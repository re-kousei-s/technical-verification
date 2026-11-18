"""① 検出：キューから取り出した 1 フレームから、人の枠を出して、② 追跡へ流す。

  JPEG をデコード → 検出（人の枠とスコア）→ Redis（dets:p…）へ流す
画像を見るのは、ここだけ。追跡（人ごとの ID）と判定（IN/OUT）は、後ろの段（tracker.py・judge.py）が行う。
"""

import json
import logging
import time

import cv2
import numpy as np

from common.live import dets_stream, now_ms
from libs.once import Once
from libs.settings import DETECTOR, RECORD_DIR, STALE_MS

log = logging.getLogger("worker")

STREAM_MAXLEN = 5000  # 検出の結果のストリームに、残す最大の件数（後ろの段が止まっても、溜まりすぎない）


class FrameProcessor:
    def __init__(self, registry, detector, rdb, output, stats):
        self.registry = registry  # 端末の設定
        self.detector = detector  # 人を検出するモデル
        self.r = rdb
        self.output = output  # 検出枠つきの画像を出す
        self.stats = stats
        self.once = Once()  # 同じフレームを、2 度検出しない

    def handle(self, fields, stream):
        """キューの 1 エントリ（端末ID・撮影時刻・JPEG）を処理する。stream は、読んだ分割（frames:p3 など）。"""
        camera_id = fields[b"camera_id"].decode()
        cam = self.registry.get(camera_id)
        if cam is None:
            log.warning("未登録の端末のフレームを捨てた: %s", camera_id)
            return
        ts_ms = int(fields[b"ts_ms"])
        if not self.once.first(camera_id, ts_ms):
            return  # 処理済みのフレーム（再配達・送り直し）
        # 溜まった古いフレームは、処理しない（あとから処理しても、通過だけが遅れて数に加わる）。捨てた数は stats.stale に数える
        if now_ms() - ts_ms > STALE_MS:
            self.stats.stale += 1
            return

        frame = cv2.imdecode(np.frombuffer(fields[b"jpeg"], np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("JPEG をデコードできない")
        h, w = frame.shape[:2]

        t0 = time.perf_counter()
        boxes, scores = self.detector.detect(frame)
        infer_ms = (time.perf_counter() - t0) * 1000
        dets = [[*(round(float(v), 1) for v in b[:4]), round(float(s), 3)] for b, s in zip(boxes, scores)]

        # 同じ端末は、同じ分割の番号へ流す（順番が保たれる）
        self.r.xadd(dets_stream(stream), {"data": json.dumps({
            "camera_id": camera_id, "ts_ms": ts_ms, "w": w, "h": h, "model": DETECTOR,
            "infer_ms": round(infer_ms, 1), "dets": dets,
        })}, maxlen=STREAM_MAXLEN, approximate=True)

        if RECORD_DIR:
            self._record(camera_id, ts_ms, w, h, dets)
        self.output.publish_image(camera_id, frame, dets, cam)
        self.stats.add(infer_ms, max(0, now_ms() - ts_ms))

    @staticmethod
    def _record(camera_id, ts_ms, w, h, dets):
        """検出の結果を、1 フレーム 1 行で、追記する（日ごと・端末ごとのファイル）。記録に失敗しても、処理は止めない。"""
        try:
            day = time.strftime("%Y%m%d", time.gmtime(ts_ms / 1000))
            with open(f"{RECORD_DIR}/{camera_id}-{day}.jsonl", "a") as fp:
                fp.write(json.dumps({"ts_ms": ts_ms, "w": w, "h": h, "dets": dets}) + "\n")
        except OSError as e:
            log.warning("検出の記録に失敗: %s", e)
