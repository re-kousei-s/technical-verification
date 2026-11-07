"""軌跡の向きと、線をまたいだ事実を、スコアにためて、IN/OUT を決める判定（線を、ぴったり越えなくてよい）。

1 人（追跡 ID）ごと・線ごとに、スコアを持つ（+ が IN、− が OUT。IN の向きは、LineZone と同じ＝始点→終点に対して画面の左側）。

【軌跡から向きを出す】
  足元の点を、直近 window（5）点まで覚える。新しい点が来るたびに、古い点それぞれから、いまの点へのベクトルを出し、
  遠い点からのものほど重く平均する（1 フレームだけのベクトルは、検出のぶれに弱いため）。
  向きの確かさ＝各ベクトルが、平均の向きに、どれだけ揃っているか。

【スコアの上げ下げ】（入口のそば＝枠の高さ × zone 以内にいるときだけ）
  ・向きが揃って（確かさ c_min 以上）、線に対して進んでいる（窓の中で、枠の高さ × min_win 以上）→ その向きに +1
    逆向きのスコアがたまっているときは、逆向きに 2 倍の重さ（引き返しは、大きく下げる）
  ・立ち止まり・ぶれ → スコアを半分にする（立ち話では、スコアが、たまらない）
  ・線をまたいだ（座標で分かる）→ またいだ向きに +cross_w。ただし、そのときの向きと、一致するときだけ。
    食い違うときは、加えない（「疑い」）。反対向きに、flip_seconds 以内に、またぎ返したら、さらに 1 減らす（IN/OUT が交互に出るのを防ぐ）
  ・線の後ろ（または、線のすぐ手前、枠の高さ × reach 以内）で消えた → vanish_frames フレームたったら +vanish_bonus。戻ってきて、逆向きに動いたら −return_penalty
  ・線のすぐそばで見え始めた人（扉から出てきた人）：履歴がなく、スコアが 0 から始まるので、線から離れる向きに動き出したとき、初期のスコア +born_bonus を加える
【判定】
  スコアが ±threshold に届いたら、候補。confirm_frames フレームの間、スコアが保たれたら、確定して 1 回数える（その間に下がったら、取り消し）。
  消えた場合と、同じ向きに進み続けて、入口のそばを出ていった場合は、待たずに確定する。同じ人が、同じ向きに、続けて数えられることはない。反対向きは、もう一度 ±threshold まで、ためたときだけ。
  線のすぐそば（枠の高さ × reach 以内）まで、実際に来た人だけ、数える（線の手前を、通り過ぎただけの人は、数えない）。
"""

from collections import deque

import numpy as np


class _State:
    __slots__ = ("pts", "score", "counted", "pending", "absent", "last_pt", "last_h", "last_d", "min_d", "inz",
                 "away", "bonus", "suspect", "last_cross", "cross_age", "vec", "conf", "born_near", "born_done")

    def __init__(self, maxlen):
        self.pts = deque(maxlen=maxlen)  # (足元の点, 線までの距離 d, 枠の高さ h)
        self.score = 0.0
        self.counted = 0  # 最後に数えた向き（0＝まだ）
        self.pending = None  # 確定待ちの残りフレーム数
        self.absent = 0
        self.last_pt = self.last_h = self.last_d = None
        self.min_d = 1e9
        self.inz = False
        self.away = 0
        self.bonus = False  # 消えたことによる加算を、済ませたか
        self.suspect = False  # またいだ向きと、進む向きが、食い違った
        self.last_cross, self.cross_age = 0, 10**9
        self.vec, self.conf = None, 0.0
        self.born_near = False  # 線のすぐそばで、見え始めたか（扉から出てきた人）
        self.born_done = False


class HeadingGate:
    """線 1 本ぶんの判定。"""

    def __init__(self, start, end, fps, frame=None, zone=0.4, reach=0.3, v_min=0.1, min_win=0.08, c_min=0.5, window=5,
                 cross_w=1.0, flip_seconds=5.0, threshold=3.0, confirm_frames=6, vanish_frames=3, vanish_bonus=2.0,
                 return_penalty=3.0, cap=6.0, born_bonus=2.0, dedupe_seconds=2.0, dedupe_dist=0.8, exit_all=False, **_ignored):
        self.a = np.array(start, float)
        v = np.array(end, float) - self.a
        self.length = float(np.hypot(*v)) or 1.0
        self.u = v / self.length
        self.n = np.array([v[1], -v[0]]) / self.length  # IN の向き
        self.dt = 1.0 / fps
        self.frame, self.zone, self.reach, self.v_min, self.min_win, self.c_min = frame, zone, reach, v_min, min_win, c_min
        self.window, self.cross_w, self.flip_frames = window, cross_w, int(flip_seconds * fps)
        self.threshold, self.confirm, self.vanish_frames, self.vanish_bonus = threshold, confirm_frames, vanish_frames, vanish_bonus
        self.return_penalty, self.cap, self.born_bonus = return_penalty, cap, born_bonus
        self.dedupe_frames, self.dedupe_dist = max(1, int(dedupe_seconds * fps)), dedupe_dist
        self.recent = []  # 最近数えた (フレーム番号, 向き, 点)。追跡 ID が付け替わった同じ人を、2 回数えないため
        self.tick = 0
        self.exit_all = bool(exit_all)  # True なら、扉から出てきた人でなくても、確定待ちの人が、同じ向きに入口のそばを出たら、待たずに確定する
        self.tracks = {}

    # ---- 幾何 ----
    def _along(self, pt):
        return float(np.dot(np.asarray(pt, float) - self.a, self.u))

    def _span(self, pt, h):
        return -0.3 * h <= self._along(pt) <= self.length + 0.3 * h

    def _inside(self, pt):
        """画面の端（4%）の内側か。端で見え始めた人は、扉から出てきたのではなく、画面に入ってきただけ。"""
        if self.frame is None:
            return True
        w, h = self.frame
        return 0.04 * w <= pt[0] <= 0.96 * w and 0.04 * h <= pt[1] <= 0.96 * h

    def _zone(self, pt, d, h):
        return abs(d) <= self.zone * h and self._span(pt, h)

    # ---- 画面に出す用 ----
    def info(self, tid):
        """(向き, スコア, 線のそばか, 数えた向き)。向き＝スコアの符号。"""
        st = self.tracks.get(int(tid))
        if st is None:
            return None
        return (int(np.sign(st.score)), round(float(abs(st.score)), 1), bool(st.inz), int(st.counted))

    def vector(self, tid):
        st = self.tracks.get(int(tid))
        return None if st is None or st.vec is None else st.vec

    # ---- 更新 ----
    def _heading(self, st):
        """軌跡から、向き（px/秒）と、確かさ（0〜1）を出す。点が 2 つ未満なら None。"""
        pts = [p for p, _, _ in st.pts]
        if len(pts) < 2:
            return None, 0.0
        vs, ws = [], []
        for k in range(1, len(pts)):
            vs.append((pts[-1] - pts[-1 - k]) / (k * self.dt))
            ws.append(float(k))  # 遠い点からのベクトルほど、重く
        mean = sum(w * v for w, v in zip(ws, vs)) / sum(ws)
        nm = float(np.hypot(*mean))
        if nm < 1e-6:
            return mean, 0.0
        cos = [float(np.dot(v, mean) / (np.hypot(*v) * nm)) if np.hypot(*v) > 1e-6 else 0.0 for v in vs]
        conf = max(0.0, sum(w * c for w, c in zip(ws, cos)) / sum(ws))
        return mean, conf

    def update(self, ids, points, heights):
        """1 フレーム。いま追跡できている人の、足元の点と枠の高さを渡す。数える人がいれば [(方向, 追跡ID, 点)] を返す。"""
        self.tick += 1
        out, seen = [], set()
        for tid, pt, h in zip(ids, points, heights):
            tid = int(tid)
            seen.add(tid)
            pt = np.asarray(pt, float)
            d = float(np.dot(pt - self.a, self.n))
            st = self.tracks.get(tid)
            if st is None:
                st = self.tracks[tid] = _State(self.window)
                # 線のすぐそばで見え始めた（画面の端ではない）：扉から出てきた人。履歴が無く、スコアが 0 から始まるので、あとで、初期のスコアを加える
                st.born_near = abs(d) <= self.reach * h and self._span(pt, h) and self._inside(pt)
            prev = st.pts[-1] if st.pts else None
            if st.absent > 0 and st.bonus and st.score != 0 and prev is not None:
                # 戻ってきた：消えたことで加えたスコアは、逆向きに動き出したら、取り消す
                st.pts.append((pt, d, h))
                vec, _ = self._heading(st)
                if vec is not None and np.sign(float(np.dot(vec, self.n))) == -np.sign(st.score):
                    st.score -= np.sign(st.score) * self.return_penalty
                st.bonus = False
                st.pts.pop()
            st.absent = 0
            st.pts.append((pt, d, h))
            st.cross_age += 1
            st.last_pt, st.last_h, st.last_d = pt, h, d
            st.inz = self._zone(pt, d, h)
            vec, conf = self._heading(st)
            st.vec, st.conf = vec, conf

            if not st.inz:
                # 扉から出てきた人（線のそばで見え始めた人）が、同じ向きに進み続けて、入口のそばを出ていった：待たずに、ここで確定する
                # （足早に歩き去る人は、待っている間に、そばを離れてしまうため）。線のそばを、通り過ぎただけの人には、使わない
                sc = int(np.sign(st.score))
                if ((st.born_near or self.exit_all) and st.pending is not None and vec is not None and sc != 0 and st.counted != sc
                        and abs(st.score) >= self.threshold
                        and int(np.sign(float(np.dot(vec, self.n)))) == sc):
                    st.counted, st.pending = sc, None
                    out.append(("in" if sc > 0 else "out", tid, pt))
                st.away += 1
                st.score *= 0.5
                if abs(st.score) < 0.5:
                    st.score = 0.0
                if st.away >= 3:
                    st.counted, st.min_d, st.suspect = 0, 1e9, False
                st.pending = None if abs(st.score) < self.threshold else st.pending
                continue
            st.away = 0
            st.min_d = min(st.min_d, abs(d))

            # 1. 線をまたいだ（座標で分かる）
            if prev is not None and prev[1] * d < 0 and self._span(pt, h):
                cdir = 1 if d > prev[1] else -1
                heading_dir = 0 if vec is None else int(np.sign(float(np.dot(vec, self.n))))
                if heading_dir in (0, cdir):
                    st.score += cdir * self.cross_w
                else:
                    st.suspect = True  # 疑い：進む向きと、食い違う。加えない
                if st.last_cross == -cdir and st.cross_age <= self.flip_frames:
                    st.score += cdir * 1.0  # 反対向きに、またぎ返した：さらに、打ち消す
                st.last_cross, st.cross_age = cdir, 0

            # 2. 軌跡の向き
            if vec is not None:
                vn = float(np.dot(vec, self.n)) / max(h, 1.0)  # 枠の高さ/秒。プラスが IN の向き
                p0 = st.pts[0][0]
                win_disp = float(np.dot(pt - p0, self.n)) / max(h, 1.0)  # 窓の中で、線に対して進んだ量（枠の高さ）
                s = 1 if vn > 0 else -1
                if abs(vn) >= self.v_min and abs(win_disp) >= self.min_win and conf >= self.c_min and np.sign(win_disp) == s:
                    same = st.score == 0 or np.sign(st.score) == s
                    st.score += s * (1.0 if same else 2.0)  # 逆向きは、2 倍の重さ（引き返し）
                    if st.born_near and not st.born_done:  # 扉から出てきた人が、線から離れていく向きに、動き出した：初期のスコアを加える
                        st.born_done = True
                        st.score += s * self.born_bonus
                else:
                    st.score *= 0.5  # 立ち止まり・ぶれ・向きが定まらない
                    if abs(st.score) < 0.5:
                        st.score = 0.0
            st.score = float(np.clip(st.score, -self.cap, self.cap))
            self._decide(tid, st, out)

        # 消えた人
        for tid in [t for t in self.tracks if t not in seen]:
            st = self.tracks[tid]
            st.absent += 1
            # すでに数えた人（またいだ・向きで確定したなど）は、消えたことでは、もう数えない（1 人を 2 回数えないため）
            if (st.absent == self.vanish_frames and not st.bonus and st.counted == 0 and st.score != 0 and st.last_pt is not None
                    and st.min_d <= self.reach * st.last_h and np.sign(st.score) * st.last_d >= -self.reach * st.last_h
                    and self._zone(st.last_pt, st.last_d, st.last_h)):
                st.bonus = True  # 線の後ろで消えた：スコアに加える。待たずに、判定する
                st.score = float(np.clip(st.score + np.sign(st.score) * self.vanish_bonus, -self.cap, self.cap))
                self._decide(tid, st, out, wait=False)
            if st.absent >= 8:
                del self.tracks[tid]
        return self._dedupe(out)

    def _dedupe(self, out):
        """同じ向きで、すぐ近く・すぐあとの数えは、同じ人（追跡 ID の付け替わり）とみて、1 回にする。
        検出の頻度が低いと、線の上で一瞬止まっただけで、追跡が切れて、新しい ID が付き、またぎと消えるの両方で、数えられることがある。"""
        self.recent = [r for r in self.recent if self.tick - r[0] <= self.dedupe_frames]
        kept = []
        for direction, tid, pt in out:
            h = max(self.tracks[tid].last_h or 1.0, 1.0) if tid in self.tracks else 1.0
            if any(r[1] == direction and float(np.hypot(*(np.asarray(pt, float) - r[2]))) <= self.dedupe_dist * h for r in self.recent):
                continue
            self.recent.append((self.tick, direction, np.asarray(pt, float)))
            kept.append((direction, tid, pt))
        return kept

    def _decide(self, tid, st, out, wait=True):
        """スコアが閾値に届いたら、確定待ちにする。待つ間、保たれたら、数える（待たないときは、すぐ数える）。"""
        s = int(np.sign(st.score))
        near = st.min_d <= self.reach * (st.last_h or 1.0)
        if s == 0 or st.counted == s or not near:
            st.pending = None
            return
        if abs(st.score) < self.threshold:
            if st.pending is not None and abs(st.score) < self.threshold * 0.75:
                st.pending = None  # 確定待ちの間に、スコアが下がった：取り消し
            return
        if not wait:
            st.counted, st.pending = s, None
            out.append(("in" if s > 0 else "out", tid, st.last_pt))
            return
        if st.pending is None:
            st.pending = self.confirm
        st.pending -= 1
        if st.pending <= 0:
            st.counted, st.pending = s, None
            out.append(("in" if s > 0 else "out", tid, st.last_pt))
