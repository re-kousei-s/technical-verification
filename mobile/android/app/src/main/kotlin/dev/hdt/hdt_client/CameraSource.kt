package dev.hdt.hdt_client

import android.content.Context
import android.util.Size
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.core.AspectRatio
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.resolutionselector.AspectRatioStrategy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import java.util.concurrent.Executors

/**
 * カメラ（CameraX）。画面には出さず、解析用の画像（YUV）だけを受け取る。
 * 前面サービス（LifecycleOwner）に結びつけるので、画面ロック中も、アプリの画面を閉じたあとも、映像が来る。
 */
@OptIn(ExperimentalCamera2Interop::class)
class CameraSource(
    private val context: Context,
    private val owner: LifecycleOwner,
    private val onFrame: (ImageProxy) -> Unit,
) {
    private val executor = Executors.newSingleThreadExecutor()
    private var provider: ProcessCameraProvider? = null
    private var camera: Camera? = null

    /** メインスレッドから呼ぶ。結果は、メインスレッドで返る。 */
    fun bind(width: Int, height: Int, deviceId: String?, zoom: Float?, done: (ok: Boolean, error: String?) -> Unit) {
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            try {
                val p = future.get()
                provider = p
                p.unbindAll()
                val analysis = buildAnalysis(width, height)
                camera = try {
                    p.bindToLifecycle(owner, selectorFor(deviceId), analysis)
                } catch (e: Exception) {
                    if (deviceId.isNullOrEmpty()) throw e
                    p.unbindAll() // 指定のカメラが無い：既定の背面カメラで、開き直す
                    p.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, buildAnalysis(width, height))
                }
                if (zoom != null) camera?.cameraControl?.setZoomRatio(zoom)
                done(true, null)
            } catch (e: Exception) {
                camera = null
                done(false, e.message ?: e.toString())
            }
        }, ContextCompat.getMainExecutor(context))
    }

    fun unbind() {
        provider?.unbindAll()
        camera = null
    }

    private fun buildAnalysis(w: Int, h: Int): ImageAnalysis {
        val ratio = if (w * 9 == h * 16) AspectRatio.RATIO_16_9 else AspectRatio.RATIO_4_3
        val selector = ResolutionSelector.Builder()
            .setAspectRatioStrategy(AspectRatioStrategy(ratio, AspectRatioStrategy.FALLBACK_RULE_AUTO))
            .setResolutionStrategy(ResolutionStrategy(Size(w, h), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER))
            .build()
        return ImageAnalysis.Builder()
            .setResolutionSelector(selector)
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST) // 追いつかないときは、古いフレームを捨てる
            .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
            .build()
            .also { it.setAnalyzer(executor) { img -> onFrame(img) } }
    }

    private fun selectorFor(id: String?): CameraSelector {
        if (id.isNullOrEmpty()) return CameraSelector.DEFAULT_BACK_CAMERA
        return CameraSelector.Builder()
            .addCameraFilter { infos -> infos.filter { Camera2CameraInfo.from(it).cameraId == id } }
            .build()
    }
}
