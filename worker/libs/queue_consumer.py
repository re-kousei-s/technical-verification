"""Redis Streams のキューからフレームを取り出して、処理に渡す。"""

import logging
import time

import redis

from common.live import GROUP, stream_name
from libs.partition_owner import PartitionOwner
from libs.settings import NAME, OWNED, PARTITIONS, STATIC_PARTITIONS

log = logging.getLogger("worker")


class QueueConsumer:
    def __init__(self, rdb, handler, heartbeat, stats):
        self.r = rdb
        self.handler = handler  # 1 エントリを処理する関数
        self.heartbeat = heartbeat  # 生きていることを知らせる関数
        self.stats = stats
        self._stop = False

    def stop(self, *_):
        """終了の合図（SIGTERM / SIGINT）。いま処理中のフレームを終えてから止まる。"""
        self._stop = True

    def _create_groups(self, streams):
        """コンシューマーグループを作る（無ければ。あれば何もしない）。"""
        for s in streams:
            try:
                self.r.xgroup_create(s, GROUP, id="0", mkstream=True)
            except redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise

    def _take_over(self, stream):
        """新しく担当する分割の、前の持ち主（落ちた worker など）が、処理中のまま残したフレームを、拾い直す。"""
        start = "0-0"
        while True:
            res = self.r.xautoclaim(stream, GROUP, NAME, min_idle_time=3000, start_id=start, count=50)
            next_id, msgs = res[0], res[1]
            for entry_id, fields in msgs:
                if fields:
                    self._process(stream, entry_id, fields)
            if not msgs or next_id in (b"0-0", "0-0"):
                return
            start = next_id

    def _update_partitions(self, owner, read_ids):
        """担当する分割を、更新する（自動のときだけ）。増えた分割は、グループを作って、未処理から読む。減った分割は、外す。"""
        if owner is None:
            return
        owned, new = owner.refresh()
        for p in new:
            s = stream_name(p)
            self._create_groups([s])
            self._take_over(s)
            read_ids[s] = "0"  # 前回 ACK していない分を、先に処理する
        for s in [s for s in read_ids if s not in [stream_name(p) for p in owned]]:
            del read_ids[s]  # 手放した分割は、読まない
        if owned != OWNED:
            log.info("担当する分割: %s → %s", OWNED, owned)
            OWNED[:] = owned

    def run(self):
        owner = None if STATIC_PARTITIONS else PartitionOwner(self.r, NAME, PARTITIONS)
        read_ids = {}  # 担当する分割ごとの、読む位置。起動直後は、前回 ACK していない分（"0"）を先に処理し、尽きたら新着（">"）だけを待つ
        if owner is None:
            streams = [stream_name(p) for p in OWNED]
            self._create_groups(streams)
            read_ids = {s: "0" for s in streams}
        last_heartbeat = last_owner = 0.0
        log.info("開始: worker=%s partitions=%s", NAME, OWNED or "（自動で分け合う）")

        while not self._stop:
            now = time.time()
            if now - last_heartbeat > 2:
                self.heartbeat()
                last_heartbeat = now
            if now - last_owner > 2:
                try:
                    self._update_partitions(owner, read_ids)
                except redis.ConnectionError:
                    log.warning("Redis に接続できない（再試行）")
                last_owner = now
            if not read_ids:  # まだ、担当する分割がない（worker が、分割数より多いとき）
                time.sleep(1)
                continue
            try:
                resp = self.r.xreadgroup(GROUP, NAME, dict(read_ids), count=4, block=1000)
            except redis.ConnectionError:
                log.warning("Redis に接続できない（再試行）")
                time.sleep(2)
                continue

            for stream, entries in resp:
                stream = stream.decode()
                if stream not in read_ids:
                    continue
                if not entries and read_ids[stream] != ">":
                    read_ids[stream] = ">"  # 未処理の分を読み終えた。ここからは新着だけ
                    continue
                for entry_id, fields in entries:
                    self._process(stream, entry_id, fields)

            if resp == [] and any(v != ">" for v in read_ids.values()):
                read_ids = {s: ">" for s in read_ids}

        if owner is not None:
            owner.release_all()  # 終わるとき、すぐ手放す

    def _process(self, stream, entry_id, fields):
        """1 エントリを処理し、終わったら ACK して消す。"""
        try:
            self.handler(fields)
        except Exception:
            # 1 フレームの失敗で止めない。やり直すと追跡の状態が二重に進むので、失敗したものも ACK して捨てる
            self.stats.errors += 1
            log.exception("フレーム処理に失敗: %s", entry_id)
        # XACK だけではエントリが残り続け、キューの長さ（= 溜まり具合）が分からなくなる。処理済みは消す
        pipe = self.r.pipeline()
        pipe.xack(stream, GROUP, entry_id)
        pipe.xdel(stream, entry_id)
        pipe.execute()
