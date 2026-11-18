"""② 追跡：検出の枠に、人ごとの ID を付ける。距離だけで決める（速度の予想・見た目・人の状態管理は、使わない）。

1 フレームごとに、次の 3 つだけを行う。
  1. 前のフレームまでの人（最後に見えた枠）と、今回の枠の、中心どうしの距離を測る（その人の枠の高さで割る）。
  2. 距離の近い組から順に、同じ人とみなす（max_dist 倍より遠い組は、つながない）。
  3. 残った枠のうち、スコアが min_score 以上のものは、新しい人とする。lost_seconds 見えなかった人は、忘れる。
"""

import numpy as np


class SimpleTracker:
    def __init__(self, max_dist=0.8, lost_seconds=1.0, min_score=0.25, **_ignored):
        self.max_dist = max_dist  # 同じ人とみなす距離の上限（枠の高さの何倍か）
        self.lost_seconds = lost_seconds  # 見えなくなってから、同じ ID で待つ秒数
        self.min_score = min_score  # これより低いスコアの枠は、使わない
        self.people = {}  # ID → (最後に見えた枠 [x1, y1, x2, y2], 最後に見えた時刻)
        self.next_id = 0

    def update(self, boxes, scores, t):
        """boxes は [[x1, y1, x2, y2], ...]、scores は各枠のスコア、t は時刻（秒）。
        このフレームの [[ID, x1, y1, x2, y2, スコア], ...] を返す。"""
        self.people = {i: p for i, p in self.people.items() if t - p[1] <= self.lost_seconds}
        dets = [(np.asarray(b, float), float(s)) for b, s in zip(boxes, scores) if s >= self.min_score]

        # 1. 全部の組の距離（人の枠の中心どうし）
        pairs = []
        for pid, (pb, _) in self.people.items():
            pc, ph = (pb[:2] + pb[2:]) / 2, max(pb[3] - pb[1], 1.0)
            for j, (b, _) in enumerate(dets):
                d = float(np.hypot(*((b[:2] + b[2:]) / 2 - pc))) / ph
                if d <= self.max_dist:
                    pairs.append((d, pid, j))

        # 2. 近い組から順に、つなぐ
        out, used_p, used_d = [], set(), set()
        for d, pid, j in sorted(pairs):
            if pid in used_p or j in used_d:
                continue
            used_p.add(pid)
            used_d.add(j)
            self.people[pid] = (dets[j][0], t)
            out.append([pid, *dets[j][0].tolist(), dets[j][1]])

        # 3. 残った枠は、新しい人
        for j, (b, s) in enumerate(dets):
            if j in used_d:
                continue
            pid = self.next_id
            self.next_id += 1
            self.people[pid] = (b, t)
            out.append([pid, *b.tolist(), s])
        return out

