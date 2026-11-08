"""見た目：検出した枠の、服の色のヒストグラム。追跡で、人が重なったときの、ID の取り違えを減らすために使う（lowfps_tracker.py）。

胴体の部分（枠の高さの 15〜55%、幅の中央 60%）の、HSV の色相 12 × 彩度 4 のヒストグラム（合計 1）。暗すぎる画素（明るさ 30 以下）は除く。
"""

import cv2
import numpy as np


def torso_hist(img, box):
    """枠 box（[x1, y1, x2, y2]、ピクセル）の、服の色のヒストグラム（48 個）。胴体が小さすぎるときは None。"""
    hh, ww = img.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in box[:4]]
    h, w = y2 - y1, x2 - x1
    xa, xb = int(max(0, x1 + 0.2 * w)), int(min(ww, x2 - 0.2 * w))
    ya, yb = int(max(0, y1 + 0.15 * h)), int(min(hh, y1 + 0.55 * h))
    if xb - xa < 3 or yb - ya < 3:
        return None
    hsv = cv2.cvtColor(img[ya:yb, xa:xb], cv2.COLOR_BGR2HSV)
    mask = (hsv[..., 2] > 30).astype(np.uint8)
    hist = cv2.calcHist([hsv], [0, 1], mask, [12, 4], [0, 180, 0, 256]).flatten()
    s = float(hist.sum())
    return (hist / s).astype(np.float32) if s > 0 else None
