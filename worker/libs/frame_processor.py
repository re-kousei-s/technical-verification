"""キューから取り出した 1 フレームを処理する（検出 + 追跡の worker）。

  JPEG をデコード → 検出（人の枠）→ 追跡（人ごとの ID）→ 人の状態管理（判定に渡す座標）→ Redis に流す
  （線を越えたかの判定は、judge の service が、流した結果を読んで行う。画像は、ここまで）
"""

import json
import logging
import time

import cv2
import numpy as np

from aggregator.tracking import tracks_of
from common.live import now_ms, tracks_stream
from common.tiling import detect_tiled
from libs.settings import DETECTOR, STALE_MS

log = logging.getLogger("worker")

TRACKS_MAXLEN = 5000  # 追跡の結果のストリームに、残す最大の件数（judge が止まっても、溜まりすぎない）


class FrameProcessor:
    def __init__(self, registry, detector, rdb, output, stats):
        self.registry = registry  # 端末の設定と、追跡の状態
        self.detector = detector  # 人を検出するモデル
        self.r = rdb
        self.output = output  # 検出枠つきの画像を出す
        self.stats = stats

    def handle(self, fields, stream):
        """キューの 1 エントリ（端末ID・撮影時刻・JPEG）を処理する。stream は、読んだ分割（frames:p3 など）。"""
        camera_id = fields[b"camera_id"].decode()
        cam = self.registry.get(camera_id)
        if cam is None:
            log.warning("未登録の端末のフレームを捨てた: %s", camera_id)
            return
        ts_ms = int(fields[b"ts_ms"])
        # 溜まった古いフレームは、処理しない。あとから処理しても、通過だけが遅れて数に加わる（誤解のもと）。
        # worker が追いつかないときや、再起動した直後に起きる。捨てた数は、stats.stale に数える
        if now_ms() - ts_ms > STALE_MS:
            self.stats.stale += 1
            return

        frame = cv2.imdecode(np.frombuffer(fields[b"jpeg"], np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("JPEG をデコードできない")
        h, w = frame.shape[:2]
        tracker, tiles, lifecycle = self.registry.tracker_for(camera_id, w, h)

        # 1) 検出（画面を分割する設定なら、タイルごとに検出して結果を合わせる）
        t0 = time.perf_counter()
        boxes, scores = detect_tiled(self.detector.detect, frame, tiles)
        infer_ms = (time.perf_counter() - t0) * 1000

        # 2) 追跡（人ごとに ID を付け続ける）
        tracked = tracker.update(boxes, scores, ts_ms / 1000.0)
        tracks = tracks_of(tracked)
        events, alias = lifecycle.update(tracks)  # 人の状態管理：判定に渡す座標を作る（starting・moving・deleted）

        # 3) 追跡の結果を、判定の service へ流す（同じ端末は、同じ分割に届くので、順番が保たれる）
        self.r.xadd(tracks_stream(stream), {"data": json.dumps({
            "camera_id": camera_id, "ts_ms": ts_ms, "w": w, "h": h, "model": DETECTOR,
            "n_dets": len(boxes), "infer_ms": round(infer_ms, 1), "tracks": tracks, "events": events, "alias": alias,
        })}, maxlen=TRACKS_MAXLEN, approximate=True)

        self.output.publish_image(camera_id, frame, tracked, cam)
        self.stats.add(infer_ms, max(0, now_ms() - ts_ms))
