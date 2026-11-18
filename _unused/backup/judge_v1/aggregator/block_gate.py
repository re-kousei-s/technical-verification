"""ブロックで決める判定：線の両側に、奥行きのある四角（ブロック）を置き、「相手側のブロックに入って、そこから出た／消えた」で数える。

  ─側ブロック │ すき間 │ ＋側ブロック          s = 線からの距離 ÷ 枠の高さ（IN の向きが正）
  -depth … -margin │ ±margin │ margin … depth      線の範囲（端から tol 倍の枠の高さまで）の中だけ

人（人 ID）ごとに、渡された座標を順に見る。
  1. 片方のブロックに、確かにいた（confirm_frames 続いた）→ その側を「元の側」として覚える。
  2. 元の側と反対のブロックに入った → 保留（まだ数えない）。
  3. 保留のまま、次のどれかが起きたら、数える（－側→＋側なら IN、＋側→－側なら OUT）。元の側は、入った側に変わる。
       ・そのブロックから、奥（depth の先）か、横（線の範囲の外）へ出た
       ・消えた（deleted。消えたあとの予想の座標も、ここまでに見る）
       ・そのブロックに、hold_frames 留まった（越えて止まった人）
  4. 保留のまま、元の側のブロックへ戻った → 取り消し（線のそばで行き来しただけ）。
すき間（線のすぐそば）にいる間は、保留も、元の側も、変えない。
同じ向きの通過が、近い場所・短い時間に出たら、1 回にまとめる（追跡の付け替わり対策）。
"""

import numpy as np


class _Track:
    __slots__ = ("side", "cand", "run", "pend", "pend_pt", "pend_h", "dwell", "inz", "counted", "last")

    def __init__(self):
        self.side = 0  # 元の側（確かにいたブロック。0＝まだ）
        self.cand, self.run = 0, 0  # いま続いているブロックと、その長さ
        self.pend = 0  # 保留中の、入った側（0＝保留なし）
        self.pend_pt, self.pend_h = None, 1.0
        self.dwell = 0  # 保留のまま、入った側のブロックにいたフレーム数
        self.inz = False
        self.counted = 0
        self.last = None  # 直前の点


class BlockGate:
    """線 1 本ぶんの判定（ブロック）。"""

    def __init__(self, start, end, fps, frame=None, margin=0.12, depth=1.5, hold_frames=6, confirm_frames=1,
                 zone=0.6, tol=0.3, dedupe_seconds=2.0, dedupe_dist=0.8, cancel_jump=0.0, cancel_frames=0, **_ignored):
        self.a = np.array(start, float)
        v = np.array(end, float) - self.a
        self.length = float(np.hypot(*v)) or 1.0
        self.u = v / self.length
        self.n = np.array([v[1], -v[0]]) / self.length  # IN の向き
        self.margin, self.depth, self.hold = margin, depth, int(hold_frames)
        self.confirm, self.zone, self.tol = confirm_frames, zone, tol
        self.dedupe_frames, self.dedupe_dist = max(1, int(round(dedupe_seconds * fps))), dedupe_dist
        # 元の側へ戻ったとき、直前の点から、枠の高さの cancel_jump 倍より大きく跳んでいたら、取り消さずに数える（0 で、いつも取り消す）。
        # 人がすれ違うと、追跡の ID が入れ替わり、1 つの ID が「入った → すぐ戻った」に見えるため（本物の 2 件の通過）
        self.cancel_jump = cancel_jump
        # 取り消すのは、入った側に cancel_frames 以下しかいなかったとき（0 で、いつも）。長くいてから戻った人は、入って出てきた（2 回の通過）
        self.cancel_frames = int(cancel_frames)
        self.tracks = {}
        self.recent = []
        self.tick = 0

    def _where(self, pt, h):
        """(どのブロックか（+1 / -1 / 0＝すき間 / None＝ブロックの外）, s)"""
        s = float(np.dot(pt - self.a, self.n)) / h
        al = float(np.dot(pt - self.a, self.u))
        if not (-self.tol * h <= al <= self.length + self.tol * h) or abs(s) > self.depth:
            return None, s
        if abs(s) <= self.margin:
            return 0, s
        return (1 if s > 0 else -1), s

    # ---- 画面に出す用 ----
    def info(self, pid):
        st = self.tracks.get(int(pid))
        if st is None:
            return None
        return (int(st.pend or st.side), 1.0 if st.side else 0.0, bool(st.inz), int(st.counted))

    def vector(self, pid):
        return None

    # ---- 判定 ----
    def feed(self, pid, state, pts, tick):
        self.tick = tick
        out = []
        st = self.tracks.get(pid)
        if st is None:
            st = self.tracks[pid] = _Track()
        for x, y, h, _pred in pts:
            self._observe(out, pid, st, np.array([x, y], float), max(float(h), 1.0))
        if state == "deleted":
            if st.pend:  # 入ったまま消えた：数える
                self._count(out, pid, st)
            self.tracks.pop(pid, None)
        return out

    def _count(self, out, pid, st):
        st.counted = st.side = st.pend
        self._emit(out, "in" if st.pend > 0 else "out", pid, st.pend_pt, st.pend_h)
        st.pend, st.dwell = 0, 0

    def _observe(self, out, pid, st, pt, h):
        last, st.last = st.last, pt
        blk, s = self._where(pt, h)
        st.inz = blk is not None and abs(s) <= self.zone
        if st.pend:
            if blk is None:  # 入った側のブロックから、奥か横へ出た：数える
                self._count(out, pid, st)
                return
            if blk == st.pend:
                st.dwell += 1
                if st.dwell >= self.hold:  # 入った側に、留まった：数える
                    self._count(out, pid, st)
                return
            if blk == -st.pend:  # 元の側へ戻った
                jumped = self.cancel_jump > 0 and last is not None and float(np.hypot(*(pt - last))) > self.cancel_jump * h
                if jumped or (self.cancel_frames > 0 and st.dwell > self.cancel_frames):
                    self._count(out, pid, st)  # 大きく跳んだ：別の人に入れ替わった。入った人は、数える
                    st.cand, st.run = blk, 1
                    return
                st.pend, st.dwell = 0, 0  # 取り消し（線のそばで行き来しただけ）
                st.cand, st.run = blk, 1
            return  # すき間：そのまま待つ
        if blk is None or blk == 0:
            return
        if blk == st.cand:
            st.run += 1
        else:
            st.cand, st.run = blk, 1
        if st.run < self.confirm or st.cand == st.side:
            return
        if st.side != 0:  # 元の側と反対のブロックに入った：保留
            st.pend, st.pend_pt, st.pend_h, st.dwell = st.cand, pt, h, 1
            if st.dwell >= self.hold:
                self._count(out, pid, st)
            return
        st.side = st.cand

    def _emit(self, out, direction, pid, pt, h):
        self.recent = [r for r in self.recent if self.tick - r[0] <= self.dedupe_frames]
        for r in self.recent:
            if r[1] == direction and float(np.hypot(*(pt - r[2]))) <= self.dedupe_dist * h:
                return
        self.recent.append((self.tick, direction, pt))
        out.append((direction, pid, pt))
