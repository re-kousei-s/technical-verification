package dev.hdt.hdt_client

import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

/**
 * Flutter の画面と、前面サービスの橋渡し。
 * 映像の送信は、すべてサービスが行う。ここは、開始・停止の指示と、状態の受け渡しだけ。
 */
class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val messenger = flutterEngine.dartExecutor.binaryMessenger

        MethodChannel(messenger, "hdt/stream").setMethodCallHandler { call, result ->
            when (call.method) {
                "start" -> {
                    val intent = Intent(this, StreamService::class.java)
                        .setAction(StreamService.ACTION_START)
                        .putExtra("url", call.argument<String>("url"))
                        .putExtra("id", call.argument<String>("id"))
                        .putExtra("insecure", call.argument<Boolean>("insecure") ?: true)
                    ContextCompat.startForegroundService(this, intent)
                    result.success(null)
                }
                "stop" -> {
                    startService(Intent(this, StreamService::class.java).setAction(StreamService.ACTION_STOP))
                    result.success(null)
                }
                "isRunning" -> result.success(StreamService.running)
                "setUiVisible" -> {
                    StreamService.uiVisible = call.arguments as? Boolean ?: false
                    StreamService.instance?.onUiVisibilityChanged()
                    result.success(null)
                }
                "isIgnoringBatteryOptimizations" ->
                    result.success(getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(packageName))
                "requestIgnoreBatteryOptimizations" -> {
                    startActivity(
                        Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")),
                    )
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }

        EventChannel(messenger, "hdt/events").setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                EventBus.sink = events
            }

            override fun onCancel(arguments: Any?) {
                EventBus.sink = null
            }
        })
    }
}
