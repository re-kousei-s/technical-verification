package dev.hdt.hdt_client

import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import androidx.camera.core.ImageProxy
import java.io.ByteArrayOutputStream

/** カメラの YUV の画像を、画面に出す用の JPEG にする（狙いを定めるための小さな画像）。 */
object YuvUtil {
    fun toJpeg(img: ImageProxy, quality: Int): ByteArray {
        val w = img.width
        val h = img.height
        val nv21 = ByteArray(w * h * 3 / 2)
        val y = img.planes[0]
        for (row in 0 until h) {
            val base = row * y.rowStride
            for (col in 0 until w) nv21[row * w + col] = y.buffer.get(base + col * y.pixelStride)
        }
        val u = img.planes[1]
        val v = img.planes[2]
        var o = w * h
        for (row in 0 until h / 2) {
            for (col in 0 until w / 2) {
                nv21[o++] = v.buffer.get(row * v.rowStride + col * v.pixelStride) // NV21 は V が先
                nv21[o++] = u.buffer.get(row * u.rowStride + col * u.pixelStride)
            }
        }
        val out = ByteArrayOutputStream()
        YuvImage(nv21, ImageFormat.NV21, w, h, null).compressToJpeg(Rect(0, 0, w, h), quality, out)
        return out.toByteArray()
    }
}
