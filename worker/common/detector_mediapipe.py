"""MediaPipe Object Detector（人物のみ）。edge_device と、ライブ検証の worker が共有する。"""

import urllib.request

import os
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

# モデルの重みの置き場所（コンテナでは /models に、ホストの worker/models をマウントしている）
MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/models"))

_BASE = "https://storage.googleapis.com/mediapipe-models/object_detector"
# 名前 -> (モデル, 量子化)。ssd_mobilenet_v2 は int8 版が公開されていない
MODELS = {
    "ssd_mobilenet_v2_fp32": ("ssd_mobilenet_v2", "float32"),
    "ssd_mobilenet_v2_fp16": ("ssd_mobilenet_v2", "float16"),
    "efficientdet_lite0_int8": ("efficientdet_lite0", "int8"),
    "efficientdet_lite0_fp32": ("efficientdet_lite0", "float32"),
    "efficientdet_lite2_int8": ("efficientdet_lite2", "int8"),
    "efficientdet_lite2_fp32": ("efficientdet_lite2", "float32"),
}


def model_file(name):
    if name not in MODELS:
        raise SystemExit(f"未知のモデル {name}。使えるもの: {list(MODELS)}")
    arch, quant = MODELS[name]
    path = MODELS_DIR / "mediapipe" / f"{name}.tflite"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{_BASE}/{arch}/{quant}/latest/{arch}.tflite"
        print(f"[download] {url}")
        urllib.request.urlretrieve(url, path)
    return path


class MediaPipeDetector:
    def __init__(self, name, min_score):
        options = vision.ObjectDetectorOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_file(name))),
            running_mode=vision.RunningMode.IMAGE,
            score_threshold=min_score,
            category_allowlist=["person"],
            max_results=-1,
        )
        self.detector = vision.ObjectDetector.create_from_options(options)

    def detect(self, image_bgr):
        rgb = np.ascontiguousarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
        result = self.detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        boxes, scores = [], []
        for d in result.detections:
            b = d.bounding_box
            boxes.append([b.origin_x, b.origin_y, b.origin_x + b.width, b.origin_y + b.height])
            scores.append(d.categories[0].score)
        return np.array(boxes, np.float32).reshape(-1, 4), np.array(scores, np.float32)
