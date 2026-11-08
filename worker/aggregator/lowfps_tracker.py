"""低fps（1〜2fps）向けの簡単なトラッカー。

ByteTrack などは前後フレームの枠の重なり（IoU）で対応付けるが、1秒あくと人は自分の幅以上に
動くので枠が重ならず、別人扱いになって線の通過を数えられない。ここでは
  「予測位置（等速）と検出の中心の距離 ÷ 枠の高さ」
を対応付けのコストにし、人が1秒に動ける範囲（枠の高さの何倍か）でゲートする。

- 高スコアの検出で対応付けと新規追跡を行い、低スコアの検出は既存の追跡の延長にだけ使う（ByteTrack と同じ考え方）
- 見失っても lost_track_seconds の間は予測位置で待つ
- 見た目（app_weight > 0）：検出に、服の色のヒストグラム（detections.data["feat"]）があれば、色の違い（バタチャリヤ距離 0〜1）を、対応付けの費用に足す。
  色が app_max より違う人どうしは、つながない（人が重なったときの、ID の取り違えを減らす）
- trackers パッケージのトラッカーと同じく update(detections, timestamp) -> Detections（tracker_id 付き）
"""

import numpy as np
import supervision as sv
from scipy.optimize import linear_sum_assignment


class _Track:
    def __init__(self, tid, box, t):
        self.id = tid
        self.box = box
        self.t = t
        self.v = np.zeros(2)  # 中心の速度（px/秒）
        self.hits = 1
        self.feat = None  # 服の色のヒストグラム（なめらかに更新）

    @property
    def center(self):
        return np.array([(self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2])

    @property
    def height(self):
        return max(self.box[3] - self.box[1], 1.0)

    def predict(self, t):
        return self.center + self.v * (t - self.t)

    def update(self, box, t, feat=None, ema=0.5):
        if feat is not None:
            self.feat = feat if self.feat is None else (1 - ema) * self.feat + ema * feat
        new_c = np.array([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2])
        dt = t - self.t
        if dt > 0:
            v = (new_c - self.center) / dt
            # 1回目は速度をそのまま、以降は急な変化を抑えて平均する
            self.v = v if self.hits == 1 else 0.5 * self.v + 0.5 * v
        self.box, self.t = box, t
        self.hits += 1


class LowFpsTracker:
    def __init__(self, frame_rate=1.0, lost_track_seconds=2.0, high_conf_det_threshold=0.4,
                 low_conf_det_threshold=0.2, max_speed_heights_per_second=1.5, base_gate_heights=0.5,
                 max_height_ratio=1.6, use_velocity=True, app_weight=0.0, app_max=1.0):
        self.lost = lost_track_seconds
        self.high = high_conf_det_threshold
        self.low = low_conf_det_threshold
        self.speed = max_speed_heights_per_second
        self.base = base_gate_heights
        self.ratio = max_height_ratio
        self.use_velocity = use_velocity
        self.app_weight, self.app_max = app_weight, app_max  # 見た目（服の色）の重みと、つなぐのを許す、色の違いの上限
        self.tracks = []
        self.next_id = 0

    def _match(self, tracks, boxes, t, feats=None, fmask=None):
        if not tracks or len(boxes) == 0:
            return [], list(range(len(tracks))), list(range(len(boxes)))
        cost = np.full((len(tracks), len(boxes)), np.inf)
        centers = (boxes[:, :2] + boxes[:, 2:]) / 2
        heights = np.maximum(boxes[:, 3] - boxes[:, 1], 1.0)
        for i, tr in enumerate(tracks):
            dt = max(t - tr.t, 1e-3)
            p = tr.predict(t) if self.use_velocity else tr.center
            d = np.linalg.norm(centers - p, axis=1) / tr.height
            ratio = np.maximum(heights / tr.height, tr.height / heights)
            # 速度で予測していても外れるので、動ける範囲 + 基本の許容 でゲートする
            gate = self.base + self.speed * dt * (0.5 if self.use_velocity and tr.hits > 1 else 1.0)
            ok = (d <= gate) & (ratio <= self.ratio)
            cost[i, ok] = d[ok] / gate
            if self.app_weight > 0 and feats is not None and tr.feat is not None:
                bc = np.sqrt(np.clip(feats, 0, None) * np.clip(tr.feat, 0, None)).sum(axis=1)  # バタチャリヤ係数（1＝同じ色）
                dapp = np.sqrt(np.clip(1 - bc, 0, 1))
                cost[i, ok] += self.app_weight * np.where(fmask, dapp, 0.5)[ok]
                cost[i, ok & fmask & (dapp > self.app_max)] = np.inf  # 色が違いすぎる：つながない
        big = 1e6
        rows, cols = linear_sum_assignment(np.where(np.isfinite(cost), cost, big))
        matches = [(r, c) for r, c in zip(rows, cols) if cost[r, c] < big]
        mr = {r for r, _ in matches}
        mc = {c for _, c in matches}
        return matches, [i for i in range(len(tracks)) if i not in mr], [j for j in range(len(boxes)) if j not in mc]

    def update(self, detections: sv.Detections, frame=None, timestamp=None) -> sv.Detections:
        t = float(timestamp)
        self.tracks = [tr for tr in self.tracks if t - tr.t <= self.lost]
        conf = detections.confidence if detections.confidence is not None else np.ones(len(detections))
        hi = np.flatnonzero(conf >= self.high)
        lo = np.flatnonzero((conf >= self.low) & (conf < self.high))
        out_idx, out_ids = [], []
        data = getattr(detections, "data", None) or {}
        feats = data.get("feat") if self.app_weight > 0 else None
        fmask = data.get("has_feat") if feats is not None else None
        ft = (lambda idx: feats[idx]) if feats is not None else (lambda idx: None)
        fm = (lambda idx: fmask[idx]) if feats is not None else (lambda idx: None)
        fone = lambda j: feats[j] if feats is not None and fmask[j] else None

        # 1段目：高スコアの検出と、全追跡
        m1, rest_tracks, rest_hi = self._match(self.tracks, detections.xyxy[hi], t, ft(hi), fm(hi))
        for r, c in m1:
            self.tracks[r].update(detections.xyxy[hi[c]], t, fone(hi[c]))
            out_idx.append(hi[c])
            out_ids.append(self.tracks[r].id)
        # 2段目：残った追跡と、低スコアの検出
        remaining = [self.tracks[i] for i in rest_tracks]
        m2, _, _ = self._match(remaining, detections.xyxy[lo], t, ft(lo), fm(lo))
        for r, c in m2:
            remaining[r].update(detections.xyxy[lo[c]], t, fone(lo[c]))
            out_idx.append(lo[c])
            out_ids.append(remaining[r].id)
        # 対応しなかった高スコアの検出は新しい人
        for c in rest_hi:
            tr = _Track(self.next_id, detections.xyxy[hi[c]], t)
            tr.feat = fone(hi[c])
            self.next_id += 1
            self.tracks.append(tr)
            out_idx.append(hi[c])
            out_ids.append(tr.id)

        if not out_idx:
            return sv.Detections.empty()
        result = detections[np.array(out_idx)]
        result.tracker_id = np.array(out_ids, dtype=int)
        return result
