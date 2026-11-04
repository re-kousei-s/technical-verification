"""人が大量にいる動画（広場）で、分割（タイル）の細かさを変えたとき、基準（RF-DETR nano 2x2、スコア 0.5 以上）の人を、どれだけ見つけられるか。
  python crowd_tiling.py <モデル名> <分割の例: none 2x2 3x4 4x4 ...>"""
import json
import sys
import time

import cv2

sys.path.insert(0, "/app")
from common.detectors import make_detector  # noqa: E402
from common.tiling import detect_tiled, make_tiles  # noqa: E402

model, modes = sys.argv[1], sys.argv[2:]
ref = []
for l in open("/o/server__rfdetr_nano__2x2__fps2.jsonl"):
    d = json.loads(l)
    ref.append([(b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]) for b in d["detections"] if b["score"] >= 0.5])


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0


det = make_detector(model, 0.1)
cap = cv2.VideoCapture("/v/people-walking.mp4")
fps = cap.get(cv2.CAP_PROP_FPS) or 30
step = max(1, round(fps / 2))
frames, i = [], 0
while True:
    ok, f = cap.read()
    if not ok:
        break
    if i % step == 0:
        frames.append(f)
    i += 1
frames = frames[: len(ref)]
for mode in modes:
    tiles = make_tiles(frames[0].shape[1], frames[0].shape[0], mode)
    t0 = time.perf_counter()
    dets = []
    for f in frames:
        b, s = detect_tiled(det.detect, f, tiles)
        dets.append([(*bb, ss) for bb, ss in zip(b.tolist(), s.tolist())])
    ms = (time.perf_counter() - t0) / len(frames) * 1000
    for th in (0.25, 0.3):
        tp = fn = fp = 0
        for r, d in zip(ref, dets):
            db = [b for b in d if b[4] >= th]
            used = set()
            for rb in r:
                best = max(((iou(rb, x), k) for k, x in enumerate(db) if k not in used), default=(0, -1))
                if best[0] >= 0.4:
                    tp += 1
                    used.add(best[1])
                else:
                    fn += 1
            fp += len(db) - len(used)
        print(f"{model} tiling={mode:5s} タイル{len(tiles):2d} {ms:6.0f}ms/枚  score>={th}: 再現率 {tp / (tp + fn):.0%}（{tp}/{tp + fn}） 基準に無い検出 {fp}")
