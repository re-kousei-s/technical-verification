"""② 追跡・③ 判定で共通の、「全部の分割のストリームを読んで、1 件ずつ処理する」ループ。

どちらも軽いので、1 つの service が、全部の分割を読む。名前を固定して、再起動しても、前回 ACK していない分を引き継ぐ。
1 件の処理に失敗しても止めない（やり直すと、状態が二重に進むので、失敗したものも ACK して捨てる）。
"""

import logging
import time

import redis

from common.live import now_ms

log = logging.getLogger("service")


class StreamService:
    def __init__(self, rdb, streams, group, name, handle, stats, heartbeat_key):
        self.r, self.streams, self.group, self.name = rdb, streams, group, name
        self.handle = handle  # handle(stream, fields)：1 件を処理する
        self.stats = stats
        self.heartbeat_key = heartbeat_key  # 例 "tracker:tracker"。管理画面が、生きているかを見る
        self._stop = False

    def stop(self, *_):
        self._stop = True

    def heartbeat(self):
        self.r.hset(self.heartbeat_key, mapping={
            "last_seen_ms": now_ms(), "processed": self.stats.processed, "errors": self.stats.errors,
            "ms_avg": self.stats.infer_ms_avg, "lag_ms_avg": self.stats.lag_ms_avg,
        })
        self.r.expire(self.heartbeat_key, 30)

    def run(self):
        for s in self.streams:  # コンシューマーグループを作る（無ければ。あれば何もしない）
            try:
                self.r.xgroup_create(s, self.group, id="0", mkstream=True)
            except redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise
        read_ids = {s: "0" for s in self.streams}  # 起動直後は、前回 ACK していない分を先に処理し、尽きたら新着（">"）だけを待つ
        log.info("開始: %s streams=%d 本", self.name, len(self.streams))
        last_hb = 0.0
        while not self._stop:
            if time.time() - last_hb > 2:
                try:
                    self.heartbeat()
                except redis.ConnectionError:
                    log.warning("Redis に接続できない（再試行）")
                last_hb = time.time()
            try:
                resp = self.r.xreadgroup(self.group, self.name, dict(read_ids), count=50, block=1000)
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
                    try:
                        self.handle(stream, fields)
                    except Exception:
                        self.stats.errors += 1
                        log.exception("処理に失敗: %s %s", stream, entry_id)
                    pipe = self.r.pipeline()
                    pipe.xack(stream, self.group, entry_id)
                    pipe.xdel(stream, entry_id)
                    pipe.execute()
            if resp == [] and any(v != ">" for v in read_ids.values()):
                read_ids = {s: ">" for s in read_ids}
