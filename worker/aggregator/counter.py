"""② 追跡 と ③ 判定を、1 つにつなげたもの（評価用。_unused/tools/eval から使う）。

本番は、② 追跡（tracker.py）と ③ 判定（judge.py）が、別々の service。ここは、検出の結果（メッセージ）を順に渡すと、追跡して判定する一続きの形。
"""

import numpy as np
import supervision as sv

from aggregator.simple_tracker import SimpleTracker
from aggregator.tile_judge import TileJudge
from common.messages import ts_to_sec


class CameraCounter:
    def __init__(self, lines, frame_w, frame_h, tracker_cfg, tiles_cfg):
        """lines は [{"id", "name", "line": [[x1,y1],[x2,y2]]}, ...]（座標は画面に対する割合）。tracker_cfg・tiles_cfg は matrix.yaml の値。"""
        self.tracker = SimpleTracker(**tracker_cfg)
        self.judge = TileJudge(lines, frame_w, frame_h, **tiles_cfg)
        self.events = self.judge.events

    def process(self, msg):
        """1 フレーム（検出のメッセージ）を渡す。追跡して判定する。追跡の結果（sv.Detections、tracker_id つき）を返す。"""
        t = ts_to_sec(msg["ts"])
        dets = msg["detections"]
        tracks = self.tracker.update([[d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"]] for d in dets], [d["score"] for d in dets], t)
        self.judge.update(t, tracks)
        if not tracks:
            return sv.Detections.empty()
        a = np.asarray(tracks, float)
        return sv.Detections(xyxy=a[:, 1:5], confidence=a[:, 5], class_id=np.zeros(len(a), int), tracker_id=a[:, 0].astype(int))
