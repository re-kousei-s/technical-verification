"""カウントラインを画像に描く（検出枠つきの画像に、線と IN の向きの矢印を重ねる）。"""

import cv2
import numpy as np

from common.tiling import line_to_px


def draw_line(img, line_norm, label=True):
    """赤い線（●が始点）と、緑の矢印を描く。矢印の向きに越えたら IN、逆が OUT。

    line_norm は [[x1, y1], [x2, y2]]（画面に対する割合）。
    """
    h, w = img.shape[:2]
    (x1, y1), (x2, y2) = line_to_px(line_norm, w, h)
    p1, p2 = (int(x1), int(y1)), (int(x2), int(y2))
    thick = max(2, w // 400)
    cv2.line(img, p1, p2, (0, 0, 255), thick)
    cv2.circle(img, p1, thick * 3, (0, 0, 255), -1)  # 始点

    # IN の向き = 線の向きベクトルの、画面上の左側（y が下向きの座標では (dy, -dx)）
    d = np.array([x2 - x1, y2 - y1], float)
    n = np.array([d[1], -d[0]]) / (np.linalg.norm(d) + 1e-9)
    mid = np.array([(x1 + x2) / 2, (y1 + y2) / 2])
    length = 0.12 * min(w, h)
    tail, head = mid - n * length / 2, mid + n * length / 2
    cv2.arrowedLine(img, tuple(tail.astype(int)), tuple(head.astype(int)), (0, 255, 0), thick * 2, tipLength=0.3)
    if label:
        font = max(0.8, w / 1600)
        cv2.putText(img, "IN", tuple((head + n * 20).astype(int)), cv2.FONT_HERSHEY_SIMPLEX, font, (0, 255, 0), thick)
        cv2.putText(img, "OUT", tuple((tail - n * 40).astype(int)), cv2.FONT_HERSHEY_SIMPLEX, font, (0, 128, 255), thick)
    return img
