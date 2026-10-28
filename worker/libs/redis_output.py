"""認識の結果を Redis に出す（バックエンドが読んで、スマホ・管理画面に見せる）。

  result:{端末ID}     最新の認識結果（検出枠・追跡ID・最近の通過）。スマホの送信ページが映像に重ねる
  annotated:{端末ID}  検出枠つきの画像（JPEG）。管理画面のカードに出す
  worker:{名前}       worker のハートビート（生きているか、処理の速さ）
"""

import json
import time
from collections import deque

import numpy as np

from common.live import now_ms
from libs.annotator import Annotator
from libs.settings import ANNOTATE_EVERY_S, DETECTOR, NAME, OWNED, RESULT_MIN_SCORE


class RedisOutput:
    def __init__(self, rdb, stats):
        self.r = rdb
        self.stats = stats
        self.annotator = Annotator()
        self._last_image_at = {}  # 端末ID → 画像を最後に出した時刻
        self._recent_events = {}  # 端末ID → 最近の通過（最大 5 件）

    def publish_result(self, camera_id, ts_ms, w, h, tracked, new_events, infer_ms, lag_ms):
        """最新の認識結果を出す。枠の座標は「画面に対する割合」（0〜1）にしてある。"""
        recent = self._recent_events.setdefault(camera_id, deque(maxlen=5))
        for e in new_events:
            recent.append({"ts_ms": ts_ms, "dir": e[1], "id": e[2], "line": e[5]})

        boxes = []  # [x1, y1, x2, y2, 追跡ID, スコア]
        if len(tracked):
            scale = np.array([w, h, w, h], dtype=np.float32)
            for xyxy, tid, conf in zip(tracked.xyxy / scale, tracked.tracker_id, tracked.confidence):
                if conf >= RESULT_MIN_SCORE:
                    boxes.append([round(float(v), 4) for v in xyxy] + [int(tid), round(float(conf), 2)])

        self.r.set(f"result:{camera_id}", json.dumps({
            "ts_ms": ts_ms, "published_ms": now_ms(), "w": w, "h": h, "boxes": boxes,
            "events": list(recent), "infer_ms": round(infer_ms), "lag_ms": round(lag_ms),
        }), ex=10)  # 10 秒で消える。送信が止まれば、古い枠は出なくなる

    def publish_image(self, camera_id, frame, tracked, cam):
        """検出枠つきの画像を出す。毎フレームは描かず、ANNOTATE_EVERY_S 秒に 1 回だけ。"""
        now = time.time()
        if now - self._last_image_at.get(camera_id, 0) < ANNOTATE_EVERY_S:
            return
        self._last_image_at[camera_id] = now
        jpeg = self.annotator.render(camera_id, frame, tracked, cam)
        if jpeg:
            self.r.set(f"annotated:{camera_id}", jpeg, ex=120)

    def heartbeat(self):
        """生きていることと、処理の速さを知らせる（30 秒で消える。止まれば管理画面に「停止」と出る）。"""
        self.r.hset(f"worker:{NAME}", mapping={
            "last_seen_ms": now_ms(), "detector": DETECTOR, "partitions": ",".join(map(str, OWNED)),
            "processed": self.stats.processed, "errors": self.stats.errors,
            "infer_ms_avg": self.stats.infer_ms_avg, "lag_ms_avg": self.stats.lag_ms_avg,
        })
        self.r.expire(f"worker:{NAME}", 30)
