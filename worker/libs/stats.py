"""処理した件数と、直近の処理時間・遅れの集計（ハートビートで管理画面に出す）。"""

from collections import deque

import numpy as np


class Stats:
    def __init__(self):
        self.processed = 0  # 処理したフレーム数
        self.errors = 0  # 処理に失敗したフレーム数
        self._infer_ms = deque(maxlen=50)  # 直近 50 フレームの推論時間（ミリ秒）
        self._lag_ms = deque(maxlen=50)  # 直近 50 フレームの遅れ（撮ってから処理し終えるまで）

    def add(self, infer_ms, lag_ms):
        """1 フレーム処理できたときに呼ぶ。"""
        self.processed += 1
        self._infer_ms.append(infer_ms)
        self._lag_ms.append(lag_ms)

    @property
    def infer_ms_avg(self):
        return round(float(np.mean(self._infer_ms)), 1) if self._infer_ms else 0

    @property
    def lag_ms_avg(self):
        return round(float(np.mean(self._lag_ms)), 1) if self._lag_ms else 0
