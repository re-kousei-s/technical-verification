package dev.hdt.hdt_client

import android.os.Handler
import android.os.Looper
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * サーバーとの接続（WebSocket 1 本）。サーバーの Web 版（sender.html）と、同じ約束事。
 *   スマホ → サーバー：映像（H.264 の 1 フレームぶん、バイナリ）、カメラの能力の報告（テキスト {"caps": …}）
 *   サーバー → スマホ：状態（テキスト）{"recognize","send_fps","preview","idr","camera","lines"}
 * 切れたら、2 秒ごとにつなぎ直す。
 */
class ControlSocket(
    private val baseUrl: String, // 例 https://192.168.2.117:8000
    private val cameraId: String,
    insecure: Boolean,
    private val listener: Listener,
) {
    interface Listener {
        fun onOpen()
        fun onState(state: JSONObject)
        fun onClosed(code: Int, reason: String)
    }

    private val client: OkHttpClient = buildClient(insecure)
    private val main = Handler(Looper.getMainLooper())

    @Volatile private var ws: WebSocket? = null
    @Volatile private var wanted = false
    @Volatile var isOpen = false
        private set

    fun connect() {
        wanted = true
        open()
    }

    private fun open() {
        if (!wanted) return
        // OkHttp は、https:// の URL を、WebSocket（wss）として開ける
        val req = Request.Builder().url("$baseUrl/ws/$cameraId").build()
        ws = client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                isOpen = true
                listener.onOpen()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    listener.onState(JSONObject(text))
                } catch (_: Exception) {
                    // 読めない指示は、無視する
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = closed(code, reason)

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = closed(-1, t.message ?: "接続できません")
        })
    }

    private fun closed(code: Int, reason: String) {
        isOpen = false
        listener.onClosed(code, reason)
        // 4404＝登録がない、4410＝別の画面に置き換えられた：つなぎ直しても意味がない
        if (wanted && code != 4404 && code != 4410) main.postDelayed({ open() }, 2000)
    }

    /** 映像を送る。送信待ちが溜まっているときは、捨てる（false）。 */
    fun sendBinary(data: ByteArray): Boolean {
        val s = ws ?: return false
        if (!isOpen || s.queueSize() > MAX_QUEUED) return false
        return s.send(data.toByteString())
    }

    fun sendText(text: String) {
        if (isOpen) ws?.send(text)
    }

    fun close() {
        wanted = false
        main.removeCallbacksAndMessages(null)
        ws?.close(1000, "bye")
        ws = null
        isOpen = false
    }

    companion object {
        private const val MAX_QUEUED = 1_500_000L // 送信待ちがこれを超えたら、フレームを捨てる（通信が詰まったとき）

        private fun buildClient(insecure: Boolean): OkHttpClient {
            val b = OkHttpClient.Builder()
                .pingInterval(20, TimeUnit.SECONDS)
                .readTimeout(0, TimeUnit.MILLISECONDS) // 長時間つなぎ続ける
            if (insecure) {
                // 検証用の gateway は、自己署名の証明書。証明書の検査を省く
                val trustAll = object : X509TrustManager {
                    override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}
                    override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {}
                    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
                }
                val ctx = SSLContext.getInstance("TLS").apply { init(null, arrayOf<TrustManager>(trustAll), SecureRandom()) }
                b.sslSocketFactory(ctx.socketFactory, trustAll).hostnameVerifier { _, _ -> true }
            }
            return b.build()
        }
    }
}
