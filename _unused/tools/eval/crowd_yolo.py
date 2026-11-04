"""人が大量にいる動画（広場）で、YOLOv8（ONNX、CPU）が、基準（RF-DETR nano 2x2、スコア 0.5 以上）の人を、どれだけ見つけられるか。速さも測る。
  python crowd_yolo.py <onnx のパス> <入力の大きさ> [スレッド数]"""
import json
import sys
import time

import cv2

sys.path.insert(0, "/t")
from yolo_onnx import YoloOnnx  # noqa: E402

path, imgsz = sys.argv[1], int(sys.argv[2])
threads = int(sys.argv[3]) if len(sys.argv) > 3 else 2
ref = []
for l in open("/o/server__rfdetr_nano__2x2__fps2.jsonl"):
    d = json.loads(l)
    ref.append([(b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]) for b in d["detections"] if b["score"] >= 0.5])


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0


det = YoloOnnx(path, imgsz, threads=threads)
cap = cv2.VideoCapture("/v/people-walking.mp4")
step = max(1, round((cap.get(cv2.CAP_PROP_FPS) or 30) / 2))
frames, i = [], 0
while True:
    ok, f = cap.read()
    if not ok:
        break
    if i % step == 0:
        frames.append(f)
    i += 1
frames = frames[: len(ref)]
det.detect(frames[0])  # 暖機
t0 = time.perf_counter()
dets = []
for f in frames:
    b, s = det.detect(f)
    dets.append([(*bb, ss) for bb, ss in zip(b.tolist(), s.tolist())])
ms = (time.perf_counter() - t0) / len(frames) * 1000
for th in (0.25, 0.3, 0.4):
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
    print(f"{path.split('/')[-1]:18s} imgsz={imgsz} threads={threads} {ms:5.0f}ms/枚  score>={th}: 再現率 {tp / (tp + fn):.0%}（{tp}/{tp + fn}） 基準に無い検出 {fp}")
