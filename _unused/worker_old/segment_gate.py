"""軌跡の線分と、数える線の線分が、交わったかで、IN/OUT を決める判定。動きのベクトルで、向きと、確かさを見る。

【考え方】
  人ごとに、足元の点の履歴を持つ。新しい点が来るたびに、「1 つ前の点 → いまの点」の線分が、数える線（線分）と交わるかを調べる。
  交わったら、越えた。向きは、線のどちら側へ移ったかで決める（IN の向きは、他の判定と同じ）。
  線の端の外側（延長線）は、交わらないので、自然に除かれる（端の少し外まで、tol 倍の枠の高さだけ許す）。
【ベクトル】
  直近 vec_frames フレームの動きが、越えた向きに、線を横切っていること：
  線に垂直な動きが、min_move（枠の高さ比）以上、かつ、線に沿った動きの across_ratio 倍以上（線に沿って歩いただけ・足元のぶれを除く）。
【見えなくなる人・見え始める人】
  線のすぐそばで見えなくなった人（扉の中へ入る人）は、最後の動きのベクトルを、extend_seconds 先まで伸ばした線分が、数える線と交われば、越えたとみなす。
  線のすぐそばで見え始めた人（扉から出てきた人）は、最初の動きを、逆向きに、extend_seconds 前まで伸ばして、同じように見る。
  画面の端（見え始め）・画面の下の端（見えなくなる）は、扉ではない（画面の外から来た・画面の外へ歩き去った）ので、使わない。
【重複】同じ向きの通過が、近い場所・短い時間に出たら、1 回にまとめる（追跡の付け替わり対策）。
"""

from collections import deque

import numpy as np


class _Track:
    __slots__ = ("pts", "absent", "born_checked", "counted_tick", "vanish_done", "first_pt", "inz", "last_h", "last_dir")

    def __init__(self, maxlen):
        self.pts = deque(maxlen=maxlen)  # 足元の点
        self.absent = 0
        self.born_checked = False
        self.counted_tick = -10**9  # この線で、最後に数えたフレーム
        self.vanish_done = False
        self.first_pt = None
        self.inz = False
        self.last_h = None
        self.last_dir = 0  # 最後に数えた向き（+1＝IN、−1＝OUT）


class SegmentGate:
    """線 1 本ぶんの判定。HeadingGate・EpisodeGate と同じ使い方（update / info / vector）。"""

    def __init__(self, start, end, fps, frame=None, tol=0.3, vec_frames=3, min_move=0.1, across_ratio=0.5,
                 extend_seconds=1.0, vanish_frames=2, near=0.6, dedupe_seconds=2.0, dedupe_dist=0.8,
                 bottom_margin=0.04, inside_margin=0.04, history=8, rev_seconds=0.0, **_ignored):
        self.a = np.array(start, float)
        v = np.array(end, float) - self.a
        self.length = float(np.hypot(*v)) or 1.0
        self.u = v / self.length
        self.n = np.array([v[1], -v[0]]) / self.length  # IN の向き
        self.frame = frame
        self.tol, self.vec_frames, self.min_move, self.across_ratio = tol, vec_frames, min_move, across_ratio
        self.extend_frames = max(1, int(round(extend_seconds * fps)))
        self.vanish_frames, self.near = vanish_frames, near
        self.dedupe_frames, self.dedupe_dist = max(1, int(round(dedupe_seconds * fps))), dedupe_dist
        self.bottom_margin, self.inside_margin, self.history = bottom_margin, inside_margin, history
        self.rev_frames = int(round(rev_seconds * fps))  # 同じ人が、数えたあと、この間に、逆向きに越えても、数えない（足元のぶれで、行ったり来たりした分）
        self.kinds = {}
        self.tracks = {}
        self.recent = []
        self.tick = 0

    # ---- 幾何 ----
    def _cross(self, p0, p1, h):
        """線分 p0→p1 が、数える線と交わるか。交われば、向き（+1＝IN、−1＝OUT）。交わらなければ 0。"""
        d0 = float(np.dot(p0 - self.a, self.n))
        d1 = float(np.dot(p1 - self.a, self.n))
        if d0 * d1 >= 0:  # 同じ側（または、線の上ぴったり）：交わらない
            return 0
        t = d0 / (d0 - d1)  # p0 から p1 の間の、交わる位置
        along = float(np.dot(p0 + (p1 - p0) * t - self.a, self.u))
        if not (-self.tol * h <= along <= self.length + self.tol * h):
            return 0
        return 1 if d1 > d0 else -1

    def _moving_across(self, pts, direction, h):
        """直近の動きが、direction の向きに、線を横切っているか。"""
        k = min(len(pts), self.vec_frames + 1)
        if k < 2:
            return True
        d = pts[-1] - pts[-k]
        dn = float(np.dot(d, self.n)) * direction / h
        dt = abs(float(np.dot(d, self.u))) / h
        return dn >= self.min_move and dn >= self.across_ratio * dt

    def _inside(self, pt):
        if self.frame is None:
            return True
        w, h = self.frame
        m = self.inside_margin
        return m * w <= pt[0] <= (1 - m) * w and m * h <= pt[1] <= (1 - m) * h

    # ---- 画面に出す用 ----
    def info(self, tid):
        st = self.tracks.get(int(tid))
        if st is None:
            return None
        return (0, 0.0, bool(st.inz), 0)

    def vector(self, tid):
        return None

    # ---- 更新 ----
    def _emit(self, out, direction, tid, pt, h, kind="cross"):
        self.kinds[(tid, direction)] = kind  # 種類（cross＝交差 / born＝見え始め / vanish＝見えなくなった）。評価用の記録
        self.recent = [r for r in self.recent if self.tick - r[0] <= self.dedupe_frames]
        for r in self.recent:
            if r[1] == direction and float(np.hypot(*(np.asarray(pt, float) - r[2]))) <= self.dedupe_dist * max(h, 1.0):
                return False
        self.recent.append((self.tick, direction, np.asarray(pt, float)))
        out.append((direction, tid, pt))
        return True

    def update(self, ids, points, heights):
        self.tick += 1
        out, seen = [], set()
        for tid, pt, h in zip(ids, points, heights):
            tid = int(tid)
            seen.add(tid)
            pt = np.asarray(pt, float)
            h = max(float(h), 1.0)
            st = self.tracks.get(tid)
            if st is None:
                st = self.tracks[tid] = _Track(self.history)
                st.first_pt = pt
            st.absent = 0
            st.last_h = h
            st.inz = abs(float(np.dot(pt - self.a, self.n))) <= self.near * h
            if st.pts:
                # 1) 直前の点 → いまの点 が、線と交わったか
                direction = self._cross(st.pts[-1], pt, h)
                if direction and self._moving_across(list(st.pts) + [pt], direction, h):
                    if st.last_dir == -direction and self.tick - st.counted_tick <= self.rev_frames:
                        pass  # 数えた直後の、逆向き：行ったり来たりしただけ
                    elif self._emit(out, "in" if direction > 0 else "out", tid, pt, h):
                        st.counted_tick, st.last_dir = self.tick, direction
            st.pts.append(pt)
            # 2) 見え始め：最初の 2 点の動きを、逆向きに伸ばして、線と交わるか（扉から出てきた人）
            if len(st.pts) == 2 and not st.born_checked:
                st.born_checked = True
                p0, p1 = st.pts[0], st.pts[1]
                if self._inside(p0) and abs(float(np.dot(p0 - self.a, self.n))) <= self.near * h:
                    back = p0 - (p1 - p0) * self.extend_frames
                    direction = self._cross(back, p0, h)
                    if direction and self._moving_across([back, p0, p1], direction, h) and self.tick - st.counted_tick > 1:
                        if self._emit(out, "in" if direction > 0 else "out", tid, p1, h, "born"):
                            st.counted_tick = self.tick
        # 3) 見えなくなった人：最後の動きを、先へ伸ばして、線と交わるか（扉の中へ入る人）
        for tid in [t for t in self.tracks if t not in seen]:
            st = self.tracks[tid]
            st.absent += 1
            if st.absent == self.vanish_frames and not st.vanish_done and len(st.pts) >= 2:
                st.vanish_done = True
                k = min(len(st.pts), self.vec_frames + 1)
                last, first = st.pts[-1], st.pts[-k]
                v = (last - first) / (k - 1)
                h = st.last_h or 100.0
                ahead = last + v * self.extend_frames
                direction = self._cross(last, ahead, h) if self.frame is None or last[1] <= (1 - self.bottom_margin) * self.frame[1] else 0
                if direction and self._moving_across([first, last, ahead], direction, h) and self.tick - st.counted_tick > self.vanish_frames + 1:
                    self._emit(out, "in" if direction > 0 else "out", tid, last, h, "vanish")
            if st.absent >= self.vanish_frames + self.dedupe_frames + 8:
                del self.tracks[tid]
        return out
