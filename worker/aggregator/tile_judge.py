"""③ 判定：線の両側に並べたタイルを、人の足元が「踏んだ列の並び」だけで、IN/OUT を決める（ベクトル・速度・スコアは使わない）。

タイル（線 1 本につき、片側 rows 列。いつもは 3 列）
     ┌────┬────┬────┬────┐
     │ 遠く（列3）        │   ← ここまで来たら「扉から離れた」と言い切れる
     ├────┼────┼────┼────┤
     │ 近く（列2）        │
     ├────┼────┼────┼────┤
     │ 扉の前（列1）      │
     └────┴────┴────┴────┘
     ･････ すき間 ･････      ← 線のすぐそばは、タイルなし（足元のぶれで、反対側を踏まないように）
    ━━━━━━━ 線 ━━━━━━━
     ･････ すき間 ･････
     （反対側にも、同じく 3 列）

数える決まり（人ごと・線ごと）
  1. 越えた：片側のタイルを踏んだ人が、反対側のタイルを踏んだ → 踏んだ側へ通過（IN 側なら IN）。
     ただし、越えた先が「扉の前」の列のうちは、仮の通過。越えた側の「近く」まで進む・消える・扉の前に hold_seconds いる、のどれかで確定する。
     仮のまま、元の側へ引き返したら、どちらも数えない（線の上の足元のぶれ・うろうろ）。
  2. 扉に入った：「近く → 扉の前」と来て、vanish_seconds 見えなくなった → 反対側へ通過（扉の中は写らないので、消えたことが証拠）。
  3. 扉から出た：扉のそば（born_row 列目まで）で初めて見えた人が、そのあと、初めて見えた列より遠く、appear_row 列目以上まで離れた
     → 反対側から来た通過（離れてから数えるので、扉の前で立っていただけの人は、数えない）。
守りの決まり
  B. 同じ人の、同じ向きの通過は、線が違っても、same_seconds 秒に 1 回だけ数える（線を 2 本、近くに引いて、タイルが重なっても、1 人を 2 回数えない）。
  A. 枠が、直前のコマの shrink 倍未満に、上の端をほぼ動かさずに下から縮んだコマ（足元が隠れたかもしれない）で越えたときは、
     仮の通過にして、そのまま消えたときだけ確定する（隠れが解けて、元の側に戻ったら取り消し）。
     手前の人に足元を隠されると、足元の点が線の奥へ跳ぶため。扉へ入っていく人も、高い位置から見ると、下から縮んで見えるので、捨てはしない。
"""

import numpy as np

from common.tiling import line_to_px


class LineTiles:
    """線 1 本ぶんのタイル。座標は画素。"""

    def __init__(self, start, end, cols=4, rows=3, depth=0.06, gap=0.02, extend=0.25, unit=None):
        self.a = np.array(start, float)
        v = np.array(end, float) - self.a
        self.length = float(np.hypot(*v)) or 1.0
        self.u = v / self.length  # 線に沿う向き
        self.n = np.array([v[1], -v[0]]) / self.length  # IN 側の向き
        self.cols, self.rows = int(cols), int(rows)
        # 奥行き・すき間は、unit（画素。ふつうは画面の高さ）に対する割合。線の長さで決めると、長い線ではタイルが画面を覆ってしまう
        unit = unit or self.length
        self.depth, self.gap = depth * unit, gap * unit  # 画素
        self.lo, self.hi = -extend * self.length, (1 + extend) * self.length  # 線に沿う範囲（両端から extend × 線の長さ 外まで）

    def tile_of(self, pt):
        """足元の点が踏んでいるタイル (側, 列, 枚目) を返す。側は IN 側 +1・OUT 側 -1、列は 0＝扉の前。どのタイルでもなければ None。"""
        d = np.asarray(pt, float) - self.a
        along, across = float(d @ self.u), float(d @ self.n)
        if not self.lo <= along <= self.hi or abs(across) < self.gap:
            return None
        row = int((abs(across) - self.gap) // self.depth)
        if row >= self.rows:
            return None
        return (1 if across > 0 else -1, row, min(int((along - self.lo) / (self.hi - self.lo) * self.cols), self.cols - 1))

    def near(self, pt):
        """線のそば（すき間か「扉の前」の列。線の範囲の中）か。"""
        d = np.asarray(pt, float) - self.a
        along, across = float(d @ self.u), float(d @ self.n)
        return self.lo <= along <= self.hi and abs(across) < self.gap + self.depth

    def corners(self, side, row, col):
        """タイル 1 枚の 4 隅（画像に描く用）。"""
        s0, s1 = self.gap + row * self.depth, self.gap + (row + 1) * self.depth
        span = self.hi - self.lo
        t0, t1 = self.lo + span * col / self.cols, self.lo + span * (col + 1) / self.cols
        return [self.a + self.u * t + self.n * side * s for t, s in ((t0, s0), (t1, s0), (t1, s1), (t0, s1))]


def foot_point(x1, y1, x2, y2):
    """足元の点（枠の下の中央）。"""
    return (x1 + x2) / 2, y2


class _Step:
    """人 1 人・線 1 本ぶんの、踏んだタイルの記憶。"""
    __slots__ = ("side", "row", "near", "born_front", "pt", "tent", "hidden", "prev")

    def __init__(self, side, row, born_front, pt):  # born_front：線のそばで初めて見えた人（扉から出てきたかもしれない）
        self.side, self.row = side, row  # 最後に踏んだタイルの側・列
        self.near = row >= 1  # この側で「近く」以上を踏んだ（扉へ向かってきた）
        self.born_front = born_front  # 扉のそばで初めて見えた列（-1＝すき間）。まだ反対側を踏んでいない。None＝扉のそばで現れた人ではない
        self.pt = pt  # 最後に踏んだ足元の点
        self.tent = None  # 仮の通過 (経過秒, 側, 点, 元の側)（決まり 1 の、扉の前で止まっている間）
        self.hidden = False  # 仮の通過が、下から縮んだ枠で越えたもの（消えたときだけ確定する）
        self.prev = None  # 仮の通過の前の記憶（引き返したら、これに戻す）


class TileJudge:
    """端末 1 台ぶんの判定。"""

    def __init__(self, lines, frame_w, frame_h, cols=4, rows=3, depth=0.06, gap=0.02, extend=0.25,
                 vanish_seconds=0.4, shrink=0.7, shrink_top=0.1, hidden_vanish=True, same_seconds=2.0, appear_row=1, born_row=0, hold_seconds=2.0, forget_seconds=10.0, **_ignored):
        """lines は [{"id", "name", "line": [[x1,y1],[x2,y2]]}, ...]（座標は画面に対する割合）。"""
        self.names = [item["name"] for item in lines]
        self.tiles = [LineTiles(*line_to_px(item["line"], frame_w, frame_h), cols, rows, depth, gap, extend, frame_h) for item in lines]
        self.appear_row = min(int(appear_row), int(rows) - 1)  # 決まり 3：扉の前で現れた人が、ここまで離れたら数える列
        self.born_row = int(born_row)
        self.hidden_vanish = hidden_vanish
        self.same_seconds = same_seconds  # 守り B
        self.last_dir = {}  # 人ID → {向き: 最後に数えた経過秒}  # 守り A：足元が隠れた枠で越えた仮の通過を、消えたときに確定するか  # 決まり 3：この列までで初めて見えた人を、扉から出てきたかもしれない人とする
        self.frame_size = (frame_w, frame_h)
        self.vanish_seconds, self.shrink, self.shrink_top = vanish_seconds, shrink, shrink_top
        self.hold_seconds, self.forget_seconds = hold_seconds, forget_seconds
        self.steps = {}  # (人ID, 線の番号) → _Step
        self.seen = {}  # 人ID → 最後に見えた時刻
        self.ref_h = {}  # 人ID → (使ったコマの枠の高さ, 続けて縮んでいたコマ数, 時刻, 上の端)
        self.born_near = {}  # (人ID, 線の番号) → 扉のそばで初めて見えた列（-1＝すき間）。そうでなければ None
        self.t0 = None
        self.rel = 0.0
        self.events = []  # 確定した通過：(経過秒, "in"/"out", 人ID, 足元x, 足元y, 線の名前)
        self.debug = []  # 画面に出す用

    # ---- 守り ----
    def _shrunk(self, tid, top, h):
        """守り A：枠が、直前のコマ（0.5 秒以内）より、上の端をほぼ動かさずに、下から急に縮んだコマか（足元が隠れた）。"""
        ref = self.ref_h.get(tid)
        if (ref is not None and self.rel - ref[2] <= 0.5 and h < self.shrink * ref[0] and ref[1] < 3
                and (self.shrink_top <= 0 or abs(top - ref[3]) <= self.shrink_top * ref[0])):
            self.ref_h[tid] = (ref[0], ref[1] + 1, self.rel, ref[3])
            return True
        self.ref_h[tid] = (h, 0, self.rel, top)
        return False

    def _cross(self, new, side, tid, pt, name, at=None):
        """通過を確定して、数える。at は、越えた時刻（仮の通過を確定するとき）。"""
        at = self.rel if at is None else at
        d = "in" if side > 0 else "out"
        last = self.last_dir.setdefault(tid, {})
        if self.same_seconds > 0 and abs(at - last.get(d, -1e9)) <= self.same_seconds:
            return  # 守り B：同じ人・同じ向きを、別の線でも数えない
        last[d] = at
        new.append((at, d, tid, float(pt[0]), float(pt[1]), name))

    def _commit(self, new, st, tid, name):
        """仮の通過を確定する。"""
        at, side, pt, _orig = st.tent
        st.tent = None
        self._cross(new, side, tid, pt, name, at)

    # ---- 1 フレーム ----
    def update(self, t, tracks):
        """1 フレームの追跡の結果 tracks = [[人ID, x1, y1, x2, y2, スコア], ...] を渡す。このフレームで確定した通過のリストを返す。"""
        if self.t0 is None:
            self.t0 = t
        self.rel = rel = t - self.t0
        self.debug, new = [], []
        w, h = self.frame_size
        for tid, x1, y1, x2, y2, _score in tracks:
            tid = int(tid)
            first = tid not in self.seen  # この人を、初めて見た
            self.seen[tid] = rel
            x, y = foot_point(x1, y1, x2, y2)
            if first:
                for k, tiles in enumerate(self.tiles):
                    tl = tiles.tile_of((x, y))
                    self.born_near[(tid, k)] = (-1 if tiles.near((x, y)) and tl is None else
                                                tl[1] if tl is not None and tl[1] <= self.born_row else None)
            hidden = self._shrunk(tid, y1, y2 - y1)  # 守り A：足元が隠れたかもしれない枠
            shown = []
            for k, (name, tiles) in enumerate(zip(self.names, self.tiles)):
                tile = tiles.tile_of((x, y))
                if tile is None:
                    continue
                side, row = tile[0], tile[1]
                st = self.steps.get((tid, k))
                if st is None:
                    if not hidden:
                        self.steps[(tid, k)] = _Step(side, row, self.born_near.get((tid, k)), (x, y))
                elif side != st.side:
                    if st.tent is not None and side == st.tent[3]:  # 仮の通過のまま、元の側へ引き返した：どちらも数えない（前の記憶に戻す）
                        old = self.steps[(tid, k)] = st.prev
                        old.row, old.pt = row, (x, y)
                    else:  # 決まり 1：反対側のタイルを踏んだ
                        nst = self.steps[(tid, k)] = _Step(side, row, None, (x, y))
                        nst.tent, nst.hidden, nst.prev = (rel, side, (x, y), st.side), hidden, st
                        if row >= 1 and not hidden:  # いきなり「近く」以上：すぐ確定
                            self._commit(new, nst, tid, name)
                elif hidden:
                    pass  # 足元が隠れたかもしれない枠では、確定も、列の記憶の更新もしない
                else:
                    if st.tent is not None and (row >= 1 or rel - st.tent[0] >= self.hold_seconds):
                        self._commit(new, st, tid, name)  # 越えた側の「近く」まで進んだ／扉の前に留まった：確定
                    if st.born_front is not None and row >= self.appear_row and row > st.born_front:  # 決まり 3：扉のそばで現れて、離れていった
                        self._cross(new, side, tid, (x, y), name)
                        st.born_front = None
                    st.near = st.near or row >= 1
                    st.row, st.pt = row, (x, y)
                shown.append([name, side, float(row), True, 0])
            # 画面用：[ID, 足元x, 足元y, 動きx, 動きy, 速さ, [[線の名前, 踏んでいる側, 列, 線のそばか, 数えた向き], ...]]（動きは使わないので 0）
            self.debug.append([tid, round(x / w, 4), round(y / h, 4), 0.0, 0.0, 0.0, shown])

        # 決まり 2：「近く → 扉の前」と来て、見えなくなった人は、扉に入った
        for (tid, k), st in list(self.steps.items()):
            if rel - self.seen.get(tid, rel) <= self.vanish_seconds:
                continue
            if st.tent is not None:  # 越えて、そのまま消えた：仮の通過を確定
                if self.hidden_vanish or not st.hidden:
                    self._commit(new, st, tid, self.names[k])
            elif st.row == 0 and st.near:
                self._cross(new, -st.side, tid, st.pt, self.names[k])
            del self.steps[(tid, k)]
        for tid in [i for i, s in self.seen.items() if rel - s > self.forget_seconds]:
            del self.seen[tid]
            self.ref_h.pop(tid, None)
            self.last_dir.pop(tid, None)
            for k in range(len(self.tiles)):
                self.born_near.pop((tid, k), None)

        self.events.extend(new)
        return new
