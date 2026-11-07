"""判定：人の座標（lifecycle.py が作る）から、線を越えたか（IN/OUT）を決める。画像は見ない。2 次元の点と線の幾何だけ。

追跡（tracking.py）─▶ 人の状態管理（lifecycle.py）─▶ 【判定】─▶ 通過（どの線を、どちら向きに）

入力は、そのフレームで起きた、人ごとの出来事 events = [(人ID, 状態, 座標のリスト), ...]（lifecycle.py の出力。画面のピクセル座標）と、時刻（秒）。
線ごとに、判定の部品（EpisodeGate）を持つ。端末 1 台に Judge が 1 つ。
"""

from collections import deque

import numpy as np

from aggregator.episode_gate import EpisodeGate
from common.tiling import line_to_px

GATES = {"episode": EpisodeGate}  # 判定の方式（heading・segment は、使わなくなったので、_unused/worker_old/ に移した）


def foot_point(anchor, x1, y1, x2, y2):
    """画面に出す点。床の線に合わせるので、既定は足元（枠の下の中央）。"""
    if anchor == "top_center":
        return ((x1 + x2) / 2, y1)
    if anchor == "center":
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    return ((x1 + x2) / 2, y2)


class Judge:
    def __init__(self, lines, frame_w, frame_h, sample_fps, method="episode", params=None, anchor="bottom_center"):
        """lines は [{"id", "name", "line": [[x1,y1],[x2,y2]]}, ...]（座標は画面に対する割合）。method は episode か heading。"""
        if method not in GATES:
            raise ValueError(f"method は {list(GATES)} のどれか（{method} は使えない）")
        params = dict(params or {})
        # 同じ追跡 ID が、同じ向きで、続けて数えられるのを止める秒数（線をまたいで）。入口に 2 本の線を引くと、1 人が両方で OUT になるため
        self.same_id_seconds = float(params.pop("same_id_seconds", 5.0))
        self.anchor = anchor
        self.names, self.gates = [], []
        gate_cls = GATES[method]
        for item in lines:
            (x1, y1), (x2, y2) = line_to_px(item["line"], frame_w, frame_h)
            self.names.append(item["name"])
            self.gates.append(gate_cls((x1, y1), (x2, y2), sample_fps, (frame_w, frame_h), **params))
        self.frame_size = (frame_w, frame_h)
        self.t0 = None
        self.events = []  # 通過の記録：(経過秒, "in"/"out", 追跡ID, 判定点x, 判定点y, 線の名前)
        self.debug = []  # 画面に出す用：人ごとの、足元・動きのベクトル・線ごとのスコア
        self._last_dir = {}  # 人ID → (最後に数えた経過秒, 向き)
        self.tick = 0
        self._hist = {}  # 追跡ID → 直近の (経過秒, x, y)。画面に出すベクトルを、なめらかにするため

    def update(self, t, tracks, events=(), alias=None):
        """1 フレームを渡す。tracks は、そのフレームの追跡の結果 [[追跡ID, x1, y1, x2, y2, スコア], ...]（画面に出す用）、
        events は、lifecycle.py の出力 [(人ID, 状態, 座標のリスト), ...]、alias は、追跡ID → 人ID（つないだ人だけ）。
        このフレームで新しく起きた通過のリストを返す。"""
        if self.t0 is None:
            self.t0 = t
        rel = t - self.t0
        self.tick += 1
        new = []
        for pid, state, pts in events:
            for name, gate in zip(self.names, self.gates):
                for direction, p, (x, y) in gate.feed(int(pid), state, pts, self.tick):
                    last = self._last_dir.get(int(p))
                    if last and last[1] == direction and rel - last[0] <= self.same_id_seconds:
                        continue  # 同じ人が、別の線でも、同じ向きで数えられた：数えない（IN を取りこぼしていても、時間がたてば、また数える）
                    self._last_dir[int(p)] = (rel, direction)
                    new.append((rel, direction, int(p), float(x), float(y), name))
        self.events.extend(new)
        self._update_debug(rel, tracks, alias or {})
        return new

    def _update_debug(self, rel, tracks, alias):
        """画面に出す用の情報。人ごとに [追跡ID, x, y, vx, vy, 速さ, [[線の名前, 向き, スコア, 線のそばか, 数えたか], ...]]。
        x, y は画面に対する割合。vx, vy は 1 秒あたりの動き（画面に対する割合）、速さは、枠の高さ/秒。

        動きは、直近 4 点の、最初から最後までの動きで出す（1 つ前の点との差だけだと、見え始めに、枠が育つ（扉や人の陰から出てくる）だけで、
        足元が大きく動き、実際の動きでない矢印が飛び出す）。点が 3 つ（動きの区間が 2 つ）そろうまでは、動き 0 とする。"""
        self.debug = []
        w, h = self.frame_size
        seen = set()
        for tr in tracks:
            tid, box_h = int(tr[0]), float(tr[4] - tr[2])
            x, y = foot_point(self.anchor, *tr[1:5])
            pid = alias.get(tid, tid)  # つないだ人は、元の人 ID で、判定の状態を引く
            seen.add(tid)
            hist = self._hist.setdefault(tid, deque(maxlen=4))
            hist.append((rel, x, y))
            vx = vy = speed = 0.0
            vec = self.gates[0].vector(pid) if self.gates else None  # 判定が、なめらかな動きを持っていれば、それを使う
            if vec is not None:
                vx, vy = float(vec[0]), float(vec[1])
            elif len(hist) >= 3 and hist[-1][0] > hist[0][0]:
                dt = hist[-1][0] - hist[0][0]
                vx, vy = (hist[-1][1] - hist[0][1]) / dt, (hist[-1][2] - hist[0][2]) / dt  # px/秒
            speed = float(np.hypot(vx, vy)) / max(box_h, 1.0)
            lines = []
            for name, gate in zip(self.names, self.gates):
                inf = gate.info(pid)
                if inf:
                    lines.append([name, inf[0], inf[1], inf[2], inf[3]])
            self.debug.append([tid, round(x / w, 4), round(y / h, 4), round(vx / w, 4), round(vy / h, 4), round(speed, 2), lines])
        for tid in [t for t in self._hist if t not in seen]:
            del self._hist[tid]  # 見えなくなった人の履歴は、捨てる
