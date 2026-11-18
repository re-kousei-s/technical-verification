"""② 追跡：① 検出が流した枠に、人ごとの ID を付けて、③ 判定（judge.py）へ流す（Python）。

  dets:p… ─▶ 距離だけの追跡（aggregator/simple_tracker.py）─▶ tracks:p…

画像は見ない。軽いので、1 つの service が、全部の分割を読む。同じ端末の結果は、同じ分割に、順番どおりに届く。
"""

import json
import logging
import os
import signal
import time

import redis

from common.live import PARTITIONS, TRACKER_GROUP, dets_stream, now_ms, stream_name, tracks_stream
from libs.camera_registry import CameraRegistry
from libs.once import Once
from libs.settings import REDIS_URL
from libs.stats import Stats
from libs.stream_service import StreamService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
NAME = os.environ.get("TRACKER_NAME", "tracker")  # 1 つだけ動かす（名前を固定して、再起動しても、前回 ACK していない分を引き継ぐ）
STREAM_MAXLEN = 5000


def main():
    r = redis.from_url(REDIS_URL)
    stats = Stats()
    registry = CameraRegistry()
    once = Once()  # 同じフレームを、2 度追跡しない（追跡の状態が、二重に進まないように）

    def handle(stream, fields):
        p = json.loads(fields[b"data"])
        camera_id, ts_ms, w, h = p["camera_id"], p["ts_ms"], p["w"], p["h"]
        if registry.get(camera_id) is None or not once.first(camera_id, ts_ms):
            return
        t0 = time.perf_counter()
        dets = p["dets"]
        tracks = registry.tracker_for(camera_id, w, h).update([d[:4] for d in dets], [d[4] for d in dets], ts_ms / 1000.0)
        r.xadd(tracks_stream(stream), {"data": json.dumps({
            "camera_id": camera_id, "ts_ms": ts_ms, "w": w, "h": h, "model": p.get("model"),
            "infer_ms": p.get("infer_ms", 0), "n_dets": len(dets), "tracks": tracks,
        })}, maxlen=STREAM_MAXLEN, approximate=True)
        stats.add((time.perf_counter() - t0) * 1000, max(0, now_ms() - ts_ms))

    streams = [dets_stream(stream_name(p)) for p in range(PARTITIONS)]
    svc = StreamService(r, streams, TRACKER_GROUP, NAME, handle, stats, f"tracker:{NAME}")
    signal.signal(signal.SIGTERM, svc.stop)
    signal.signal(signal.SIGINT, svc.stop)
    svc.run()


if __name__ == "__main__":
    main()
