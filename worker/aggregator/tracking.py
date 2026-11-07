"""追跡：検出の枠に、人ごとの ID を付け続ける。画像は見ない（枠とスコアだけ）。

検出 ─▶ 【追跡】 ─▶ 判定（judge.py）
"""

import numpy as np
import supervision as sv
import trackers

from aggregator.lowfps_tracker import LowFpsTracker

IOU = {"iou": trackers.IoU, "giou": trackers.GIoU, "diou": trackers.DIoU, "ciou": trackers.CIoU}
TRACKERS = {
    "bytetrack": trackers.ByteTrackTracker,
    "ocsort": trackers.OCSORTTracker,
    "sort": trackers.SORTTracker,
    "lowfps": LowFpsTracker,  # 自作。距離で対応付ける低fps向け
}


def build_tracker(tracker_cfg, sample_fps):
    params = dict(tracker_cfg.get("params", {}))
    if tracker_cfg["type"] == "lowfps":
        return LowFpsTracker(frame_rate=sample_fps, **params)
    # lost_track_buffer は trackers の仕様で「30fps換算のフレーム数」。秒で書けるようにする
    if "lost_track_seconds" in params:
        params["lost_track_buffer"] = max(1, round(params.pop("lost_track_seconds") * 30))
    if "iou" in params:
        params["iou"] = IOU[params["iou"]]()
    return TRACKERS[tracker_cfg["type"]](frame_rate=sample_fps, **params)


class Tracker:
    """端末 1 台ぶんの追跡。フレームの検出（枠・スコア）を順に渡すと、人ごとの ID が付いた枠を返す。"""

    def __init__(self, tracker_cfg, sample_fps):
        self.tracker = build_tracker(tracker_cfg, sample_fps)
        self.t0 = None

    def update(self, boxes, scores, t_sec):
        """boxes は [x1, y1, x2, y2] の並び、t_sec はそのフレームの時刻（秒）。追跡した結果（sv.Detections）を返す。"""
        if self.t0 is None:
            self.t0 = t_sec
        if len(boxes):
            det = sv.Detections(xyxy=np.asarray(boxes, np.float32), confidence=np.asarray(scores, np.float32),
                                class_id=np.zeros(len(boxes), int))
        else:
            det = sv.Detections.empty()
        return self.tracker.update(det, timestamp=t_sec - self.t0)


def tracks_of(tracked):
    """追跡の結果を、判定に渡す形にする： [[追跡ID, x1, y1, x2, y2, スコア], ...]"""
    if not len(tracked):
        return []
    return [[int(t), float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(c)]
            for b, t, c in zip(tracked.xyxy, tracked.tracker_id, tracked.confidence)]
