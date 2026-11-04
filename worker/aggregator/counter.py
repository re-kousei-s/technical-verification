"""サーバー集計役の中核：カメラ1台ぶんの「追跡 → ライン通過判定」。

カメラごとに状態（トラッカー・線）を持つ。メッセージ（仕様書5章のJSON）を ts 順に
process() に渡すと、IN/OUT を数える。あとで FastAPI に載せるときも、このクラスをそのまま
カメラIDごとに1つ持たせればよい。
"""

import numpy as np
import supervision as sv
import trackers

from aggregator.edge_crossing import EdgeCrossing
from aggregator.heading_gate import HeadingGate
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
                 min_crossing_seconds=0.0, edge_margin=0.0, edge_confirm_seconds=1.5, method="line", heading=None):
        """lines は [{"id", "name", "line": [[x1,y1],[x2,y2]]}, ...]（座標は画面に対する割合）。"""
        anchors = ANCHORS[anchor]
        # 通過の記録に残す座標：1 点で判定するときはその点、枠全体のときは枠の中心
        self.anchor = anchors[0] if len(anchors) == 1 else sv.Position.CENTER
        self.zones = []  # (線の名前, LineZone)
        self.edges = []  # 線ごとの EdgeCrossing（zones と同じ順）
        self.heading = method == "heading"  # True なら、線をまたぐ判定ではなく、方向のスコア（HeadingGate）で数える
        self.gates = []  # 線ごとの HeadingGate
        self.debug = []  # 画面に出す用：人ごとの、足元・動きのベクトル・線ごとのスコア
        self._prev = {}  # 追跡ID → 1 つ前の足元の点
        heading = dict(heading or {})
        # 同じ追跡 ID が、同じ向きで、続けて数えられるのを止める秒数（線をまたいで）。入口に 2 本の線を引くと、1 人が両方で OUT になるため
        self.same_id_seconds = float(heading.pop("same_id_seconds", 5.0))
        self._last_dir = {}  # 追跡ID → (最後に数えた経過秒, 向き)
        for item in lines:
            (x1, y1), (x2, y2) = line_to_px(item["line"], frame_w, frame_h)
            # 線の上で立ち止まった人の足元のぶれで IN/OUT を何度も数えないよう、
            # 越えた側に一定時間とどまってから数える（低fpsでは1フレームになる）
            zone = sv.LineZone(
                start=sv.Point(x1, y1), end=sv.Point(x2, y2), triggering_anchors=anchors,
                minimum_crossing_threshold=max(1, round(min_crossing_seconds * sample_fps)),
            )
            self.zones.append((item["name"], zone))
            self.gates.append(HeadingGate((x1, y1), (x2, y2), sample_fps, (frame_w, frame_h), **(heading or {})))
            # 線のぎりぎりを通る人の補助（edge_margin = 人の枠の高さの何倍までを「際」とするか。0 なら使わない）
            self.edges.append(EdgeCrossing((x1, y1), (x2, y2), edge_margin, max(2, round(edge_confirm_seconds * sample_fps)), (frame_w, frame_h)) if edge_margin > 0 else None)
        self.tracker = build_tracker(tracker_cfg, sample_fps)
        self.t0 = None
        self.frame_size = (frame_w, frame_h)
        # 通過の記録：(経過秒, "in"/"out", 追跡ID, 判定点x, 判定点y, 線の名前)
        self.events = []

    def process(self, msg):
        """1 フレームを渡す。追跡して、各線の通過を events に足す。追跡結果を返す。"""
        t = ts_to_sec(msg["ts"])
        if self.t0 is None:
            self.t0 = t
        tracked = self.tracker.update(to_detections(msg), timestamp=t - self.t0)
        points = tracked.get_anchors_coordinates(self.anchor) if len(tracked) else None
        if self.heading:  # 方向のスコアで数える（線をまたぐ瞬間は、見ない）
            ids = tracked.tracker_id if len(tracked) else []
            pts = points if len(tracked) else []
            hs = (tracked.xyxy[:, 3] - tracked.xyxy[:, 1]) if len(tracked) else []
            for (name, _), gate in zip(self.zones, self.gates):
                for direction, tid, (x, y) in gate.update(ids, pts, hs):
                    last = self._last_dir.get(int(tid))
                    if last and last[1] == direction and (t - self.t0) - last[0] <= self.same_id_seconds:
                        continue  # 同じ人が、別の線でも、同じ向きで数えられた：数えない（IN を取りこぼしていても、時間がたてば、また数える）
                    self._last_dir[int(tid)] = (t - self.t0, direction)
                    self.events.append((t - self.t0, direction, int(tid), x, y, name))
            self._update_debug(tracked, points, t)  # 画面に出す用（スコアは、このフレームの更新のあと）
            return tracked
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
        self._update_debug(tracked, points, t)
        return tracked

    def _update_debug(self, tracked, points, t):
        """画面に出す用の情報を作る。人ごとに [追跡ID, x, y, vx, vy, 速さ, [[線の名前, 向き, スコア, 線のそばか, 数えたか], ...]]。
        x, y は画面に対する割合。vx, vy は 1 秒あたりの動き（画面に対する割合）、速さは、枠の高さ/秒（判定に使う値）。"""
        self.debug = []
        if not len(tracked):
            self._prev = {}
            return
        w, h = self.frame_size
        prev, now = self._prev, {}
        dt = (t - self._prev_t) if getattr(self, "_prev_t", None) is not None else 0.0
        for i in range(len(tracked)):
            tid = int(tracked.tracker_id[i])
            x, y = float(points[i][0]), float(points[i][1])
            box_h = float(tracked.xyxy[i][3] - tracked.xyxy[i][1])
            now[tid] = (x, y)
            vx = vy = speed = 0.0
            vec = self.gates[0].vector(tid) if (self.heading and self.gates) else None  # 判定に使っている、なめらかな動き
            if vec is not None:
                vx, vy = float(vec[0]), float(vec[1])
                speed = float(np.hypot(vx, vy)) / max(box_h, 1.0)
            elif tid in prev and dt > 0:
                vx, vy = (x - prev[tid][0]) / dt, (y - prev[tid][1]) / dt  # px/秒
                speed = float(np.hypot(vx, vy)) / max(box_h, 1.0)
            lines = []
            if self.heading:
                for (name, _), gate in zip(self.zones, self.gates):
                    inf = gate.info(tid)
                    if inf:
                        lines.append([name, inf[0], inf[1], inf[2], inf[3]])
            self.debug.append([tid, round(x / w, 4), round(y / h, 4), round(vx / w, 4), round(vy / h, 4), round(speed, 2), lines])
        self._prev, self._prev_t = now, t
