"""vision：画像から、ドア・エレベーターなどの「四角」の候補を探す小さな HTTP サービス。

Go のバックエンドが、スマホから届いた 1 枚の画像（JPEG）をここへ転送する。
OpenCV を使うので、Go ではなく Python 側に置いている。四角検出のアルゴリズムは common/quads.py。
"""

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request

from common.quads import detect_quads

app = FastAPI(title="vision")


@app.post("/detect")
async def detect(request: Request):
    """JPEG を受け取り、ドアらしい四角の候補を返す。候補は人が確認して直す前提。"""
    data = await request.body()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
    if img is None:
        raise HTTPException(422, "画像を読めない")
    return {"candidates": detect_quads(img)}


@app.get("/healthz")
async def healthz():
    return {"ok": True}
