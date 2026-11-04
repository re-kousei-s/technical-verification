"""YOLOX（ONNX、CPU の onnxruntime）で、人だけを検出する。ライセンスは Apache-2.0（YOLOv8 は AGPL-3.0 のため、使わない）。

軽量の EfficientDet-Lite0 は、人が大量にいて重なる場面で、半数以上を見落とした（広場の動画で、基準の 41% しか見つけられなかった）。
YOLOX-tiny（入力 416）は、同じ CPU 2 コアで、67% を見つけた（1 枚 約 0.15 秒。Lite0 は 約 0.16 秒）。
YOLOX-s（入力 640）なら 77%（約 0.58 秒）。

モデルは、公式の ONNX（Megvii-BaseDetection/YOLOX の releases）を、MODELS_DIR/yolox/ に置く。
名前：yolox_tiny_416 → yolox/yolox_tiny.416.onnx（s なら yolox_s_640。数字は、入力の大きさ。tiny は 416 固定）
"""

import os
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/models"))


class YoloxOnnxDetector:
    def __init__(self, name, min_score, iou=0.5):
        size_name, imgsz = name.rsplit("_", 1)  # "yolox_tiny_416" → ("yolox_tiny", "416")
        path = MODELS_DIR / "yolox" / f"{size_name}.{imgsz}.onnx"
        if not path.exists():
            raise SystemExit(f"YOLOX のモデルがありません: {path}（公式の ONNX を置いてください）")
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(os.environ.get("ORT_THREADS", "2"))  # worker の CPU 数に合わせる
        self.sess = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self.input = self.sess.get_inputs()[0].name
        self.imgsz, self.conf, self.iou = int(imgsz), min_score, iou
        # 出力は、格子（8・16・32 ピクセルごと）の相対値。元の座標にするための格子と歩幅を、先に作っておく
        grids, strides = [], []
        for s in (8, 16, 32):
            n = self.imgsz // s
            gx, gy = np.meshgrid(np.arange(n), np.arange(n))
            grids.append(np.stack([gx, gy], 2).reshape(-1, 2))
            strides.append(np.full((n * n, 1), s))
        self.grid, self.stride = np.concatenate(grids), np.concatenate(strides)

    def detect(self, image_bgr):
        """(枠 xyxy の配列, スコアの配列) を返す。枠は、元の画像の座標。"""
        h, w = image_bgr.shape[:2]
        r = self.imgsz / max(h, w)  # 長い辺を、入力の大きさに合わせて、余白を足す
        nh, nw = int(round(h * r)), int(round(w * r))
        canvas = np.full((self.imgsz, self.imgsz, 3), 114, np.uint8)
        canvas[:nh, :nw] = cv2.resize(image_bgr, (nw, nh))
        x = np.ascontiguousarray(canvas.transpose(2, 0, 1)[None], dtype=np.float32)  # BGR のまま、0〜255
        out = self.sess.run(None, {self.input: x})[0][0]  # (候補の数, 85)：x, y, 幅, 高さ, 物体らしさ, 80 クラス
        scores = out[:, 4] * out[:, 5]  # 物体らしさ × 人（クラス 0）
        keep = scores >= self.conf
        if not keep.any():
            return np.zeros((0, 4), np.float32), np.zeros(0, np.float32)
        out, scores = out[keep], scores[keep]
        xy = (out[:, :2] + self.grid[keep]) * self.stride[keep]
        wh = np.exp(out[:, 2:4]) * self.stride[keep]
        boxes = np.concatenate([xy - wh / 2, xy + wh / 2], 1) / r
        idx = cv2.dnn.NMSBoxes([[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes],
                               scores.tolist(), self.conf, self.iou)
        idx = np.array(idx).reshape(-1)
        return boxes[idx].astype(np.float32), scores[idx].astype(np.float32)
