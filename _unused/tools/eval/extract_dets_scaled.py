"""動画から、5fps で人の検出を取り出して、JSON に保存する（検出は、重いので、1 回だけ。数える条件の比較は、このあと、何度でも回せる）。

  python extract_dets.py <動画> <モデル名> <fps> <出力 JSON>
worker のコンテナの中で動かす（common/detectors を使う）。
"""
import json
import sys

import cv2

sys.path.insert(0, "/app")
from common.detectors import make_detector  # noqa: E402

video, model, fps, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
TARGET_W = int(sys.argv[5]) if len(sys.argv) > 5 else 0  # 実際の流れと同じ大きさ（横 960）に縮めてから検出する
det = make_detector(model, 0.1)  # 低めの最低スコアで取り出す（しきい値は、あとで変える）
cap = cv2.VideoCapture(video)
src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
w, h = int(cap.get(3)), int(cap.get(4))
if TARGET_W and w > TARGET_W:
    h, w = int(round(h * TARGET_W / w)) & ~1, TARGET_W
step = max(1, round(src_fps / fps))
frames, i = [], 0
while True:
    ok, f = cap.read()
    if not ok:
        break
    if i % step == 0:
        if TARGET_W and f.shape[1] > TARGET_W:
            f = cv2.resize(f, (w, h), interpolation=cv2.INTER_AREA)
        boxes, scores = det.detect(f)
        frames.append([[float(v) for v in b] + [float(s)] for b, s in zip(boxes, scores)])
    i += 1
json.dump({"fps": src_fps / step, "w": w, "h": h, "model": model, "frames": frames}, open(out, "w"))
print(video.split("/")[-1], model, len(frames), "frames")
