"""Redis Streams のキューからフレームを取り出して、処理に渡す。"""

import logging
import time

import redis

from common.live import GROUP, stream_name
from libs.settings import NAME, OWNED

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

    def run(self):
        streams = [stream_name(p) for p in OWNED]
        self._create_groups(streams)
        # 起動直後は、前回 ACK していない分（"0"）を先に処理する。尽きたら新着（">"）だけを待つ
        read_ids = {s: "0" for s in streams}
        last_heartbeat = 0
        log.info("開始: worker=%s partitions=%s", NAME, OWNED)

        while not self._stop:
            if time.time() - last_heartbeat > 2:
                self.heartbeat()
                last_heartbeat = time.time()
            try:
                resp = self.r.xreadgroup(GROUP, NAME, read_ids, count=4, block=1000)
            except redis.ConnectionError:
                log.warning("Redis に接続できない（再試行）")
                time.sleep(2)
                continue

            for stream, entries in resp:
                stream = stream.decode()
                if not entries and read_ids[stream] != ">":
                    read_ids[stream] = ">"  # 未処理の分を読み終えた。ここからは新着だけ
                    continue
                for entry_id, fields in entries:
                    self._process(stream, entry_id, fields)

            if resp == [] and any(v != ">" for v in read_ids.values()):
                read_ids = {s: ">" for s in streams}

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
