"""線のぎりぎりを通る人を数える補助（LineZone だけでは数えられない 2 つの場合）。

LineZone は、足元の点が線の「こちら側」から「あちら側」へ動いたのを見て数える。
入口の足元ぎりぎりに線を置くと、次のことが起きて、線をまたぐ瞬間が、映像に残らない。

  ① 出てくる人：暗いドアの中では検出できず、線のすぐ外へ出てから、初めて検出される（最初の点が、もう線の向こう側）
  ② 入る人    ：線に着く前後でドアの中に消え、検出が途切れる（最後の点が、まだ線の手前）

そこで、線の近く（人の枠の高さ × edge_margin の範囲）を「線の際」とみなし、次の場合も 1 回数える。
  ① 際で見え始めた人が、際の外へ出たら、出た側へ越えたことにする
  ② 際の外から線へ向かって動いていた人が、際の中で見えなくなったら、反対側へ越えたことにする
     ただし、見えなくなってから confirm_frames（1〜2 秒）は、確定を待つ。
       ・同じ人がまた見えれば、検出の取りこぼしだったので、何もしない
       ・別の追跡IDで、すぐ近くに現れたら、同じ人の続きとして引き継ぐ（IDが変わっただけ）
       ・そのまま現れなければ、本当に消えたとして、数える
LineZone が、すでにその人を数えていれば、数えない。
"""

from collections import deque

import numpy as np


class _Track:
    """1 人（追跡ID）の、1 本の線に対する履歴。"""
    __slots__ = ("born_near", "first_d", "last_d", "last_h", "last_pt", "absent", "n", "done", "hist")

    def __init__(self, d, h, pt, on_edge):
        self.born_near = on_edge  # 際で見え始めたか
        self.first_d, self.last_d, self.last_h, self.last_pt = d, d, h, pt
        self.absent, self.n, self.done = 0, 1, False
        self.hist = deque([d], maxlen=4)  # 直近の、線までの距離（動いているかの確認に使う）

    def approaching(self, h):
        """線へ向かって動いているか（直近の数フレームで、線までの距離が、枠の高さの 0.1 倍以上縮んだ）。"""
        return len(self.hist) >= 2 and abs(self.hist[0]) - abs(self.hist[-1]) >= 0.1 * h


class EdgeCrossing:
    """線 1 本ぶんの、際の判定。signed distance の向きは、画面の IN の矢印（始点→終点の左側）が、プラス。"""

    def __init__(self, start, end, margin, confirm_frames, frame=None):
        self.a = np.array(start, float)
        v = np.array(end, float) - self.a
        self.length = float(np.hypot(*v)) or 1.0
        self.u = v / self.length                                  # 線に沿った単位ベクトル
        self.n = np.array([v[1], -v[0]]) / self.length            # IN の向きの単位ベクトル
        self.margin, self.confirm_frames = margin, confirm_frames
        self.frame = frame  # (幅, 高さ) の px。画面の端で見え始めた人は、扉から出てきたのではなく、画面に入ってきただけ
        self.tracks = {}  # 追跡ID → _Track

    def _dist(self, pt):
        return float(np.dot(np.asarray(pt, float) - self.a, self.n))

    def _on_edge(self, pt, d, h):
        """点が、線の近く（線の長さの範囲の内側で、線から枠の高さ × margin 以内）にあるか。
        線の延長線上の遠い所（別の入口の前など）の人は、際とは見なさない。"""
        m = self.margin * h
        along = float(np.dot(np.asarray(pt, float) - self.a, self.u))
        return abs(d) <= m and -m <= along <= self.length + m

    def _inside_frame(self, pt):
        """画面の端（4%）の内側か。端で見え始めた人は、扉から出てきたのではなく、画面に入ってきただけなので、「際で見え始めた」とは見なさない。"""
        if self.frame is None:
            return True
        w, h = self.frame
        return 0.04 * w <= pt[0] <= 0.96 * w and 0.04 * h <= pt[1] <= 0.96 * h

    def _within_span(self, pt, h):
        """点が、線の長さの範囲（両端に、枠の高さ × margin の余裕）の内側にあるか。線からの距離は、問わない。"""
        m = self.margin * h
        along = float(np.dot(np.asarray(pt, float) - self.a, self.u))
        return -m <= along <= self.length + m

    def update(self, ids, points, heights, counted):
        """1 フレーム。ids/points/heights は、いま追跡できている人。counted は、LineZone が数えた追跡ID。
        数える人がいれば [(方向, 追跡ID, 点)] を返す。"""
        out, seen = [], set()
        for tid, pt, h in zip(ids, points, heights):
            tid, d = int(tid), self._dist(pt)
            seen.add(tid)
            tr = self.tracks.get(tid)
            if tr is None:
                tr = self.tracks[tid] = _Track(d, h, pt, self._on_edge(pt, d, h) and self._inside_frame(pt))
                self._take_over(tid, tr, pt, h)  # 見えなくなった人のすぐ近くに現れたら、その続きとして引き継ぐ
                continue
            tr.absent, tr.n = 0, tr.n + 1
            tr.last_d, tr.last_h, tr.last_pt = d, h, pt
            tr.hist.append(d)
            if tid in counted:
                tr.done = True
            if tr.done:
                continue
            if tr.born_near and abs(d) > self.margin * h and self._within_span(pt, h):
                # ① 際で見え始めた人が、際の外へ出た（出た場所も、線の長さの範囲の内側。線から離れて歩いたあとに、延長線を越えただけの人は、数えない）
                tr.done = True
                out.append(("in" if d > 0 else "out", tid, pt))
            elif (not tr.born_near and abs(tr.first_d) > self.margin * h and abs(d) > self.margin * h and d * tr.first_d < 0
                  and self._within_span(pt, h)):
                # 引き継いだ人が、最初と反対側へ出た（ID が変わって、LineZone では数えられなかった）。
                # 線の延長線の向こうへ回り込んだだけの人（線の長さの範囲の外）は、数えない（検証で、過検出の原因だった）
                tr.done = True
                out.append(("in" if d > 0 else "out", tid, pt))
        # ② 際の外から線へ向かっていた人が、際の中で見えなくなった。confirm_frames の間は、待つ
        for tid in [t for t in self.tracks if t not in seen]:
            tr = self.tracks[tid]
            tr.absent += 1
            if tr.absent < self.confirm_frames:
                continue
            if (not tr.done and tr.n >= 2 and not tr.born_near and tid not in counted
                    and self._on_edge(tr.last_pt, tr.last_d, tr.last_h)
                    and abs(tr.last_d) < abs(tr.first_d) and tr.approaching(tr.last_h)):
                out.append(("out" if tr.first_d > 0 else "in", tid, tr.last_pt))
            del self.tracks[tid]
        return out

    def _take_over(self, tid, tr, pt, h):
        """見えなくなって、確定を待っている人のすぐ近く（枠の高さ以内）に、新しい追跡が現れたら、同じ人の続きとする。"""
        for old_id, old in self.tracks.items():
            if old_id == tid or old.absent == 0 or old.done:
                continue
            if np.hypot(*(np.asarray(pt, float) - np.asarray(old.last_pt, float))) <= max(h, old.last_h):
                tr.first_d, tr.born_near, tr.n = old.first_d, old.born_near, old.n + 1
                tr.hist = deque(old.hist, maxlen=4)
                old.done = True  # 古いほうは、数えずに捨てる
                return
