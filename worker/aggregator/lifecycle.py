"""人の状態管理：人（追跡 ID）ごとに、状態を持ち、判定に渡す座標を作る。

  starting（見え始め）─▶ moving（動いている）─▶ deleted（消えた）

  starting：見え始めてから、watch_frames フレームたまるまで、判定に渡さない。たまったら、見え始める前の位置を、動きから、
            backfill_frames フレームぶん予想して足し、座標のリストとして、一括で渡す（予想した前の位置と、実際の位置）。
  moving  ：座標を 1 つずつ、毎フレーム渡す。
  deleted ：見えなくなって、つなぎの猶予（stitch_seconds）が過ぎたら、消えたとする。直前の動きから、predict_frames フレーム先の位置を、
            予想して、座標のリストとして、一括で渡す。
  つなぎ  ：見えなくなった人の近くに、すぐあとで、別の ID が見え始めたら、同じ人とみなして、moving のまま続ける（deleted を出さない）。

画像は見ない。追跡の結果（枠）だけで動く。判定（judge.py）は、渡された座標だけで、線を越えたかを決める。
座標は [x, y, 枠の高さ, 予想か（0＝実際、1＝予想）]。
"""

from collections import deque

import numpy as np


class _Person:
    __slots__ = ("pid", "state", "buf", "recent", "absent", "last")

    def __init__(self, pid):
        self.pid = pid
        self.state = "starting"
        self.buf = []  # starting のあいだに、たまった実際の座標
        self.recent = deque(maxlen=4)  # 直近の実際の座標（予想に使う）
        self.absent = 0
        self.last = None


def _velocity(pts):
    """座標の並び（[x, y, h, ...]）の、1 フレームあたりの動き。2 点未満なら None。"""
    if len(pts) < 2:
        return None
    k = len(pts) - 1
    return ((pts[-1][0] - pts[0][0]) / k, (pts[-1][1] - pts[0][1]) / k)


class Lifecycle:
    def __init__(self, fps, frame=None, watch_frames=3, backfill_frames=5, predict_frames=2, vanish_frames=2,
                 stitch_seconds=0.7, stitch_dist=1.0, bottom_margin=0.04, inside_margin=0.04, backfill_max=1.0, **_ignored):
        self.frame = frame
        self.watch_frames, self.backfill_frames, self.predict_frames = max(2, int(watch_frames)), int(backfill_frames), int(predict_frames)
        self.vanish_frames = int(vanish_frames)
        self.stitch_frames = max(1, int(round(stitch_seconds * fps)))
        self.stitch_dist = stitch_dist
        self.bottom_margin, self.inside_margin = bottom_margin, inside_margin
        self.backfill_max = backfill_max  # 見え始める前へ、予想する距離の上限（枠の高さ比）。遠くまで予想すると、線から遠い人の、でたらめな予想が、線をまたぐ
        self.people = {}  # 人 ID → _Person
        self.alias = {}  # 追跡 ID → 人 ID（つないだ人だけ）

    def _inside(self, x, y):
        """画面の端（左右・上下）の内側か。端で見え始めた人は、扉から出てきたのではなく、画面に入ってきただけ。"""
        if self.frame is None:
            return True
        w, h = self.frame
        m = self.inside_margin
        return m * w <= x <= (1 - m) * w and m * h <= y <= (1 - m) * h

    def _starting_batch(self, p):
        """見え始め：予想した前の位置 ＋ 実際の位置。端で見え始めた人は、予想を足さない。"""
        first = p.buf[0]
        pts = []
        v = _velocity(p.buf)
        if v is not None and self.backfill_frames > 0 and self._inside(first[0], first[1]):
            n = self.backfill_frames
            span = float(np.hypot(v[0], v[1])) * n / first[2]  # 予想する距離（枠の高さ比）
            if span > self.backfill_max:
                n = max(1, int(n * self.backfill_max / span))  # 上限を超えるときは、予想するフレーム数を減らす
            for i in range(n, 0, -1):
                pts.append([first[0] - v[0] * i, first[1] - v[1] * i, first[2], 1])
        pts.extend([x, y, h, 0] for x, y, h in p.buf)
        return pts

    def _deleted_batch(self, p):
        """消えた：直前の動きから、先の位置を予想する。画面の下の端で消えた人は、手前へ歩き去っただけなので、予想しない。"""
        if p.last is None or self.predict_frames <= 0:
            return []
        x, y, h = p.last
        if self.frame is not None and y > (1 - self.bottom_margin) * self.frame[1]:
            return []
        v = _velocity(list(p.recent)[-3:])
        if v is None:
            return []
        return [[x + v[0] * i, y + v[1] * i, h, 1] for i in range(1, self.predict_frames + 1)]

    def _find_dying(self, x, y, h):
        """見えなくなって、つなぎを待っている人のうち、いちばん近い人。"""
        best, bd = None, 1e9
        for p in self.people.values():
            if p.absent < self.vanish_frames or p.last is None:
                continue
            d = float(np.hypot(x - p.last[0], y - p.last[1])) / max(h, 1.0)
            if d <= self.stitch_dist and d < bd:
                best, bd = p, d
        return best

    def update(self, tracks):
        """1 フレームの追跡の結果 tracks = [[追跡ID, x1, y1, x2, y2, スコア], ...] を渡す。
        判定に渡すもの [(人ID, 状態, 座標のリスト), ...] と、このフレームの追跡ID → 人ID（つないだ人だけ）を返す。"""
        events, seen, alias_now = [], set(), {}
        for tr in tracks:
            tid = int(tr[0])
            x, y, h = (tr[1] + tr[3]) / 2, float(tr[4]), max(float(tr[4] - tr[2]), 1.0)
            pid = self.alias.get(tid, tid)
            p = self.people.get(pid)
            if p is None:
                d = self._find_dying(x, y, h)
                if d is not None:  # 近くで見えなくなった人と、同じ人：つなぐ
                    pid, p = d.pid, d
                    self.alias[tid] = pid
                else:
                    p = self.people[pid] = _Person(pid)
            if pid != tid:
                alias_now[tid] = pid
            seen.add(pid)
            p.absent = 0
            p.last = (x, y, h)
            p.recent.append((x, y, h))
            if p.state == "starting":
                p.buf.append((x, y, h))
                if len(p.buf) >= self.watch_frames:
                    events.append((pid, "starting", self._starting_batch(p)))
                    p.state, p.buf = "moving", []
            else:
                events.append((pid, "moving", [[x, y, h, 0]]))
        for pid in [q for q in self.people if q not in seen]:
            p = self.people[pid]
            p.absent += 1
            if p.absent >= self.vanish_frames + self.stitch_frames:  # つなぎ先が現れないまま、猶予が過ぎた：消えた
                if p.state == "moving":
                    events.append((pid, "deleted", self._deleted_batch(p)))
                del self.people[pid]
                for t in [t for t, q in self.alias.items() if q == pid]:
                    del self.alias[t]
        return events, alias_now
