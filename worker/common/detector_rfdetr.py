"""RF-DETR（人物のみ、CPU）。server_model と、ライブ検証の worker が共有する。"""

import time

import os
from pathlib import Path

import cv2
import numpy as np
import requests
from rfdetr import RFDETRMedium, RFDETRNano, RFDETRSmall

# モデルの重みの置き場所（コンテナでは /models に、ホストの worker/models をマウントしている）
MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/models"))

# XL / 2XL はライセンスが別なので入れない（仕様書4章）
MODELS = {
    "rfdetr_nano": (RFDETRNano, "rf-detr-nano.pth"),
    "rfdetr_small": (RFDETRSmall, "rf-detr-small.pth"),
    "rfdetr_medium": (RFDETRMedium, "rf-detr-medium.pth"),
}
PERSON_CLASS_ID = 1  # COCO の category id（RF-DETR は 1 始まりの COCO id を返す）


class RFDETRDetector:
    def __init__(self, name, min_score):
        if name not in MODELS:
            raise SystemExit(f"未知のモデル {name}。使えるもの: {list(MODELS)}")
        cls, weights = MODELS[name]
        (MODELS_DIR / "rfdetr").mkdir(parents=True, exist_ok=True)
        # 初回は重み（数百MB）をダウンロードする。回線が不安定だとタイムアウトするので数回やり直す
        for attempt in range(1, 4):
            try:
                self.model = cls(pretrain_weights=str(MODELS_DIR / "rfdetr" / weights))
                break
            except requests.exceptions.RequestException as e:
                if attempt == 3:
                    raise
                print(f"[retry {attempt}] 重みのダウンロードに失敗: {e}")
                time.sleep(10 * attempt)
        self.min_score = min_score

    def detect(self, image_bgr):
        rgb = np.ascontiguousarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
        d = self.model.predict(rgb, threshold=self.min_score)
        keep = d.class_id == PERSON_CLASS_ID
        return d.xyxy[keep].astype(np.float32), d.confidence[keep].astype(np.float32)
