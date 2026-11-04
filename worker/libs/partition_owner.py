"""キューの分割（frames:p0 … p{N-1}）を、動いている worker どうしで、自動で分け合う。

`docker compose up --scale worker=3` のように、worker を増やすだけで、分割が分かれる（分割ごとの設定は、要らない）。
  ・分割ごとに、Redis の鍵（partition_lock:{n}）を、1 つの worker だけが持つ（SET NX EX）。持っている間は、定期的に延長する
  ・動いている worker の数（ハートビート worker:* の数）から、1 台あたりの目標 = 切り上げ(分割数 / 台数) を決める
  ・目標より多く持っていたら、余りを手放す（新しい worker が、加わったとき）。足りなければ、空いている分割を取る
  ・worker が落ちたら、鍵が 10 秒で切れ、ほかの worker が引き継ぐ（未処理のフレームも、拾い直す）
同じ端末のフレームは、同じ分割に積まれる（backend が、端末ごとに分割を固定する）ので、追跡の状態は、1 台の worker にだけある。
"""

import math
import time

LOCK_TTL_S = 10  # 鍵の寿命。落ちた worker の分割は、この時間で、空く
ALIVE_S = 6  # ハートビートが、これより新しければ、動いているとみなす


def lock_key(p):
    return f"partition_lock:{p}"


class PartitionOwner:
    def __init__(self, rdb, name, total):
        self.r, self.name, self.total = rdb, name, total

    def _alive_workers(self):
        """動いている worker の数（自分を含む）。"""
        now_ms = time.time() * 1000
        n = 0
        for key in self.r.scan_iter("worker:*", count=100):
            ts = self.r.hget(key, "last_seen_ms")
            if ts is not None and now_ms - float(ts) < ALIVE_S * 1000:
                n += 1
        return max(1, n)

    def refresh(self):
        """持っている分割を延長し、目標に合わせて、手放す・取る。戻り値 = (持っている分割のリスト, 新しく取った分割)。"""
        target = math.ceil(self.total / self._alive_workers())
        mine = [p for p in range(self.total) if self._get(p) == self.name]
        for p in mine:
            self.r.expire(lock_key(p), LOCK_TTL_S)
        while len(mine) > target:  # 多すぎる：手放す（新しい worker に、譲る）
            self.r.delete(lock_key(mine.pop()))
        new = []
        for p in range(self.total):
            if len(mine) >= target:
                break
            if p not in mine and self.r.set(lock_key(p), self.name, nx=True, ex=LOCK_TTL_S):
                mine.append(p)
                new.append(p)
        return sorted(mine), new

    def release_all(self):
        """終了するとき、持っている分割を、すぐ手放す（ほかの worker が、すぐ引き継げる）。"""
        for p in range(self.total):
            if self._get(p) == self.name:
                self.r.delete(lock_key(p))

    def _get(self, p):
        v = self.r.get(lock_key(p))
        return v.decode() if v is not None else None
