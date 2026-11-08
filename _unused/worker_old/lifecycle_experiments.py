"""人の状態管理：人（追跡 ID）ごとに、状態を持ち、判定に渡す座標を作る。

  starting（見え始め）─▶ moving（動いている）─▶ deleted（消えた）

  starting：見え始めてから、watch_frames フレームたまるまで、判定に渡さない。たまったら、見え始める前の位置を、動きから、
            backfill_frames フレームぶん予想して足し、座標のリストとして、一括で渡す（予想した前の位置と、実際の位置）。
  moving  ：座標を 1 つずつ、毎フレーム渡す。
  deleted ：見えなくなって、つなぎの猶予（stitch_seconds）が過ぎたら、消えたとする。直前の動きから、predict_frames フレーム先の位置を、
            予想して、座標のリストとして、一括で渡す。
  つなぎ  ：見えなくなった人の近くに、すぐあとで、別の ID が見え始めたら、同じ人とみなして、moving のまま続ける（deleted を出さない）。

【平滑化】smooth > 0 なら、足元を、前後 smooth フレームの中央値で、ならしてから渡す（判定は smooth フレーム遅れる）。足元のぶれで、側が行き来するのを防ぐ。
【足元の推定】foot_model が true なら、下半身が隠れた枠の足元を、頭の位置から置き直す。
  全身が写った枠（縦横比 min_aspect 以上、画面の下の端に触れない）から、「枠の上端の y」と「背の高さ」の関係（直線）を、学び続ける。
  枠の高さが、期待の背の高さの trunc 倍より小さい（手前の人や物に、下半身が隠れている）ときは、足元 ＝ 上端 ＋ 期待の背の高さ とする。
  足元が隠れると、枠の下端が上にずれ、線の反対側にいるように見えるため。

画像は見ない。追跡の結果（枠）だけで動く。判定（judge.py）は、渡された座標だけで、線を越えたかを決める。
座標は [x, y, 枠の高さ, 予想か（0＝実際、1＝予想）]。
"""

from collections import deque

import numpy as np


class RowHeight:
    """画面の行（枠の上端の y）と、人の背の高さ（枠の高さ）の関係を、全身が写った枠から学ぶ。 背の高さ ≈ a × 上端の y + b"""

    def __init__(self, frame_h, min_aspect=2.2, min_samples=30):
        self.frame_h, self.min_aspect, self.min_samples = frame_h, min_aspect, min_samples
        self.samples = deque(maxlen=600)
        self.coef = None
        self._since = 0

    def observe(self, x1, y1, x2, y2):
        h, w = y2 - y1, max(x2 - x1, 1.0)
        if h / w < self.min_aspect or (self.frame_h and y2 >= 0.97 * self.frame_h):
            return  # 全身が写っていない枠（下が隠れている・画面の下の端で切れている）は、学ばない
        self.samples.append((y1, h))
        self._since += 1
        if len(self.samples) >= self.min_samples and (self.coef is None or self._since >= 20):
            self._fit()

    def _fit(self):
        a = np.asarray(self.samples, float)
        x = np.c_[a[:, 0], np.ones(len(a))]
        coef, *_ = np.linalg.lstsq(x, a[:, 1], rcond=None)
        for _ in range(3):  # 外れ値（座っている人、検出の誤り）を除いて、当てはめ直す
            r = np.abs(a[:, 1] - x @ coef)
            keep = r <= 2.5 * np.median(r) + 1e-6
            if keep.sum() < 10:
                break
            coef, *_ = np.linalg.lstsq(x[keep], a[keep, 1], rcond=None)
        self.coef, self._since = coef, 0

    def expected(self, y_top):
        """上端が y_top の人の、期待の背の高さ（ピクセル）。まだ学んでいなければ None。"""
        if self.coef is None:
            return None
        h = float(self.coef[0] * y_top + self.coef[1])
        return h if h > 1 else None


class _Person:
    __slots__ = ("pid", "state", "buf", "recent", "absent", "last", "raw", "sent")

    def __init__(self, pid):
        self.pid = pid
        self.state = "starting"
        self.buf = []  # starting のあいだに、たまった実際の座標
        self.recent = deque(maxlen=4)  # 直近の実際の座標（予想に使う）
        self.absent = 0
        self.last = None
        self.raw = []  # 実際の座標の履歴（平滑化用）
        self.sent = 0  # 判定に渡し終えた、raw の位置


def _velocity(pts):
    """座標の並び（[x, y, h, ...]）の、1 フレームあたりの動き。2 点未満なら None。"""
    if len(pts) < 2:
        return None
    k = len(pts) - 1
    return ((pts[-1][0] - pts[0][0]) / k, (pts[-1][1] - pts[0][1]) / k)


class Lifecycle:
    def __init__(self, fps, frame=None, watch_frames=3, backfill_frames=5, predict_frames=2, vanish_frames=2,
                 stitch_seconds=0.7, stitch_dist=1.0, bottom_margin=0.04, inside_margin=0.04, backfill_max=1.0,
                 foot_model=False, trunc=0.8, min_aspect=2.2, trunc_aspect=0.0, smooth=0, **_ignored):
        self.frame = frame
        self.watch_frames, self.backfill_frames, self.predict_frames = max(2, int(watch_frames)), int(backfill_frames), int(predict_frames)
        self.vanish_frames = int(vanish_frames)
        self.stitch_frames = max(1, int(round(stitch_seconds * fps)))
        self.stitch_dist = stitch_dist
        self.bottom_margin, self.inside_margin = bottom_margin, inside_margin
        self.backfill_max = backfill_max  # 見え始める前へ、予想する距離の上限（枠の高さ比）。遠くまで予想すると、線から遠い人の、でたらめな予想が、線をまたぐ
        self.rows = RowHeight(frame[1] if frame else 0, min_aspect) if foot_model else None  # 足元の推定（使わないなら None）
        self.trunc, self.trunc_aspect = trunc, trunc_aspect  # trunc_aspect > 0 なら、枠がずんぐり（高さ/幅がこれ未満）のときだけ、置き直す
        self.smooth = int(smooth)
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

    def _smoothed(self, p, upto):
        """raw の p.sent 〜 upto−1 番目を、前後 smooth 点の中央値で、ならして返す（判定に渡し終えた位置を進める）。"""
        out, k = [], self.smooth
        for i in range(p.sent, upto):
            win = p.raw[max(0, i - k): i + k + 1]
            out.append([float(np.median([q[0] for q in win])), float(np.median([q[1] for q in win])), float(np.median([q[2] for q in win])), 0])
        p.sent = max(p.sent, upto)
        return out

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
            if self.rows is not None:
                self.rows.observe(*tr[1:5])
                he = self.rows.expected(float(tr[2]))
                squat = self.trunc_aspect <= 0 or h / max(float(tr[3] - tr[1]), 1.0) < self.trunc_aspect
                if he is not None and h < self.trunc * he and squat:  # 下半身が隠れている：頭の位置 ＋ 期待の背の高さ を、足元にする
                    y, h = float(tr[2]) + he, he
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
            p.raw.append((x, y, h))
            if p.state == "starting":
                p.buf.append((x, y, h))
                if len(p.buf) >= self.watch_frames:
                    batch = self._starting_batch(p)
                    if self.smooth > 0:  # 予想した前の位置 ＋ ならした実際の位置（最後の smooth 点は、次のフレームまで待つ）
                        batch = [q for q in batch if q[3]] + self._smoothed(p, len(p.raw) - self.smooth)
                    else:
                        p.sent = len(p.raw)
                    events.append((pid, "starting", batch))
                    p.state, p.buf = "moving", []
            elif self.smooth > 0:
                pts = self._smoothed(p, len(p.raw) - self.smooth)
                if pts:
                    events.append((pid, "moving", pts))
            else:
                p.sent = len(p.raw)
                events.append((pid, "moving", [[x, y, h, 0]]))
        for pid in [q for q in self.people if q not in seen]:
            p = self.people[pid]
            p.absent += 1
            if p.absent >= self.vanish_frames + self.stitch_frames:  # つなぎ先が現れないまま、猶予が過ぎた：消えた
                if p.state == "moving":
                    rest = self._smoothed(p, len(p.raw)) if self.smooth > 0 else []  # まだ渡していない、最後の点
                    events.append((pid, "deleted", rest + self._deleted_batch(p)))
                del self.people[pid]
                for t in [t for t, q in self.alias.items() if q == pid]:
                    del self.alias[t]
        return events, alias_now
