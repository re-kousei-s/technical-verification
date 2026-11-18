"""検出の JSON から、数える条件を変えて、通過を数え直す共通の部品（worker のコンテナの中で使う）。"""
import json
import sys

import yaml

sys.path.insert(0, "/app")
from aggregator.counter import CameraCounter  # noqa: E402

MATRIX = yaml.safe_load(open("/config/matrix.yaml"))
TRACKER = MATRIX["aggregator"]["tracker"]  # ② 追跡の設定
TILES = MATRIX["aggregator"]["tiles"]  # ③ 判定（タイル）の設定


def load(path, min_score=0.0):
    d = json.load(open(path))
    frames = [[b for b in fr if b[4] >= min_score] for fr in d["frames"]]
    return d, frames


def messages(d, frames):
    out = []
    for k, dets in enumerate(frames):
        sec = k / d["fps"]
        out.append({"ts": "2026-11-04T10:%02d:%09.6f+09:00" % (int(sec // 60), sec % 60),
                    "detections": [{"x": b[0], "y": b[1], "w": b[2] - b[0], "h": b[3] - b[1], "score": b[4], "feat": b[5] if len(b) > 5 else None} for b in dets]})
    return out


def run(d, frames, lines, tracker_over=None, heading=None, pad=0, **_ignored):
    """いまの ② 追跡 ＋ ③ 判定（タイル）で数える。tracker_over・heading は、追跡・タイルの設定の上書き。
    lines: [{"id","name","line":[[x,y],[x,y]]}]。戻り値: (events, tracks)。events = [(秒, 向き, 追跡ID, 線の名前)]"""
    c = CameraCounter(lines, d["w"], d["h"], {**TRACKER, **(tracker_over or {})}, {**TILES, **(heading or {})})
    tracks = {}
    for k, m in enumerate(messages(d, list(frames) + [[] for _ in range(pad)])):  # pad：映像が終わったあとも、検出なしのフレームが続く、と見なす
        tr = c.process(m)
        for i in range(len(tr)):
            tid = int(tr.tracker_id[i])
            x1, y1, x2, y2 = tr.xyxy[i]
            p = ((x1 + x2) / 2 / d["w"], y2 / d["h"])
            t = tracks.setdefault(tid, {"first": (k / d["fps"], p), "n": 0})
            t["last"] = (k / d["fps"], p)
            t["n"] += 1
    return [(round(e[0], 1), e[1], e[2], e[5]) for e in c.events], tracks
