"""床の座標：斜めから撮った画像の、床の上の点を、真上から見た位置（床の座標）に直す。

画像の中の、床の上の長方形の 4 つの角（と、その縦横の比）から、画像 → 床 の射影変換（ホモグラフィ、3×3 の行列）を作る。
実際の寸法は要らない。長さは、「人の背の高さ」を 1 とした単位に、そろえる（人を物差しにする）：
  検出した人の、足元の床の座標と、枠の高さ（ピクセル）から、「人の背の高さが、床の座標で、いくつか」を、見積もり続ける（中央値）。
  判定は、この 1 人ぶん（unit）を単位に、距離を測る。カメラの角度・距離が違っても、設定値が、同じ意味になる。
床の上の点だけが、正しく変換される。足元は、床の上なので、使える。頭・体は、床の上にないので、使えない。
"""

from collections import deque

import numpy as np


def _homography(src, dst):
    """4 組の対応点（src → dst）から、3×3 の射影変換の行列を作る（直接線形法）。"""
    a = []
    for (x, y), (u, v) in zip(src, dst):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.asarray(a, float))
    h = vt[-1].reshape(3, 3)
    return h / h[2, 2]


def _signed_area(pts):
    """点の並びの、符号つきの面積（靴ひも公式。座標は、画像のまま）。"""
    return sum(pts[i][0] * pts[(i + 1) % 4][1] - pts[(i + 1) % 4][0] * pts[i][1] for i in range(4)) / 2


class FloorMap:
    """端末 1 台ぶんの、床の座標への変換。"""

    def __init__(self, img_pts, rect, frame_w, frame_h):
        """img_pts：床の上の長方形の 4 つの角（隣どうしを、順に。画面に対する割合）。1・2 番目の点の間が「横」、2・3 番目の点の間が「縦」。
        rect：その長方形の、横と縦の長さの比（[1, 1] なら正方形）。"""
        px = [(float(x) * frame_w, float(y) * frame_h) for x, y in img_pts]
        w, d = float(rect[0]), float(rect[1])
        if w <= 0 or d <= 0:
            raise ValueError("縦横の比は、正の数")
        # 1・2 番目の点の間が「横」（長さ w）、2・3 番目の点の間が「縦」（長さ d）。
        # 並びの回る向きが、床の側と、逆（鏡写し）になるときは、床の縦を、反対向きにとる。IN/OUT が、入れ替わらないようにする
        dst = [(0.0, 0.0), (w, 0.0), (w, d), (0.0, d)]
        if _signed_area(px) * _signed_area(dst) < 0:
            dst = [(0.0, 0.0), (w, 0.0), (w, -d), (0.0, -d)]
        self.h = _homography(px, dst)
        self._samples = deque(maxlen=300)  # 人の背の高さ（床の座標）の見積もり
        self._unit = None

    def to_floor(self, x, y):
        """画像の点（ピクセル）→ 床の座標。"""
        p = self.h @ np.array([x, y, 1.0])
        return np.array([p[0] / p[2], p[1] / p[2]])

    def per_pixel(self, x, y):
        """その場所での、1 ピクセルあたりの、床の座標の長さ（縦横の平均）。"""
        e = 1.0
        f0 = self.to_floor(x, y)
        j = np.column_stack([self.to_floor(x + e, y) - f0, self.to_floor(x, y + e) - f0]) / e
        return float(np.sqrt(abs(np.linalg.det(j))))

    def observe(self, x, y, h_px):
        """検出した人の、足元（x, y）と、枠の高さ（ピクセル）を渡す。人の背の高さ（床の座標）の見積もりを、更新する。"""
        pp = self.per_pixel(x, y)
        if pp > 0 and np.isfinite(pp):
            self._samples.append(pp * h_px)
            if len(self._samples) >= 10:
                self._unit = float(np.median(self._samples))

    def unit(self, x, y, h_px):
        """人 1 人ぶん（背の高さ）の長さ（床の座標）。見積もりがまだなら、その人の枠の高さから、その場で出す。"""
        if self._unit is not None:
            return self._unit
        return max(self.per_pixel(x, y) * h_px, 1e-6)
