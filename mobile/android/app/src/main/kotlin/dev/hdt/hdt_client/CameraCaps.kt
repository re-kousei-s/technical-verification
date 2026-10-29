package dev.hdt.hdt_client

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject

/** スマホのカメラの能力（管理画面で、カメラ・解像度・ズームを選べるように、サーバーへ報告する）。 */
object CameraCaps {
    /** 解像度の候補（Web 版と同じ）。 */
    private val RESOLUTIONS = listOf(
        "1280x960" to "1280×960", "960x720" to "960×720", "1280x720" to "1280×720",
        "1920x1080" to "1920×1080", "640x480" to "640×480",
    )

    fun defaultBackId(ctx: Context): String? {
        val cm = ctx.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        return cm.cameraIdList.firstOrNull { cm.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK }
            ?: cm.cameraIdList.firstOrNull()
    }

    /** {"caps": {...}} の形で返す（サーバーは、この形で受け取る）。 */
    fun report(ctx: Context, deviceId: String?, res: String, actual: IntArray?): JSONObject {
        val cm = ctx.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        val current = deviceId ?: defaultBackId(ctx)
        val devices = JSONArray()
        for (id in cm.cameraIdList) {
            val ch = cm.getCameraCharacteristics(id)
            val facing = if (ch.get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_FRONT) "前面" else "背面"
            val focal = ch.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)?.firstOrNull()
            devices.put(JSONObject().put("id", id).put("label", "$facing $id" + if (focal != null) "（焦点距離 %.1fmm）".format(focal) else ""))
        }
        var zoom: JSONObject? = null
        if (current != null) {
            val ch = cm.getCameraCharacteristics(current)
            var min = 1f
            var max = ch.get(CameraCharacteristics.SCALER_AVAILABLE_MAX_DIGITAL_ZOOM) ?: 1f
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                ch.get(CameraCharacteristics.CONTROL_ZOOM_RATIO_RANGE)?.let { min = it.lower; max = it.upper }
            }
            if (max > min) zoom = JSONObject().put("min", min.toDouble()).put("max", max.toDouble()).put("step", 0.1).put("value", min.toDouble())
        }
        val resolutions = JSONArray()
        RESOLUTIONS.forEach { resolutions.put(JSONObject().put("value", it.first).put("label", it.second)) }
        val caps = JSONObject().put("devices", devices).put("device_id", current ?: "").put("res", res).put("resolutions", resolutions)
        if (zoom != null) caps.put("zoom", zoom)
        if (actual != null) caps.put("actual", JSONArray().put(actual[0]).put(actual[1]))
        return JSONObject().put("caps", caps)
    }
}
