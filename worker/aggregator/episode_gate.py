"""線のどちら側にいたか（側）の変わり目で、IN/OUT を決める判定。座標だけで決める（画像・追跡・状態管理は見ない）。

人（人 ID）ごとに、渡された座標を、順に見て、「線のどちら側に、確かにいたか」だけを覚える。側が入れ替わったら、1 回数える。
見え始め・消えた人の補完（予想した座標）は、lifecycle.py が、座標のリストとして、渡してくる。ここでは、特別に扱わない。

【側】足元の点と線の距離 d（IN の向きが正）を、枠の高さ h で割った s = d/h で決める。
  s > margin なら +側、s < −margin なら −側、間（線のすぐそば）は、どちらでもない（ぶれの余地）。
  同じ側が confirm_frames 続いたら、その側に「確かにいた」とする。線の範囲の外（延長線の先、端から tol 倍の枠の高さまで許す）は、側を決めない。
【数える】確かにいた側が、−側→＋側になったら IN、＋側→−側になったら OUT。最初に確かにいた側は、数えない。
【重複】同じ向きの通過が、近い場所・短い時間に出たら、1 回にまとめる（追跡の付け替わり対策）。
"""

import numpy as np


class _Track:
    __slots__ = ("side", "cand", "run", "inz", "counted")

    def __init__(self):
        self.side = 0  # 確かにいた側（0＝まだ）
        self.cand, self.run = 0, 0  # いま続いている側と、その長さ
        self.inz = False
        self.counted = 0  # 最後に数えた向き


class EpisodeGate:
    """線 1 本ぶんの判定。"""

    def __init__(self, start, end, fps, frame=None, margin=0.12, confirm_frames=1, zone=0.6, tol=0.3,
                 dedupe_seconds=2.0, dedupe_dist=0.8, **_ignored):
        self.a = np.array(start, float)
        v = np.array(end, float) - self.a
        self.length = float(np.hypot(*v)) or 1.0
        self.u = v / self.length
        self.n = np.array([v[1], -v[0]]) / self.length  # IN の向き
        self.margin, self.confirm, self.zone, self.tol = margin, confirm_frames, zone, tol
        self.dedupe_frames, self.dedupe_dist = max(1, int(round(dedupe_seconds * fps))), dedupe_dist
        self.tracks = {}
        self.recent = []  # 最近数えた (フレーム番号, 向き, 点)
        self.tick = 0

    def _span(self, pt, h):
        """線の範囲の内側か（端から tol 倍の枠の高さまで許す）。"""
        al = float(np.dot(pt - self.a, self.u))
        return -self.tol * h <= al <= self.length + self.tol * h

    # ---- 画面に出す用 ----
    def info(self, pid):
        """(側, スコア, 線のそばか, 数えた向き)。スコアは無いので、確かな側にいるときは 1。"""
        st = self.tracks.get(int(pid))
        if st is None:
            return None
        return (int(st.side), 1.0 if st.side else 0.0, bool(st.inz), int(st.counted))

    def vector(self, pid):
        return None

    # ---- 判定 ----
    def feed(self, pid, state, pts, tick):
        """人 pid の座標のリスト pts（[x, y, 枠の高さ, 予想か]）を、順に判定する。state は starting / moving / deleted。
        数えた通過 [(向き, 人ID, 点)] を返す。deleted のときは、そのあとで、その人の状態を捨てる。"""
        self.tick = tick
        out = []
        st = self.tracks.get(pid)
        if st is None:
            st = self.tracks[pid] = _Track()
        for x, y, h, _pred in pts:
            self._observe(out, pid, st, np.array([x, y], float), max(float(h), 1.0))
        if state == "deleted":
            self.tracks.pop(pid, None)
        return out

    def _observe(self, out, pid, st, pt, h):
        s = float(np.dot(pt - self.a, self.n)) / h
        span = self._span(pt, h)
        st.inz = abs(s) <= self.zone and span
        if not span:
            return
        side_now = 1 if s > self.margin else (-1 if s < -self.margin else 0)
        if side_now == 0:
            return
        if side_now == st.cand:
            st.run += 1
        else:
            st.cand, st.run = side_now, 1
        if st.run < self.confirm or st.cand == st.side:
            return
        if st.side != 0:  # 確かにいた側が、入れ替わった：線を越えた
            st.counted = st.cand
            self._emit(out, "in" if st.cand > 0 else "out", pid, pt, h)
        st.side = st.cand

    def _emit(self, out, direction, pid, pt, h):
        """重複を除いて、数える。"""
        self.recent = [r for r in self.recent if self.tick - r[0] <= self.dedupe_frames]
        for r in self.recent:
            if r[1] == direction and float(np.hypot(*(pt - r[2]))) <= self.dedupe_dist * h:
                return
        self.recent.append((self.tick, direction, pt))
        out.append((direction, pid, pt))
