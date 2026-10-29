package dev.hdt.hdt_client

import android.media.Image
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.os.Bundle
import androidx.camera.core.ImageProxy

/**
 * カメラの 1 フレーム（YUV）を、H.264（Annex B）の 1 フレームに符号化する（MediaCodec）。
 * Web 版（sender.html）と同じく、1 フレーム = 1 メッセージで送れる形にする。
 *   ・キーフレームの前には、SPS/PPS を付ける（途中から見る人が、デコードできるように）
 *   ・fps が低いときは、毎フレームをキーフレームにする（呼び出し側が、forceKey で指定）
 * 呼び出しは、1 本のスレッド（カメラの解析スレッド）からだけ。
 */
class H264Encoder(private val onFrame: (data: ByteArray, key: Boolean) -> Unit) {
    private var codec: MediaCodec? = null
    private var csd: ByteArray? = null // SPS + PPS（Annex B）

    var width = 0
        private set
    var height = 0
        private set
    val started get() = codec != null

    fun start(w: Int, h: Int, bitrate: Int, fps: Int) {
        stop()
        val fmt = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, w, h).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible)
            setInteger(MediaFormat.KEY_BIT_RATE, bitrate)
            setInteger(MediaFormat.KEY_FRAME_RATE, fps.coerceAtLeast(1))
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 10) // 10 秒ごと（それ以外は、要求したときと、低 fps のとき）
            setInteger(MediaFormat.KEY_BITRATE_MODE, MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR)
        }
        val c = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
        c.configure(fmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        c.start()
        codec = c
        width = w
        height = h
        csd = null
    }

    fun stop() {
        val c = codec ?: return
        codec = null
        try {
            c.stop()
        } catch (_: Exception) {
        }
        c.release()
    }

    /** 次のフレームを、キーフレームにする。 */
    fun requestKeyFrame() {
        codec?.setParameters(Bundle().apply { putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0) })
    }

    /** fps が変わったとき、ビットレートも合わせる。 */
    fun setBitrate(bitrate: Int) {
        codec?.setParameters(Bundle().apply { putInt(MediaCodec.PARAMETER_KEY_VIDEO_BITRATE, bitrate) })
    }

    /** 1 フレームを符号化する。入力の空きが無ければ、捨てる（false）。 */
    fun encode(img: ImageProxy, ptsUs: Long, forceKey: Boolean): Boolean {
        val c = codec ?: return false
        if (forceKey) requestKeyFrame()
        val idx = c.dequeueInputBuffer(0)
        if (idx < 0) {
            drain(c)
            return false
        }
        val dst = c.getInputImage(idx)
        if (dst == null) {
            c.queueInputBuffer(idx, 0, 0, ptsUs, 0)
            return false
        }
        copyPlane(img.planes[0], dst.planes[0], width, height)
        copyPlane(img.planes[1], dst.planes[1], width / 2, height / 2)
        copyPlane(img.planes[2], dst.planes[2], width / 2, height / 2)
        c.queueInputBuffer(idx, 0, width * height * 3 / 2, ptsUs, 0)
        drain(c)
        return true
    }

    /** 符号化できたものを、取り出して渡す。 */
    private fun drain(c: MediaCodec) {
        val info = MediaCodec.BufferInfo()
        while (true) {
            val out = c.dequeueOutputBuffer(info, 0)
            if (out == MediaCodec.INFO_TRY_AGAIN_LATER) return
            if (out < 0) continue // 形式の変更など。読み捨てる
            val buf = c.getOutputBuffer(out)
            if (buf != null && info.size > 0) {
                val data = ByteArray(info.size)
                buf.position(info.offset)
                buf.limit(info.offset + info.size)
                buf.get(data)
                if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0) {
                    csd = data
                } else {
                    val key = info.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME != 0
                    // 機種によっては、キーフレームに SPS/PPS が付いてこない。付けて渡す
                    val head = csd
                    onFrame(if (key && head != null && !startsWithSps(data)) head + data else data, key)
                }
            }
            c.releaseOutputBuffer(out, false)
        }
    }

    private fun startsWithSps(d: ByteArray): Boolean {
        val i = if (d.size > 4 && d[2].toInt() == 0 && d[3].toInt() == 1) 4 else 3
        return d.size > i && (d[i].toInt() and 0x1f) == 7
    }

    /** カメラの 1 面（Y・U・V のどれか）を、符号化器の入力の面へ写す。行の幅（rowStride）と、画素の間隔（pixelStride）の違いを吸収する。 */
    private fun copyPlane(src: ImageProxy.PlaneProxy, dst: Image.Plane, w: Int, h: Int) {
        val sb = src.buffer
        val db = dst.buffer
        val sRow = src.rowStride
        val sPix = src.pixelStride
        val dRow = dst.rowStride
        val dPix = dst.pixelStride
        if (sPix == 1 && dPix == 1) {
            for (row in 0 until h) { // 速い道：行ごとに、まとめて写す
                val s = sb.duplicate()
                s.position(row * sRow)
                s.limit(row * sRow + w)
                val d = db.duplicate()
                d.position(row * dRow)
                d.put(s)
            }
        } else {
            for (row in 0 until h) { // 画素の間隔が違うとき（U と V が交互に並ぶ形など）：1 画素ずつ
                val sBase = row * sRow
                val dBase = row * dRow
                for (col in 0 until w) {
                    db.put(dBase + col * dPix, sb.get(sBase + col * sPix))
                }
            }
        }
    }
}
