package dev.hdt.hdt_client

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import androidx.camera.core.ImageProxy
import androidx.lifecycle.LifecycleService
import org.json.JSONObject

/**
 * 映像を送る前面サービス。サーバーの指示（状態）に従って、カメラ → H.264 → WebSocket と流す。
 *
 * 画面ロック中も動かすための仕組み：
 *   ・前面サービス（種類 camera）。通知が出ている間は、アプリの画面を閉じても、画面ロックしても、カメラを使える
 *   ・部分的な wake lock（CPU が眠らない）と、Wi-Fi lock（Wi-Fi が眠らない）
 *   ・サーバーとの接続は、このサービスが持つ（Flutter の画面に依存しない）。切れたら、つなぎ直す
 * 送るかどうか・fps・解像度は、すべてサーバー（管理画面）が決める。
 */
class StreamService : LifecycleService(), ControlSocket.Listener {
    private val main = Handler(Looper.getMainLooper())
    private var socket: ControlSocket? = null
    private lateinit var camera: CameraSource
    private val encoder = H264Encoder { data, _ -> onEncoded(data) }

    private var wake: PowerManager.WakeLock? = null
    private var wifi: WifiManager.WifiLock? = null

    // サーバーが決めた状態
    @Volatile private var sendFps = 0.0
    @Volatile private var recognize = false
    @Volatile private var preview = false
    @Volatile private var idrWanted = false
    private var camRes = "1280x960"
    private var camZoom: Float? = null
    private var camDevice: String? = null
    private var linesJson = ""

    // カメラの状態（メインスレッドだけで触る）
    private var boundKey: String? = null
    @Volatile private var actualW = 0
    @Volatile private var actualH = 0

    // 解析スレッドだけで触る
    private var nextSendAt = 0L
    private var nextThumbAt = 0L
    private var lastFps = 0.0

    // 統計
    @Volatile private var sent = 0
    @Volatile private var dropped = 0
    @Volatile private var bytes = 0L
    private var bytesAt = SystemClock.elapsedRealtime()
    @Volatile private var kbps = 0
    @Volatile private var message = ""

    override fun onCreate() {
        super.onCreate()
        instance = this
        camera = CameraSource(this, this) { img -> onFrame(img) }
        loadPrefs()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        if (intent?.action == ACTION_STOP) {
            shutdown()
            stopSelf()
            return START_NOT_STICKY
        }
        val prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val url = intent?.getStringExtra("url") ?: prefs.getString("url", null)
        val id = intent?.getStringExtra("id") ?: prefs.getString("id", null)
        val insecure = intent?.getBooleanExtra("insecure", true) ?: prefs.getBoolean("insecure", true)
        if (url == null || id == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        prefs.edit().putString("url", url).putString("id", id).putBoolean("insecure", insecure).apply()

        startForegroundNow()
        acquireLocks()
        running = true
        socket?.close()
        socket = ControlSocket(url, id, insecure, this).also { it.connect() }
        emitStatus()
        return START_STICKY // 止められても、システムが再起動してくれる（保存した設定で、つなぎ直す）
    }

    override fun onDestroy() {
        shutdown()
        instance = null
        super.onDestroy()
    }

    private fun shutdown() {
        running = false
        socket?.close()
        socket = null
        sendFps = 0.0
        main.post {
            encoder.stop()
            camera.unbind()
            boundKey = null
        }
        wake?.takeIf { it.isHeld }?.release()
        wifi?.takeIf { it.isHeld }?.release()
        emitStatus()
    }

    // ---- 前面サービスの通知・ロック ------------------------------------------------------

    private fun startForegroundNow() {
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "映像の送信", NotificationManager.IMPORTANCE_LOW))
        }
        val n = buildNotification("起動しています…")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA)
        } else {
            startForeground(NOTIF_ID, n)
        }
    }

    private fun buildNotification(text: String): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(
            this, 1, Intent(this, StreamService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE,
        )
        val b = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) Notification.Builder(this, CHANNEL) else Notification.Builder(this)
        return b.setContentTitle("人検出クライアント")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(android.R.drawable.ic_media_pause, "停止", stop).build())
            .build()
    }

    @Suppress("DEPRECATION")
    private fun acquireLocks() {
        if (wake == null) {
            wake = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "hdt:stream")
        }
        if (wake?.isHeld != true) wake?.acquire()
        if (wifi == null) {
            val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            wifi = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "hdt:stream")
        }
        if (wifi?.isHeld != true) wifi?.acquire()
    }

    // ---- サーバーからの指示 --------------------------------------------------------------

    override fun onOpen() {
        message = ""
        reportCaps()
        emitStatus()
    }

    override fun onClosed(code: Int, reason: String) {
        sendFps = 0.0 // つながっていない間は、送らない（カメラも止める）
        message = when (code) {
            4404 -> "サーバーに登録がありません。アプリで登録し直してください"
            4410 -> "この端末は、別の画面で開かれました"
            else -> if (code == -1) "サーバーにつながりません（$reason）" else ""
        }
        main.post { refreshCamera() }
        emitStatus()
    }

    /** {"recognize","send_fps","preview","idr","camera":{res,zoom,device_id},"lines":[...]} */
    override fun onState(state: JSONObject) {
        recognize = state.optBoolean("recognize")
        val newFps = state.optDouble("send_fps", 0.0).coerceAtMost(CameraSource.MAX_CAPTURE_FPS.toDouble()) // 送るのも、最大 15fps
        val newPreview = state.optBoolean("preview")
        if (state.optBoolean("idr")) idrWanted = true

        var cameraChanged = false
        state.optJSONObject("camera")?.let { c ->
            val res = c.optString("res", "")
            val dev = c.optString("device_id", "")
            val zoom = if (c.has("zoom")) c.optDouble("zoom").toFloat() else null
            if (res.isNotEmpty() && res != camRes) { camRes = res; cameraChanged = true }
            if (dev.isNotEmpty() && dev != camDevice) { camDevice = dev; cameraChanged = true }
            if (zoom != null && zoom != camZoom) { camZoom = zoom; cameraChanged = true }
            if (cameraChanged) savePrefs()
        }
        state.optJSONArray("lines")?.toString()?.let { s ->
            if (s != linesJson) {
                linesJson = s
                EventBus.emit(mapOf("type" to "lines", "lines" to jsonToList(state.getJSONArray("lines"))))
            }
        }

        val changed = newFps != sendFps || newPreview != preview || cameraChanged
        sendFps = newFps
        preview = newPreview
        if (changed) main.post { if (cameraChanged) boundKey = null; refreshCamera() }
        emitStatus()
    }

    // ---- カメラの入り切り（メインスレッド） --------------------------------------------------

    /** 送る必要がある（または、画面で見ている）間だけ、カメラを動かす。電池を節約するため。 */
    fun refreshCamera() {
        val need = running && (sendFps > 0 || uiVisible)
        if (!need) {
            if (boundKey != null) {
                camera.unbind()
                boundKey = null
            }
            encoder.stop()
            return
        }
        if (sendFps <= 0) encoder.stop()
        val (w, h) = targetSize()
        val key = "$w x $h|$camDevice|$camZoom"
        if (key == boundKey) return
        boundKey = key
        camera.bind(w, h, camDevice, camZoom) { ok, err ->
            if (!ok) {
                boundKey = null
                message = "カメラを開けません: $err"
                emitStatus()
            } else {
                reportCaps()
            }
        }
    }

    /** 見られていない間は、解像度を落として送る（認識には、元の解像度は要らない）。 */
    private fun targetSize(): Pair<Int, Int> {
        val parts = camRes.split("x")
        var w = parts.getOrNull(0)?.toIntOrNull() ?: 1280
        var h = parts.getOrNull(1)?.toIntOrNull() ?: 960
        if (!preview && w > RECOG_WIDTH) {
            h = (h * RECOG_WIDTH / w) and 1.inv()
            w = RECOG_WIDTH
        }
        return w to h
    }

    private fun reportCaps() {
        val s = socket ?: return
        if (!s.isOpen) return
        try {
            val actual = if (actualW > 0) intArrayOf(actualW, actualH) else null
            s.sendText(CameraCaps.report(this, camDevice, camRes, actual).toString())
        } catch (_: Exception) {
            // カメラの一覧が取れないときは、報告しない
        }
    }

    // ---- フレームの処理（解析スレッド） --------------------------------------------------------

    private fun onFrame(img: ImageProxy) {
        try {
            val now = SystemClock.elapsedRealtime()
            actualW = img.width
            actualH = img.height
            if (uiVisible && now >= nextThumbAt) { // 画面で見ている間は、1 秒に 1 枚、狙いを定める用の画像を渡す
                nextThumbAt = now + 1000
                EventBus.emit(mapOf("type" to "thumb", "bytes" to YuvUtil.toJpeg(img, 55)))
            }
            val fps = sendFps
            val s = socket
            if (fps <= 0 || s == null || !s.isOpen) return
            if (now < nextSendAt) return
            nextSendAt = now + (1000.0 / fps).toLong() - 5

            if (!encoder.started || encoder.width != img.width || encoder.height != img.height) {
                encoder.start(img.width, img.height, bitrateFor(img.width, img.height, fps), fps.toInt())
                idrWanted = true
            } else if (fps != lastFps) {
                encoder.setBitrate(bitrateFor(img.width, img.height, fps))
            }
            lastFps = fps
            val key = idrWanted || fps <= 2 // 低 fps は、毎フレームをキーフレームに（見始めても、すぐ映る）
            idrWanted = false
            if (!encoder.encode(img, now * 1000, key)) dropped++
        } catch (e: Exception) {
            message = "符号化エラー: ${e.message}"
        } finally {
            img.close()
        }
    }

    /** 1 フレームぶんの H.264。送れなければ、捨てて、次をキーフレームにする。 */
    private fun onEncoded(data: ByteArray) {
        val s = socket
        if (s != null && s.sendBinary(data)) {
            sent++
            bytes += data.size
            val now = SystemClock.elapsedRealtime()
            if (now - bytesAt >= 1000) {
                kbps = (bytes * 8 / 1000 / ((now - bytesAt) / 1000.0)).toInt()
                bytes = 0
                bytesAt = now
                emitStatus()
            }
        } else {
            dropped++
            idrWanted = true
        }
    }

    /** 解像度に比例させ、fps が上がるぶんも増やす（5fps＝基準、上限 4Mbps）。 */
    private fun bitrateFor(w: Int, h: Int, fps: Double): Int {
        val base = (1_000_000.0 * w * h / (1280 * 720)).coerceIn(600_000.0, 3_000_000.0)
        return (base * (1 + (fps - 5).coerceAtLeast(0.0) / 12.5)).coerceAtMost(4_000_000.0).toInt()
    }

    // ---- 画面への知らせ ---------------------------------------------------------------

    fun onUiVisibilityChanged() = main.post { refreshCamera() }

    private fun emitStatus() {
        val open = socket?.isOpen == true
        EventBus.emit(
            mapOf(
                "type" to "status", "running" to running, "connected" to open, "recognize" to recognize,
                "sendFps" to sendFps, "preview" to preview, "width" to actualW, "height" to actualH,
                "kbps" to kbps, "sent" to sent, "dropped" to dropped, "message" to message,
            ),
        )
        if (running) {
            val text = if (!open) "サーバーに接続中…" else if (sendFps > 0) "${if (recognize) "認識中" else "プレビュー配信中"} ${sendFps.toInt()}fps" else "待機中"
            getSystemService(NotificationManager::class.java).notify(NOTIF_ID, buildNotification(text))
        }
    }

    private fun jsonToList(a: org.json.JSONArray): List<Map<String, Any?>> = (0 until a.length()).map { i ->
        val o = a.getJSONObject(i)
        val pts = o.getJSONArray("line")
        mapOf(
            "name" to o.optString("name"),
            "line" to (0 until pts.length()).map { j -> listOf(pts.getJSONArray(j).getDouble(0), pts.getJSONArray(j).getDouble(1)) },
        )
    }

    private fun loadPrefs() {
        val p = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        camRes = p.getString("res", camRes) ?: camRes
        camDevice = p.getString("device", null)
        if (p.contains("zoom")) camZoom = p.getFloat("zoom", 1f)
    }

    private fun savePrefs() {
        getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().apply {
            putString("res", camRes)
            putString("device", camDevice)
            camZoom?.let { putFloat("zoom", it) }
        }.apply()
    }

    companion object {
        const val ACTION_START = "dev.hdt.hdt_client.START"
        const val ACTION_STOP = "dev.hdt.hdt_client.STOP"
        private const val CHANNEL = "hdt_stream"
        private const val NOTIF_ID = 1
        private const val PREFS = "hdt"
        private const val RECOG_WIDTH = 960 // 見られていない間（認識だけ）に送る映像の横幅

        @Volatile var running = false
        @Volatile var uiVisible = false
        @Volatile var instance: StreamService? = null
    }
}
