"""③ 判定：② 追跡が流した人の枠から、足元が踏んだタイルで IN/OUT を決め、DB と画面用の結果に書く（Python）。

  tracks:p… ─▶ タイルの判定（aggregator/tile_judge.py）─▶ PostgreSQL / Redis（result:端末）

画像は見ない。軽いので、1 つの service が、全部の分割を読む。同じ端末の結果は、同じ分割に、順番どおりに届く。
"""

import json
import logging
import os
import signal
import time

import redis

from common.live import JUDGE_GROUP, PARTITIONS, now_ms, stream_name, tracks_stream
from libs.camera_registry import CameraRegistry
from libs.once import Once
from libs.database import ResultWriter
from libs.redis_output import RedisOutput
from libs.settings import REDIS_URL
from libs.stats import Stats
from libs.stream_service import StreamService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("judge")
NAME = os.environ.get("JUDGE_NAME", "judge")  # 1 つだけ動かす（名前を固定して、再起動しても、前回 ACK していない分を引き継ぐ）


def main():
    r = redis.from_url(REDIS_URL)
    stats = Stats()
    registry = CameraRegistry()
    writer = ResultWriter()
    output = RedisOutput(r, stats)
    # 同じフレームを、2 度判定しない。前回までに処理した最後の時刻は、DB（camera_state.last_frame_ts）から読む。
    # last_frame_ts は、通過の記録と同じ 1 回のコミットで書くので、再起動しても、数えた通過が二重にならない
    once = Once(writer.last_frame_ms)

    def handle(_stream, fields):
        p = json.loads(fields[b"data"])
        camera_id, ts_ms, w, h = p["camera_id"], p["ts_ms"], p["w"], p["h"]
        cam = registry.get(camera_id)
        if cam is None or not once.first(camera_id, ts_ms):
            return
        t0 = time.perf_counter()
        judge = registry.judge_for(camera_id, w, h)
        events = judge.update(ts_ms / 1000.0, p["tracks"])
        lag_ms = max(0, now_ms() - ts_ms)  # 撮ってから、判定し終えるまでの遅れ
        writer.write(camera_id, cam, ts_ms, w, h, events, p["n_dets"], len(p["tracks"]), p["infer_ms"], lag_ms, p.get("model"))
        output.publish_result(camera_id, ts_ms, w, h, p["tracks"], events, p["infer_ms"], lag_ms, judge.debug)
        stats.add((time.perf_counter() - t0) * 1000, lag_ms)
        for e in events:
            log.info("通過 %s %s（%s）人=%d", camera_id, e[1].upper(), e[5], e[2])

    streams = [tracks_stream(stream_name(p)) for p in range(PARTITIONS)]
    svc = StreamService(r, streams, JUDGE_GROUP, NAME, handle, stats, f"judge:{NAME}")
    signal.signal(signal.SIGTERM, svc.stop)
    signal.signal(signal.SIGINT, svc.stop)
    svc.run()


if __name__ == "__main__":
    main()
