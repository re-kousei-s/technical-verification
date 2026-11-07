"""JPEG の連番（ffmpeg が出したもの）から、検出を取り出して、JSON に保存する。実際の流れ（H.264 → JPEG → 検出）を、オフラインで再現する。
  python extract_jpgs.py <JPEG のフォルダ> <出力 JSON> [fps]"""
import glob
import json
import sys

import cv2

sys.path.insert(0, "/app")
from common.detectors import make_detector  # noqa: E402

folder, out = sys.argv[1], sys.argv[2]
fps = float(sys.argv[3]) if len(sys.argv) > 3 else 3.0
det = make_detector("yolox_tiny_416", 0.1)
frames, w, h = [], 0, 0
for p in sorted(glob.glob(folder + "/*.jpg")):
    f = cv2.imread(p)
    h, w = f.shape[:2]
    boxes, scores = det.detect(f)
    frames.append([[float(v) for v in b] + [float(s)] for b, s in zip(boxes, scores)])
json.dump({"fps": fps, "w": w, "h": h, "model": "yolox_tiny_416", "frames": frames}, open(out, "w"))
print(folder, len(frames), "frames")
