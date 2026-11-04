"""YOLOv8（ONNX、CPU の onnxruntime）で、人だけを検出する。

軽量の EfficientDet-Lite0 は、人が大量にいて重なる場面で、半数以上を見落とした（広場の動画で、基準の 41% しか見つけられなかった）。
YOLOv8n（入力 640）は、同じ CPU 2 コアで、71% を見つけた（1 枚 約 0.24 秒。Lite0 は 約 0.16 秒）。入力 960 なら 78%（約 0.54 秒）。

モデルは、ONNX に書き出したものを、MODELS_DIR/yolo/ に置く（書き出しの手順は、README の「検出器」）。
名前：yolov8n_640 → yolo/yolov8n.640.onnx（n＝最小。s なら yolov8s_640。数字は、入力の大きさ）
"""

import os
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/models"))


class YoloOnnxDetector:
    def __init__(self, name, min_score, iou=0.5):
        size_name, imgsz = name.rsplit("_", 1)  # "yolov8n_640" → ("yolov8n", "640")
        path = MODELS_DIR / "yolo" / f"{size_name}.{imgsz}.onnx"
        if not path.exists():
            raise SystemExit(f"YOLO のモデルがありません: {path}（ONNX に書き出して、置いてください）")
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(os.environ.get("ORT_THREADS", "2"))  # worker の CPU 数に合わせる
        self.sess = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self.input = self.sess.get_inputs()[0].name
        self.imgsz, self.conf, self.iou = int(imgsz), min_score, iou

    def detect(self, image_bgr):
        """(枠 xyxy の配列, スコアの配列) を返す。枠は、元の画像の座標。"""
        h, w = image_bgr.shape[:2]
        r = self.imgsz / max(h, w)  # 長い辺を、入力の大きさに合わせて、余白を足す
        nh, nw = int(round(h * r)), int(round(w * r))
        canvas = np.full((self.imgsz, self.imgsz, 3), 114, np.uint8)
        canvas[:nh, :nw] = cv2.resize(image_bgr, (nw, nh))
        x = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
        out = self.sess.run(None, {self.input: x})[0][0].T  # (候補の数, 84)：中心 x, y, 幅, 高さ, 80 クラスのスコア
        scores = out[:, 4]  # クラス 0 ＝ 人
        keep = scores >= self.conf
        out, scores = out[keep], scores[keep]
        if not len(out):
            return np.zeros((0, 4), np.float32), np.zeros(0, np.float32)
        boxes = np.stack([out[:, 0] - out[:, 2] / 2, out[:, 1] - out[:, 3] / 2,
                          out[:, 0] + out[:, 2] / 2, out[:, 1] + out[:, 3] / 2], 1) / r
        idx = cv2.dnn.NMSBoxes([[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes],
                               scores.tolist(), self.conf, self.iou)
        idx = np.array(idx).reshape(-1)
        return boxes[idx].astype(np.float32), scores[idx].astype(np.float32)
