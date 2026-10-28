"""タイル分割と、分割結果の統合（NMS）。

分割方式:
  none  : 分割なし
  RxC   : 画面を R 行 C 列に分ける（例: 2x2）。隣と overlap の割合だけ重ねる
  line  : 線の周りだけを切り出して推論する（line_margin は画面の縦横に対する割合）。
          切り出しが細長いときは、線に沿って正方形に近いタイルに分ける
"""

import numpy as np


def line_to_px(line_norm, w, h):
    (x1, y1), (x2, y2) = line_norm
    return (x1 * w, y1 * h), (x2 * w, y2 * h)


def make_tiles(w, h, mode, line_norm=None, overlap=0.15, line_margin=0.2):
    if mode in (None, "none"):
        return [(0, 0, w, h)]
    if mode == "line":
        if line_norm is None:
            raise ValueError("tiling=line には動画の line 設定が必要です")
        (x1, y1), (x2, y2) = line_to_px(line_norm, w, h)
        mx, my = line_margin * w, line_margin * h
        x0, x1_ = max(0, min(x1, x2) - mx), min(w, max(x1, x2) + mx)
        y0, y1_ = max(0, min(y1, y2) - my), min(h, max(y1, y2) + my)
        # 細長いまま正方形の入力に縮めると人が潰れるので、長い方向に正方形に近いタイルへ分ける
        rw, rh = x1_ - x0, y1_ - y0
        n = max(1, round(max(rw, rh) / max(min(rw, rh), 1)))
        if n == 1:
            return [(int(x0), int(y0), int(np.ceil(x1_)), int(np.ceil(y1_)))]
        tiles = []
        step = (max(rw, rh)) / n
        pad = step * overlap / 2
        for i in range(n):
            a0, a1 = max(0, i * step - pad), min(max(rw, rh), (i + 1) * step + pad)
            if rw >= rh:
                tiles.append((int(x0 + a0), int(y0), int(np.ceil(x0 + a1)), int(np.ceil(y1_))))
            else:
                tiles.append((int(x0), int(y0 + a0), int(np.ceil(x1_)), int(np.ceil(y0 + a1))))
        return tiles
    rows, cols = (int(v) for v in mode.lower().split("x"))
    tw, th = w / cols, h / rows
    ox, oy = tw * overlap / 2, th * overlap / 2
    tiles = []
    for r in range(rows):
        for c in range(cols):
            x0 = max(0, int(c * tw - ox))
            y0 = max(0, int(r * th - oy))
            x1 = min(w, int(np.ceil((c + 1) * tw + ox)))
            y1 = min(h, int(np.ceil((r + 1) * th + oy)))
            tiles.append((x0, y0, x1, y1))
    return tiles


def nms(boxes, scores, iou_threshold=0.5):
    if len(boxes) == 0:
        return np.zeros(0, dtype=int)
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= iou_threshold]
    return np.array(keep, dtype=int)


def detect_tiled(detect_fn, frame, tiles):
    """各タイルで detect_fn(画像) -> (xyxy, scores) を呼び、元画像の座標に戻して統合する。"""
    all_boxes, all_scores = [], []
    for x0, y0, x1, y1 in tiles:
        boxes, scores = detect_fn(frame[y0:y1, x0:x1])
        if len(boxes):
            all_boxes.append(boxes + np.array([x0, y0, x0, y0], dtype=np.float32))
            all_scores.append(scores)
    if not all_boxes:
        return np.zeros((0, 4), np.float32), np.zeros(0, np.float32)
    boxes = np.concatenate(all_boxes)
    scores = np.concatenate(all_scores)
    if len(tiles) > 1:
        keep = nms(boxes, scores)
        boxes, scores = boxes[keep], scores[keep]
    return boxes, scores
