"""① 検出の worker：キューからフレームを取り出して、人の枠を出し、② 追跡（tracker.py）へ流す（Python）。

  パイプライン（3 段。それぞれ別のコンテナ。Redis のストリームでつなぐ）
    バックエンド（Go）が積んだ JPEG ─① 検出（ここ）─▶ dets:p… ─② 追跡（tracker.py）─▶ tracks:p… ─③ 判定（judge.py）─▶ DB・画面

画像を見るのは、ここだけ。重いので、台数を増やして並べる。
  libs/queue_consumer.py   キューの読み取りと ACK（担当する分割を、worker どうしで分け合う）
  libs/frame_processor.py  1 フレームの処理（デコード → 検出 → 流す）
  libs/redis_output.py     検出枠つきの画像（管理画面用）・ハートビート
"""

import logging
import signal

import redis

from common.detectors import make_detector
from libs.camera_registry import CameraRegistry
from libs.frame_processor import FrameProcessor
from libs.queue_consumer import QueueConsumer
from libs.redis_output import RedisOutput
from libs.settings import DETECTOR, REDIS_URL
from libs.stats import Stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")


def main():
    rdb = redis.from_url(REDIS_URL)
    stats = Stats()

    # 部品を作る（下の層から順に）
    registry = CameraRegistry()
    log.info("検出器を読み込み中: %s", DETECTOR)
    detector = make_detector(DETECTOR, registry.min_score)
    output = RedisOutput(rdb, stats, registry.tiles_cfg)

    # 1 フレームの処理と、キューの読み取りを組み合わせる
    processor = FrameProcessor(registry, detector, rdb, output, stats)
    consumer = QueueConsumer(rdb, processor.handle, output.heartbeat, stats)

    # 停止の合図（docker stop など）を受けたら、処理中のフレームを終えてから止まる
    signal.signal(signal.SIGTERM, consumer.stop)
    signal.signal(signal.SIGINT, consumer.stop)

    consumer.run()


if __name__ == "__main__":
    main()
