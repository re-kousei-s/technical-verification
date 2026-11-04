"""キューから取り出した 1 フレームを処理する。

  JPEG をデコード → 検出（人の枠）→ 追跡 → 線の通過を判定 → DB に保存 → Redis に出力
"""

import logging
import time

import cv2
import numpy as np

from common.live import now_ms, ts_iso
from common.messages import build_message
from common.tiling import detect_tiled
from libs.settings import DETECTOR, STALE_MS

log = logging.getLogger("worker")


class FrameProcessor:
    def __init__(self, registry, detector, writer, output, stats):
        self.registry = registry  # 端末の設定と、追跡の状態
        self.detector = detector  # 人を検出するモデル
        self.writer = writer  # DB への保存
        self.output = output  # Redis への出力
        self.stats = stats

    def handle(self, fields):
        """キューの 1 エントリ（端末ID・撮影時刻・JPEG）を処理する。"""
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
        counter, tiles = self.registry.trackers_for(camera_id, w, h)

        # 1) 検出（画面を分割する設定なら、タイルごとに検出して結果を合わせる）
        t0 = time.perf_counter()
        boxes, scores = detect_tiled(self.detector.detect, frame, tiles)
        infer_ms = (time.perf_counter() - t0) * 1000

        # 2) 追跡（人ごとに ID を付け続ける）
        n_events = len(counter.events)
        message = build_message(
            camera_id=camera_id, floor=cam.get("floor"), ts=ts_iso(ts_ms), w=w, h=h, model=DETECTOR,
            boxes=boxes, scores=scores, infer_ms=infer_ms, frame_idx=0, video_t=0,
        )
        tracked = counter.process(message)

        # 3) 通過の判定：この 1 フレームで新しく起きた通過（どの線を、どちら向きに越えたか）
        events = counter.events[n_events:]
        lag_ms = max(0, now_ms() - ts_ms)  # 撮ってから、処理し終えるまでの遅れ

        # 4) 保存と出力
        self.writer.write(camera_id, cam, ts_ms, w, h, events, len(boxes), len(tracked), infer_ms, lag_ms)
        self.output.publish_result(camera_id, ts_ms, w, h, tracked, events, infer_ms, lag_ms, counter.debug)
        self.output.publish_image(camera_id, frame, tracked, cam)
        self.stats.add(infer_ms, lag_ms)

        for e in events:
            log.info("通過 %s %s（%s）track=%d", camera_id, e[1].upper(), e[5], e[2])
