"""ドア・エレベーター・出入口の「四角」候補を、画像から探す（書類スキャンの四角検出と同じ系統の、輪郭ベースの方法）。

斜めから見たドアの枠は、台形に写る（左右の辺はほぼ縦、上下の辺は傾く）。そこで
  エッジ → 輪郭 → 4 点の凸多角形に近似 → ドアらしい形（縦長・左右がほぼ縦・大きさが適当）だけ残す → 重複を除く
の順で絞る。壁の羽目板や天井の枠なども拾いうるので、結果は「候補」であり、人が確認して直す前提（スマホの画面で採用・修正する）。

座標はすべて画像に対する割合（0〜1）。四角は [左上, 右上, 右下, 左下] の順。
"""

import cv2
import numpy as np


def order_quad(pts):
    """4点を [左上, 右上, 右下, 左下] に並べる。"""
    pts = np.array(pts, dtype=np.float32).reshape(4, 2)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(ang)]                 # 画面上の時計回り（左上から）
    start = int(np.argmin(pts.sum(axis=1)))    # x+y が最小 = 左上
    return np.roll(pts, -start, axis=0)


def _vertical_tilt_deg(p, q):
    """辺 p→q が縦からどれだけ傾いているか（度）。"""
    dx, dy = q[0] - p[0], q[1] - p[1]
    return abs(np.degrees(np.arctan2(abs(dx), abs(dy) + 1e-9)))


def _iou_boxes(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw, ih = max(0, min(ax2, bx2) - max(ax1, bx1)), max(0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0, inter / min((ax2 - ax1) * (ay2 - ay1), (bx2 - bx1) * (by2 - by1) + 1e-9)


def _merge_side_by_side(cands, max_gap=0.35, min_height_ratio=0.8):
    """隣り合う2枚の扉（エレベーターの左右の扉など）を、1つの出入口にまとめる。

    A の右辺と B の左辺がほぼ重なる（すき間が扉の幅の max_gap 倍以内）で、高さが近いものを、
    左上=A の左上、右上=B の右上、右下=B の右下、左下=A の左下 の四角にする。
    """
    cands = sorted(cands, key=lambda c: c["quad"][0][0])
    merged, used = [], set()
    for i, a in enumerate(cands):
        if i in used:
            continue
        cur = a
        for j in range(i + 1, len(cands)):
            if j in used:
                continue
            b = cands[j]
            (atl, atr, abr, abl), (btl, btr, bbr, bbl) = cur["quad"], b["quad"]
            width = (np.linalg.norm(atr - atl) + np.linalg.norm(abr - abl)) / 2
            gap = (np.linalg.norm(btl - atr) + np.linalg.norm(bbl - abr)) / 2
            ha, hb = (np.linalg.norm(abl - atl) + np.linalg.norm(abr - atr)) / 2, (np.linalg.norm(bbl - btl) + np.linalg.norm(bbr - btr)) / 2
            if gap <= max_gap * width and min(ha, hb) / max(ha, hb) >= min_height_ratio and btl[0] >= atl[0]:
                quad = np.array([atl, btr, bbr, abl], dtype=np.float32)
                cur = {**cur, "quad": quad, "area": cur["area"] + b["area"], "score": max(cur["score"], b["score"]) * 1.1,
                       "edge_cover": (cur["edge_cover"] + b["edge_cover"]) / 2}
                used.add(j)
        merged.append(cur)
    merged.sort(key=lambda c: -c["score"])
    return merged


def detect_quads(img_bgr, max_candidates=8, work_width=1000):
    """ドアらしい四角の候補を、良さそうな順に返す。[{"quad": [[x,y]*4], "score": float, "area": float}, ...]"""
    h0, w0 = img_bgr.shape[:2]
    scale = work_width / w0
    img = cv2.resize(img_bgr, (work_width, int(h0 * scale)), interpolation=cv2.INTER_AREA)
    H, W = img.shape[:2]
    img_area = float(W * H)

    # 色の差（壁とドア枠）と明るさの差の両方でエッジを取る。LAB の明るさ以外（a,b）が壁の色とドア枠の差を拾う
    lab = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0), cv2.COLOR_BGR2LAB)
    edges = np.zeros((H, W), np.uint8)
    for ch in range(3):
        v = lab[:, :, ch]
        med = float(np.median(v))
        lo, hi = int(max(0, 0.66 * med * 0.5)), int(min(255, 1.33 * med * 0.5 + 30))
        edges |= cv2.Canny(v, max(10, lo // 2), max(40, hi // 2))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cands = []
    for cnt in contours:
        peri = cv2.arcLength(cnt, True)
        if peri < 0.2 * (W + H) * 0.25:
            continue
        for eps in (0.015, 0.025, 0.04):
            approx = cv2.approxPolyDP(cnt, eps * peri, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                break
        else:
            continue
        quad = order_quad(approx)
        area = cv2.contourArea(quad)
        if not (0.006 * img_area <= area <= 0.4 * img_area):
            continue
        tl, tr, br, bl = quad
        left_len, right_len = np.linalg.norm(bl - tl), np.linalg.norm(br - tr)
        top_len, bot_len = np.linalg.norm(tr - tl), np.linalg.norm(br - bl)
        height, width = (left_len + right_len) / 2, (top_len + bot_len) / 2
        if height / max(width, 1) < 0.9 or height / max(width, 1) > 6:     # ドアは縦長
            continue
        if _vertical_tilt_deg(tl, bl) > 28 or _vertical_tilt_deg(tr, br) > 28:   # 左右の辺はほぼ縦
            continue
        if min(left_len, right_len) / max(left_len, right_len) < 0.45:          # 左右の長さが違いすぎない（遠近の範囲）
            continue
        x, y, bw, bh = cv2.boundingRect(approx)
        if bw > 0.95 * W or bh > 0.95 * H:
            continue
        # 輪郭の四角らしさ：近似前の輪郭が、四角からどれだけ離れているか
        rect_fit = cv2.contourArea(cnt) / max(area, 1.0)
        rect_fit = min(rect_fit, 1 / max(rect_fit, 1e-6))
        # 四角の枠に沿って、エッジが連続しているか（4辺それぞれの上のエッジ画素の割合）
        mask = np.zeros((H, W), np.uint8)
        cv2.polylines(mask, [quad.astype(np.int32)], True, 255, 5)
        edge_cover = float((edges[mask > 0] > 0).mean())
        score = edge_cover * (0.5 + 0.5 * rect_fit) * (area / img_area) ** 0.35
        cands.append({"quad": quad, "score": score, "area": area / img_area, "bbox": (x, y, x + bw, y + bh),
                      "edge_cover": edge_cover})

    cands.sort(key=lambda c: -c["score"])
    kept = []
    for c in cands:
        dup = False
        for k in kept:
            iou, contain = _iou_boxes(c["bbox"], k["bbox"])
            if iou > 0.5 or contain > 0.85:      # ほぼ同じ場所、または大きい候補の中にすっぽり入る小さい候補
                dup = True
                break
        if not dup:
            kept.append(c)
        if len(kept) >= max_candidates:
            break
    kept = _merge_side_by_side(kept)
    return [
        {"quad": [[round(float(x) / W, 4), round(float(y) / H, 4)] for x, y in c["quad"]],
         "score": round(c["score"], 3), "area": round(c["area"], 3), "edge_cover": round(c["edge_cover"], 2)}
        for c in kept
    ]
