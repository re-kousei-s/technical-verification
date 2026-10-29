package dev.hdt.hdt_client

import android.os.Handler
import android.os.Looper
import io.flutter.plugin.common.EventChannel

/**
 * サービス（Kotlin）から、Flutter の画面へ知らせるための窓口。
 * 画面が開いていないとき（sink が無いとき）は、何もしない。
 */
object EventBus {
    @Volatile
    var sink: EventChannel.EventSink? = null
    private val main = Handler(Looper.getMainLooper())

    fun emit(event: Map<String, Any?>) {
        val s = sink ?: return
        main.post { s.success(event) } // EventSink は、メインスレッドから呼ぶ決まり
    }
}
