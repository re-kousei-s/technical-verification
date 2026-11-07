"""線のどちら側にいたか（側）の変わり目で、IN/OUT を決める判定。スコアを積まない。

HeadingGate（スコア方式）は、見え始めた直後・追跡が途切れた直後に、履歴が 0 から始まるため、数え漏れた。
こちらは、人（追跡）ごとに、「線のどちら側に、確かにいたか」だけを覚えて、側が入れ替わったときに、1 回数える。

【側】足元の点と線の距離 d（IN の向きが正）を、枠の高さ h で割った s = d/h で決める。
  s > margin なら +側、s < −margin なら −側、間（線のすぐそば）は、どちらでもない（ぶれの余地）。
  同じ側が confirm_frames フレーム続いたら、その側に「確かにいた」とする。線の範囲の外（延長線の先）は、側を決めない。
【数える】
  ・確かにいた側が、−側→＋側になったら IN、＋側→−側になったら OUT。
  ・線のすぐそば（reach 以内）で見え始めた人（扉から出てきた人）：最初に確かにいた側へ、離れていったとき、反対側から来たとみなして数える。
  ・線のすぐそば（reach 以内）に向かっていって、見えなくなった人（扉の中へ入る人）：向かっていた側の反対側へ、行ったとみなして数える。
【途切れた追跡をつなぐ】
  近くで見えなくなった追跡と、すぐあとに近くで見え始めた追跡は、同じ人とみなして、側の履歴を引き継ぐ（stitch_seconds・stitch_dist）。
  見えなくなったことによる「入った」の確定は、つなぐ猶予（stitch_seconds）が過ぎてから行う。
【重複】同じ向きの通過が、近い場所・短い時間に出たら、1 回にまとめる（追跡の付け替わり対策）。
"""

from collections import deque

import numpy as np


class _Track:
    __slots__ = ("watch", "born_top", "hmax", "nfr", "pts", "side", "cand", "run", "born_near", "born_pt", "born_done", "last_pt", "last_h", "last_s", "min_abs",
                 "absent", "dead_at", "claimed", "inz", "counted", "vanish_done", "stitched", "inherit_ok")

    def __init__(self):
        self.watch = None  # 監視中の、見え始めの (点, 枠の高さ) の並び（補完のため）。None なら、監視していない
        self.born_top, self.hmax, self.nfr = 0.0, 0.0, 10**9  # 見え始めの、枠の上端・最大の高さ・見えてからのフレーム数（補正用）
        self.pts = deque(maxlen=6)  # 直近の (s, 足元) 。近づいているかの判定に使う
        self.side = 0  # 確かにいた側（0＝まだ）
        self.cand, self.run = 0, 0  # いま続いている側と、その長さ
        self.born_near, self.born_pt, self.born_done = False, None, False
        self.last_pt = self.last_h = self.last_s = None
        self.min_abs = 1e9
        self.absent = 0
        self.dead_at = None
        self.claimed = False  # 見えなくなったあとに、別の追跡に引き継がれた
        self.inz = False
        self.counted = 0
        self.vanish_done = False
        self.stitched = False


class EpisodeGate:
    """線 1 本ぶんの判定。HeadingGate と同じ使い方（update / info / vector）。"""

    def __init__(self, start, end, fps, frame=None, margin=0.15, confirm_frames=1, reach=0.35, away=0.25,
                 vanish_frames=3, stitch_seconds=1.5, stitch_dist=1.0, dedupe_seconds=2.0, dedupe_dist=0.8,
                 zone=0.6, inside_margin=0.04, hold_seconds=0.0, bottom_margin=0.04, vanish_reach=None, approach_min=0.1, cross_disp=0.0, across_ratio=0.0, vec_frames=4, born_refit=False, refit_frames=4, refit_reach=None, born_backfill=False, backfill_frames=3, watch_frames=3, backfill_reach=None, vanish_predict=0, **_ignored):
        self.a = np.array(start, float)
        v = np.array(end, float) - self.a
        self.length = float(np.hypot(*v)) or 1.0
        self.u = v / self.length
        self.n = np.array([v[1], -v[0]]) / self.length  # IN の向き
        self.frame = frame
        self.margin, self.confirm, self.reach, self.away = margin, confirm_frames, reach, away
        self.vanish_frames = vanish_frames
        self.stitch_frames = max(1, int(round(stitch_seconds * fps)))
        self.stitch_dist = stitch_dist
        self.dedupe_frames, self.dedupe_dist = max(1, int(round(dedupe_seconds * fps))), dedupe_dist
        self.zone, self.inside_margin = zone, inside_margin
        # 側が入れ替わったときの、直近の動き（vec_frames フレーム）が、ちゃんと線を横切っているか：
        #   線に垂直な動き（枠の高さ比）が cross_disp 以上、かつ、線に沿った動きの across_ratio 倍以上（線に沿って歩いただけの人を、除く）
        self.cross_disp, self.across_ratio, self.vec_frames = cross_disp, across_ratio, vec_frames
        # 見え始めの位置の補正：見え始めの枠は、扉や人の陰から出てくるので、最初の数フレームは、枠が小さく、足元が上にある。
        # refit_frames フレーム待って、そのあいだの最大の枠の高さ（本当の背丈）がわかったら、「頭の位置（枠の上端）＋ 背丈」を、本当の足元として、見え始めの位置を計算し直す
        self.born_refit, self.refit_frames = born_refit, max(2, int(refit_frames))
        self.refit_reach = reach if refit_reach is None else refit_reach  # 補正した見え始めの位置が、線から、この距離（枠の高さ比）以内なら、扉から出てきた人とみなす
        # 見え始めの履歴の補完：線のそばで見え始めた人を、watch_frames フレーム、監視対象にする（そのあいだは、判定しない）。
        # そのあとの動きから、見え始める前の backfill_frames フレームぶんの位置を、予想して、軌跡の頭に足し、通常の判定を、最初からやり直す。
        # 予想した前の位置が、線の反対側なら、普通の「線を越えた」として、数えられる（見え始めの特別ルールは、使わない）
        self.born_backfill, self.backfill_frames, self.watch_frames = born_backfill, max(1, int(backfill_frames)), max(2, int(watch_frames))
        self.backfill_reach = reach if backfill_reach is None else backfill_reach
        # 見えなくなった人の判定に、先の位置の予想を使う：直前の動きから、vanish_predict フレーム先の位置を予想し、予想した位置が、線に届く（越える）なら、扉の中へ入ったとみなす。
        # 線に沿って歩いて、消えた人を、除ける。0 なら、予想を使わない（近づいていたかだけで決める）
        self.vanish_predict = vanish_predict
        self.bottom_margin = bottom_margin  # 見えなくなった位置が、画面の下の端（この割合以内）なら、手前へ歩き去っただけとみなす（扉の中へ入ったのではない）
        self.vanish_reach = reach if vanish_reach is None else vanish_reach  # 見えなくなった位置が、線からこの距離（枠の高さ比）以内なら、扉の中へ入ったとみなす
        self.approach_min = approach_min  # 見えなくなる前に、線へ、これだけ（枠の高さ比）近づいていること
        self.hold_frames = int(round(hold_seconds * fps))  # 越えてから、この間は、数えずに待つ。すぐ戻ったら、両方とも数えない
        self.kinds = {}
        self.pending = []  # 数えるのを待っている通過 [期限のフレーム番号, 向き, 追跡ID, 点, 枠の高さ]
        self.tracks = {}
        self.dying = {}  # 見えなくなって、つなぎ先を待っている追跡
        self.recent = []  # 最近数えた (フレーム番号, 向き, 点)
        self.tick = 0

    # ---- 幾何 ----
    def _along(self, pt):
        return float(np.dot(np.asarray(pt, float) - self.a, self.u))

    def _span(self, pt, h):
        return -0.3 * h <= self._along(pt) <= self.length + 0.3 * h

    def _inside(self, pt):
        if self.frame is None:
            return True
        w, h = self.frame
        m = self.inside_margin
        return m * w <= pt[0] <= (1 - m) * w and m * h <= pt[1] <= (1 - m) * h

    # ---- 画面に出す用 ----
    def info(self, tid):
        """(向き, スコア, 線のそばか, 数えた向き)。スコアは無いので、側（+1/−1）を向きに、確かな側にいるときは 1 を出す。"""
        st = self.tracks.get(int(tid))
        if st is None:
            return None
        return (int(st.side), 1.0 if st.side else 0.0, bool(st.inz), int(st.counted))

    def vector(self, tid):
        return None

    # ---- 更新 ----
    def _emit(self, out, direction, tid, pt, h):
        """重複を除いて、数える。"""
        self.recent = [r for r in self.recent if self.tick - r[0] <= self.dedupe_frames]
        for r in self.recent:
            if r[1] == direction and float(np.hypot(*(np.asarray(pt, float) - r[2]))) <= self.dedupe_dist * max(h, 1.0):
                return
        self.recent.append((self.tick, direction, np.asarray(pt, float)))
        out.append((direction, tid, pt))

    def _push(self, out, direction, tid, pt, h, kind="cross"):
        """通過を、すぐには数えず、保留する。同じ人が、保留のあいだに、逆向きに戻ったら、両方とも、数えない（行って、戻っただけ）。"""
        self.kinds[(tid, direction)] = kind  # 種類（cross＝側の入れ替わり / born＝見え始め / vanish＝見えなくなった）。評価用の記録
        if self.hold_frames <= 0:
            self._emit(out, direction, tid, pt, h)
            return
        for p in self.pending:
            if p[2] == tid and p[1] != direction:
                self.pending.remove(p)
                return
        self.pending.append([self.tick + self.hold_frames, direction, tid, np.asarray(pt, float), h])

    def _flush(self, out):
        due = [p for p in self.pending if p[0] <= self.tick]
        self.pending = [p for p in self.pending if p[0] > self.tick]
        for _, direction, tid, pt, h in due:
            self._emit(out, direction, tid, pt, h)

    def _stitch(self, st, tid, pt, h):
        """新しい追跡に、近くで見えなくなった追跡の履歴を、引き継ぐ。"""
        best, bd = None, 1e9
        for did, d in self.dying.items():
            if d.claimed:
                continue
            dist = float(np.hypot(*(pt - d.last_pt))) / max(h, 1.0)
            if dist <= self.stitch_dist and dist < bd:
                best, bd = did, dist
        if best is None:
            return False
        d = self.dying[best]
        d.claimed = True
        st.side, st.cand, st.run, st.counted = d.side, d.cand, d.run, d.counted
        st.born_near, st.born_done = False, True  # つながった：新しく出てきた人ではない
        st.stitched = True
        return True

    def _observe(self, out, tid, st, pt, h):
        """人 1 人の、1 点ぶんの観測を、判定する（側の更新・線を越えたかの判定）。"""
        s = float(np.dot(pt - self.a, self.n)) / h
        span = self._span(pt, h)
        if st.nfr < self.refit_frames:
            st.hmax, st.nfr = max(st.hmax, h), st.nfr + 1
        st.pts.append((s, pt))
        st.last_pt, st.last_h, st.last_s = pt, h, s
        st.inz = abs(s) <= self.zone and span
        st.min_abs = min(st.min_abs, abs(s))
        side_now = 0
        if span:
            side_now = 1 if s > self.margin else (-1 if s < -self.margin else 0)
        if side_now == 0:
            return
        if side_now == st.cand:
            st.run += 1
        else:
            st.cand, st.run = side_now, 1
        if st.run < self.confirm or st.cand == st.side:
            return
        if st.side != 0:
            # 確かにいた側が、入れ替わった：線を越えた。動きが、ちゃんと線を横切っていれば、数える
            if self._across(st, pt, h):
                st.counted = st.cand
                self._push(out, "in" if st.cand > 0 else "out", tid, pt, h)
            st.side = st.cand
        elif st.born_near and not st.born_done and self.born_refit and st.nfr < self.refit_frames:
            return  # 枠が育つのを待つ（まだ、見え始めの位置を、補正できない）
        elif st.born_near and not st.born_done:
            # 線のすぐそばで見え始めた人が、離れていった：反対側から来た（扉を出てきた）。まだ離れていなければ、待つ
            bp, hb = st.born_pt, h
            if self.born_refit:  # 補正した足元：頭の位置 ＋ 背丈
                bp, hb = np.array([st.born_pt[0], st.born_top + st.hmax]), max(st.hmax, 1.0)
                if not (abs(float(np.dot(bp - self.a, self.n)) / hb) <= self.refit_reach and self._span(bp, hb)):
                    st.born_near, st.side = False, st.cand  # 補正すると、線のそばではない：扉から出てきた人ではない
                    return
            if abs(float(np.dot(pt - bp, self.n))) / h >= self.away:
                st.counted = st.cand
                self._push(out, "in" if st.cand > 0 else "out", tid, pt, h, "born")
                st.born_done = True
                st.side = st.cand
        else:
            st.side = st.cand  # 最初に確かにいた側（数えない）

    def update(self, ids, points, heights):
        self.tick += 1
        out, seen = [], set()
        self._flush(out)
        for tid, pt, h in zip(ids, points, heights):
            tid = int(tid)
            seen.add(tid)
            pt = np.asarray(pt, float)
            h = max(float(h), 1.0)
            st = self.tracks.get(tid)
            if st is None:
                st = self.tracks[tid] = _Track()
                s = float(np.dot(pt - self.a, self.n)) / h
                span = self._span(pt, h)
                if not self._stitch(st, tid, pt, h):
                    # 線のすぐそばで見え始めた（画面の端ではない）：扉から出てきた人かもしれない
                    st.born_near = abs(s) <= self.reach and span and self._inside(pt)
                    st.born_pt = pt
                    st.born_top, st.hmax, st.nfr = pt[1] - h, h, 1
                    if self.born_refit:
                        st.born_near = self._inside(pt)  # 線のそばか、は、補正した位置で決める
                    if self.born_backfill and abs(s) <= self.backfill_reach and span and self._inside(pt):
                        st.watch, st.born_near = [], False  # 監視対象にする（見え始めの特別ルールは、使わない）
            st.absent = 0
            if st.watch is not None:
                st.watch.append((pt, h))
                st.last_pt, st.last_h = pt, h
                if len(st.watch) < self.watch_frames:
                    continue  # 監視中：まだ判定しない
                w, st.watch = st.watch, None
                p1, h1 = w[0]
                v = (w[-1][0] - p1) / (len(w) - 1)  # 1 フレームあたりの動き
                for i in range(self.backfill_frames, 0, -1):
                    self._observe(out, tid, st, p1 - v * i, h1)  # 見え始める前の位置を、予想して、足す
                for p, hh in w:
                    self._observe(out, tid, st, p, hh)  # 実際の位置を、順に、判定し直す
                continue
            self._observe(out, tid, st, pt, h)
        # 見えなくなった人
        for tid in [t for t in self.tracks if t not in seen]:
            st = self.tracks[tid]
            st.absent += 1
            if st.absent == self.vanish_frames and tid not in self.dying:
                st.dead_at = self.tick
                self.dying[tid] = st
            if st.absent >= self.vanish_frames + self.stitch_frames:
                self._finish(out, tid, st)
                del self.tracks[tid]
                self.dying.pop(tid, None)
        return out

    def _across(self, st, pt, h):
        """直近の動きが、線を横切っているか（越えた向きに、cross_disp 以上、線に沿った動きの across_ratio 倍以上）。"""
        if self.cross_disp <= 0 and self.across_ratio <= 0:
            return True
        k = min(len(st.pts), self.vec_frames)
        if k < 2:
            return True  # 動きが分からない：側の入れ替わりだけで、数える
        d = pt - st.pts[-k][1]
        dn = float(np.dot(d, self.n)) / h * (1 if st.cand > 0 else -1)  # 越えた向きの動き
        dt = abs(float(np.dot(d, self.u))) / h
        return dn >= self.cross_disp and dn >= self.across_ratio * dt

    def _finish(self, out, tid, st):
        """つなぎ先が現れないまま、猶予が過ぎた：線のすぐそばに向かって、見えなくなった人は、反対側へ行った（扉の中へ入った）。"""
        if st.claimed or st.vanish_done or st.last_pt is None:
            return
        st.vanish_done = True
        if st.side == 0:
            return
        # 画面の下の端で見えなくなった人は、手前へ歩き去っただけ（画面の左右の端は、扉があることがあるので、除かない）
        not_bottom = self.frame is None or st.last_pt[1] <= (1 - self.bottom_margin) * self.frame[1]
        near = abs(st.last_s) <= self.vanish_reach and self._span(st.last_pt, st.last_h) and not_bottom
        # いまの側から見て、線に近づいていたか（確かにいた側の s が、直近で減っている。越えたあとに離れていた人は、含めない）
        approach = len(st.pts) >= 3 and (st.pts[0][0] - st.pts[-1][0]) * st.side >= self.approach_min
        if approach and self.vanish_predict > 0:
            k = min(len(st.pts), 3)
            v = (st.pts[-1][0] - st.pts[-k][0]) / (k - 1)  # 1 フレームあたりの、線に垂直な動き
            approach = (st.last_s + v * self.vanish_predict) * st.side <= 0.0  # 先の位置が、線に届く（越える）
        if near and approach and st.counted != -st.side:
            direction = "in" if -st.side > 0 else "out"
            st.counted = -st.side
            self._push(out, direction, tid, st.last_pt, st.last_h, "vanish")
