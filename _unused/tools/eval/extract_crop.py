"""全体の検出に加えて、指定した領域（奥の扉の周り）を、元の解像度から切り出して、大きく検出し、合わせる。 横 960 の座標で保存する。
  python extract_crop.py <動画> <モデル> <fps> <出力 JSON> <x0> <y0> <x1> <y1>（領域は、画面に対する割合）"""
import json, sys
import cv2, numpy as np
sys.path.insert(0, "/app")
from common.detectors import make_detector
video, model, fps, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
rx0, ry0, rx1, ry1 = [float(v) for v in sys.argv[5:9]]
det = make_detector(model, 0.1)
cap = cv2.VideoCapture(video)
src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
W0, H0 = int(cap.get(3)), int(cap.get(4))
W, H = 960, int(round(H0 * 960 / W0)) & ~1
step = max(1, round(src_fps / fps))
frames, i = [], 0
while True:
    ok, f = cap.read()
    if not ok: break
    if i % step == 0:
        small = cv2.resize(f, (W, H), interpolation=cv2.INTER_AREA)
        b, s = det.detect(small)
        boxes = [list(map(float, bb)) for bb in b]; scores = [float(x) for x in s]
        x0, y0, x1, y1 = int(rx0 * W0), int(ry0 * H0), int(rx1 * W0), int(ry1 * H0)
        crop = f[y0:y1, x0:x1]
        cb, cs = det.detect(crop)
        k = W / W0
        for bb, ss in zip(cb, cs):
            boxes.append([float((bb[0] + x0) * k), float((bb[1] + y0) * k), float((bb[2] + x0) * k), float((bb[3] + y0) * k)]); scores.append(float(ss))
        if boxes:
            idx = cv2.dnn.NMSBoxes([[b[0], b[1], b[2] - b[0], b[3] - b[1]] for b in boxes], scores, 0.1, 0.5)
            idx = np.array(idx).reshape(-1)
            frames.append([[float(v) for v in boxes[j]] + [float(scores[j])] for j in idx])
        else:
            frames.append([])
    i += 1
json.dump({"fps": src_fps / step, "w": W, "h": H, "model": model + "+crop", "frames": frames}, open(out, "w"))
print(len(frames), "frames")
