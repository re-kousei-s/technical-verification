"""人が大量にいる動画（広場）で、ライセンスが緩い（Apache-2.0）検出器を、同じ条件で比べる。
基準は、RF-DETR nano（2x2）のスコア 0.5 以上の人。CPU（onnxruntime、2 スレッド）で、再現率・基準に無い検出・1 枚の時間を測る。
  python crowd_models.py <yolox|detr> <onnx のパス> [入力の大きさ(既定 640)] [スレッド数]
    yolox … YOLOX（grid 出力、余白付きの縮小、BGR のまま 0〜255）
    detr  … RT-DETR / D-FINE（HuggingFace 版。正方形に縮小、0〜1、sigmoid、NMS 不要）"""
import json
import sys
import time

import cv2
import numpy as np
import onnxruntime as ort

kind, path = sys.argv[1], sys.argv[2]
imgsz = int(sys.argv[3]) if len(sys.argv) > 3 else 640
threads = int(sys.argv[4]) if len(sys.argv) > 4 else 2
so = ort.SessionOptions()
so.intra_op_num_threads = threads
sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
inp = sess.get_inputs()[0].name


def nms(boxes, scores, conf, iou=0.5):
    idx = cv2.dnn.NMSBoxes([[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes], scores.tolist(), conf, iou)
    return np.array(idx).reshape(-1)


def yolox(bgr, conf=0.1):
    h, w = bgr.shape[:2]
    r = imgsz / max(h, w)
    nh, nw = int(round(h * r)), int(round(w * r))
    canvas = np.full((imgsz, imgsz, 3), 114, np.uint8)
    canvas[:nh, :nw] = cv2.resize(bgr, (nw, nh))
    x = np.ascontiguousarray(canvas.transpose(2, 0, 1)[None].astype(np.float32))
    out = sess.run(None, {inp: x})[0][0]  # (N, 85)：x, y, w, h, 物体らしさ, 80 クラス
    grids, strides = [], []
    for s in (8, 16, 32):
        n = imgsz // s
        gx, gy = np.meshgrid(np.arange(n), np.arange(n))
        grids.append(np.stack([gx, gy], 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), s))
    grid, stride = np.concatenate(grids), np.concatenate(strides)
    xy = (out[:, :2] + grid) * stride
    wh = np.exp(out[:, 2:4]) * stride
    sc = out[:, 4] * out[:, 5]  # 物体らしさ × 人（class 0）
    keep = sc >= conf
    xy, wh, sc = xy[keep], wh[keep], sc[keep]
    if not len(sc):
        return np.zeros((0, 4)), np.zeros(0)
    boxes = np.concatenate([xy - wh / 2, xy + wh / 2], 1) / r
    i = nms(boxes, sc, conf)
    return boxes[i], sc[i]


def detr(bgr, conf=0.1):
    h, w = bgr.shape[:2]
    x = cv2.resize(bgr, (imgsz, imgsz))[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    logits, boxes = sess.run(None, {inp: np.ascontiguousarray(x)})
    sc = 1 / (1 + np.exp(-logits[0][:, 0]))  # 人（class 0）
    b = boxes[0]
    xyxy = np.stack([(b[:, 0] - b[:, 2] / 2) * w, (b[:, 1] - b[:, 3] / 2) * h, (b[:, 0] + b[:, 2] / 2) * w, (b[:, 1] + b[:, 3] / 2) * h], 1)
    keep = sc >= conf
    return xyxy[keep], sc[keep]


fn_detect = {"yolox": yolox, "detr": detr}[kind]
ref = []
for l in open("/o/server__rfdetr_nano__2x2__fps2.jsonl"):
    d = json.loads(l)
    ref.append([(b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]) for b in d["detections"] if b["score"] >= 0.5])


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0


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
fn_detect(frames[0])  # 暖機
t0 = time.perf_counter()
dets = []
for f in frames:
    b, s = fn_detect(f)
    dets.append([(*bb, ss) for bb, ss in zip(np.asarray(b).tolist(), np.asarray(s).tolist())])
ms = (time.perf_counter() - t0) / len(frames) * 1000
name = path.split("/")[-1]
for th in (0.25, 0.3, 0.4, 0.5):
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
    print(f"{name:16s} imgsz={imgsz} {ms:5.0f}ms/枚  score>={th}: 再現率 {tp / (tp + fn):.0%}（{tp}/{tp + fn}） 基準に無い検出 {fp}")
