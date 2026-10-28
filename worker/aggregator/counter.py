"""サーバー集計役の中核：カメラ1台ぶんの「追跡 → ライン通過判定」。

カメラごとに状態（トラッカー・線）を持つ。メッセージ（仕様書5章のJSON）を ts 順に
process() に渡すと、IN/OUT を数える。あとで FastAPI に載せるときも、このクラスをそのまま
カメラIDごとに1つ持たせればよい。
"""

import numpy as np
import supervision as sv
import trackers

from aggregator.edge_crossing import EdgeCrossing
from aggregator.lowfps_tracker import LowFpsTracker
from common.messages import ts_to_sec
from common.tiling import line_to_px

IOU = {"iou": trackers.IoU, "giou": trackers.GIoU, "diou": trackers.DIoU, "ciou": trackers.CIoU}
TRACKERS = {
    "bytetrack": trackers.ByteTrackTracker,
    "ocsort": trackers.OCSORTTracker,
    "sort": trackers.SORTTracker,
    "lowfps": LowFpsTracker,  # 自作。距離で対応付ける低fps向け
}
# 線を越えたかを判定する、人の枠の位置。値は、判定に使う点のリスト。
#   box           … 枠の四隅すべて。枠全体（2 次元）が線の反対側へ移ったときに 1 回数える（既定）。
#                   足元・頭の高さ（Y）に左右されず、線をどこに引いても使える。枠が線をまたいでいる間は、決まるのを待つ
#   bottom_center … 足元の 1 点。床に引いた線に合う
#   top_center    … 頭の 1 点。人が重なって足元が隠れるとき
#   center        … 枠の中心の 1 点
ANCHORS = {
    "box": [sv.Position.TOP_LEFT, sv.Position.TOP_RIGHT, sv.Position.BOTTOM_LEFT, sv.Position.BOTTOM_RIGHT],
    "bottom_center": [sv.Position.BOTTOM_CENTER],
    "top_center": [sv.Position.TOP_CENTER],
    "center": [sv.Position.CENTER],
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


def to_detections(msg):
    dets = msg["detections"]
    if not dets:
        return sv.Detections.empty()
    xyxy = np.array([[d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"]] for d in dets], np.float32)
    conf = np.array([d["score"] for d in dets], np.float32)
    return sv.Detections(xyxy=xyxy, confidence=conf, class_id=np.zeros(len(dets), int))


class CameraCounter:
    """端末 1 台ぶんの「追跡 → 線の通過判定」。

    追跡は 1 つで、線は何本でも持てる。線ごとに LineZone があり、人がどの線を越えたかを別々に数える。
    （入口が複数なら、入口ごとに線を引く。同じ人が 2 本の線を越えれば、それぞれで数える）
    """

    def __init__(self, lines, frame_w, frame_h, tracker_cfg, sample_fps, anchor="bottom_center",
                 min_crossing_seconds=0.0, edge_margin=0.0, edge_confirm_seconds=1.5):
        """lines は [{"id", "name", "line": [[x1,y1],[x2,y2]]}, ...]（座標は画面に対する割合）。"""
        anchors = ANCHORS[anchor]
        # 通過の記録に残す座標：1 点で判定するときはその点、枠全体のときは枠の中心
        self.anchor = anchors[0] if len(anchors) == 1 else sv.Position.CENTER
        self.zones = []  # (線の名前, LineZone)
        self.edges = []  # 線ごとの EdgeCrossing（zones と同じ順）
        for item in lines:
            (x1, y1), (x2, y2) = line_to_px(item["line"], frame_w, frame_h)
            # 線の上で立ち止まった人の足元のぶれで IN/OUT を何度も数えないよう、
            # 越えた側に一定時間とどまってから数える（低fpsでは1フレームになる）
            zone = sv.LineZone(
                start=sv.Point(x1, y1), end=sv.Point(x2, y2), triggering_anchors=anchors,
                minimum_crossing_threshold=max(1, round(min_crossing_seconds * sample_fps)),
            )
            self.zones.append((item["name"], zone))
            # 線のぎりぎりを通る人の補助（edge_margin = 人の枠の高さの何倍までを「際」とするか。0 なら使わない）
            self.edges.append(EdgeCrossing((x1, y1), (x2, y2), edge_margin, max(2, round(edge_confirm_seconds * sample_fps))) if edge_margin > 0 else None)
        self.tracker = build_tracker(tracker_cfg, sample_fps)
        self.t0 = None
        # 通過の記録：(経過秒, "in"/"out", 追跡ID, 判定点x, 判定点y, 線の名前)
        self.events = []

    def process(self, msg):
        """1 フレームを渡す。追跡して、各線の通過を events に足す。追跡結果を返す。"""
        t = ts_to_sec(msg["ts"])
        if self.t0 is None:
            self.t0 = t
        tracked = self.tracker.update(to_detections(msg), timestamp=t - self.t0)
        points = tracked.get_anchors_coordinates(self.anchor) if len(tracked) else None
        ids = tracked.tracker_id if len(tracked) else []
        heights = (tracked.xyxy[:, 3] - tracked.xyxy[:, 1]) if len(tracked) else []
        for (name, zone), edge in zip(self.zones, self.edges):
            crossed_in, crossed_out = zone.trigger(tracked)
            counted = set()
            for direction, crossed in (("in", crossed_in), ("out", crossed_out)):
                for i in np.flatnonzero(crossed):
                    x, y = points[i]
                    counted.add(int(tracked.tracker_id[i]))
                    self.events.append((t - self.t0, direction, int(tracked.tracker_id[i]), x, y, name))
            if edge is not None:  # LineZone が数えなかった「線のぎりぎり」の通過
                for direction, tid, (x, y) in edge.update(ids, points if len(tracked) else [], heights, counted):
                    self.events.append((t - self.t0, direction, int(tid), x, y, name))
        return tracked
