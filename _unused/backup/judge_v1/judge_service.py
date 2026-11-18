"""judge：追跡の結果を読んで、線を越えたか（IN/OUT）を決め、DB と画面用の結果に書く（Python）。

  worker（検出 + 追跡）─▶ Redis（tracks:p…）─▶ 判定 ─▶ PostgreSQL / Redis（result:端末）

画像は、見ない。人ごとの枠（追跡ID・座標）と、端末の線だけで、決める（aggregator/judge.py）。
判定は軽いので、1 つの service が、全部の分割を読む。同じ端末の結果は、同じ分割に、順番どおりに届く。
"""

import json
import logging
import os
import signal
import time

import redis

from common.live import JUDGE_GROUP, PARTITIONS, now_ms, stream_name, tracks_stream
from libs.camera_registry import CameraRegistry
from libs.database import ResultWriter
from libs.redis_output import RedisOutput
from libs.settings import REDIS_URL
from libs.stats import Stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("judge")

NAME = os.environ.get("JUDGE_NAME", "judge")  # 1 つだけ動かす。名前を固定して、再起動しても、前回 ACK していない分を、引き継ぐ


class JudgeService:
    def __init__(self):
        self.r = redis.from_url(REDIS_URL)
        self.stats = Stats()
        self.registry = CameraRegistry()
        self.writer = ResultWriter()
        self.output = RedisOutput(self.r, self.stats)
        self.streams = [tracks_stream(stream_name(p)) for p in range(PARTITIONS)]
        self._stop = False

    def stop(self, *_):
        self._stop = True

    def handle(self, fields):
        """追跡の結果 1 フレームぶんを判定して、保存する。"""
        p = json.loads(fields[b"data"])
        camera_id, ts_ms, w, h = p["camera_id"], p["ts_ms"], p["w"], p["h"]
        cam = self.registry.get(camera_id)
        if cam is None:
            return
        t0 = time.perf_counter()
        judge = self.registry.judge_for(camera_id, w, h)
        alias = {int(k): v for k, v in p.get("alias", {}).items()}
        events = judge.update(ts_ms / 1000.0, p["tracks"], p.get("events", []), alias)
        judge_ms = (time.perf_counter() - t0) * 1000
        lag_ms = max(0, now_ms() - ts_ms)  # 撮ってから、判定し終えるまでの遅れ
        self.writer.write(camera_id, cam, ts_ms, w, h, events, p["n_dets"], len(p["tracks"]), p["infer_ms"], lag_ms, p.get("model"))
        self.output.publish_result(camera_id, ts_ms, w, h, p["tracks"], events, p["infer_ms"], lag_ms, judge.debug)
        self.stats.add(judge_ms, lag_ms)
        for e in events:
            log.info("通過 %s %s（%s）track=%d", camera_id, e[1].upper(), e[5], e[2])

    def heartbeat(self):
        self.r.hset(f"judge:{NAME}", mapping={
            "last_seen_ms": now_ms(), "processed": self.stats.processed, "errors": self.stats.errors,
            "judge_ms_avg": self.stats.infer_ms_avg, "lag_ms_avg": self.stats.lag_ms_avg,
        })
        self.r.expire(f"judge:{NAME}", 30)

    def run(self):
        for s in self.streams:  # コンシューマーグループを作る（無ければ。あれば何もしない）
            try:
                self.r.xgroup_create(s, JUDGE_GROUP, id="0", mkstream=True)
            except redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise
        read_ids = {s: "0" for s in self.streams}  # 起動直後は、前回 ACK していない分を先に処理し、尽きたら新着（">"）だけを待つ
        log.info("開始: judge=%s streams=%d 本", NAME, len(self.streams))
        last_hb = 0.0
        while not self._stop:
            if time.time() - last_hb > 2:
                try:
                    self.heartbeat()
                except redis.ConnectionError:
                    log.warning("Redis に接続できない（再試行）")
                last_hb = time.time()
            try:
                resp = self.r.xreadgroup(JUDGE_GROUP, NAME, dict(read_ids), count=50, block=1000)
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
                        self.handle(fields)
                    except Exception:
                        # 1 フレームの失敗で止めない。やり直すと判定の状態が二重に進むので、失敗したものも ACK して捨てる
                        self.stats.errors += 1
                        log.exception("判定に失敗: %s", entry_id)
                    pipe = self.r.pipeline()
                    pipe.xack(stream, JUDGE_GROUP, entry_id)
                    pipe.xdel(stream, entry_id)
                    pipe.execute()
            if resp == [] and any(v != ">" for v in read_ids.values()):
                read_ids = {s: ">" for s in read_ids}


def main():
    svc = JudgeService()
    signal.signal(signal.SIGTERM, svc.stop)
    signal.signal(signal.SIGINT, svc.stop)
    svc.run()


if __name__ == "__main__":
    main()
