"""追跡・人の状態管理・判定を、1 つにつなげたもの。評価（_unused/tools/eval）と、検出の JSON からの数え直しに使う。

本番の worker は、追跡（検出の worker の中）と判定（judge の service）に分かれている。
ここは、検出の結果（メッセージ）を順に渡すと、追跡して判定する、という一続きの形。
"""

from aggregator.judge import Judge
from aggregator.lifecycle import Lifecycle
from aggregator.tracking import Tracker, tracks_of
from common.messages import ts_to_sec


class CameraCounter:
    def __init__(self, lines, frame_w, frame_h, tracker_cfg, sample_fps, anchor="bottom_center",
                 min_crossing_seconds=0.0, edge_margin=0.0, edge_confirm_seconds=1.5, method="episode", heading=None):
        """lines は [{"id", "name", "line": [[x1,y1],[x2,y2]]}, ...]（座標は画面に対する割合）。
        min_crossing_seconds・edge_margin・edge_confirm_seconds は、旧方式（method=line）の引数。いまは使わない。"""
        self.tracker = Tracker(tracker_cfg, sample_fps)
        self.lifecycle = Lifecycle(sample_fps, (frame_w, frame_h), **(heading or {}))
        self.judge = Judge(lines, frame_w, frame_h, sample_fps, method, heading, anchor)
        self.zones = [(n, None) for n in self.judge.names]  # 線の名前（評価の道具が、線の順番を引くため）
        self.gates = self.judge.gates
        self.events = self.judge.events
        self.debug = []
        self.frame_size = (frame_w, frame_h)

    def process(self, msg):
        """1 フレーム（検出のメッセージ）を渡す。追跡して、判定する。追跡結果（sv.Detections）を返す。"""
        t = ts_to_sec(msg["ts"])
        dets = msg["detections"]
        boxes = [[d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"]] for d in dets]
        tracked = self.tracker.update(boxes, [d["score"] for d in dets], t)
        tracks = tracks_of(tracked)
        events, alias = self.lifecycle.update(tracks)
        self.judge.update(t, tracks, events, alias)
        self.debug = self.judge.debug
        return tracked
