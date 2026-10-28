"""worker：キューからフレームを取り出して人を認識し、結果を DB に書く（Python）。

  バックエンド（Go）が積んだ JPEG ─▶ 検出 ─▶ 追跡 ─▶ 線 / ゲートで通過を判定 ─▶ PostgreSQL

このファイルは、部品を組み立てて動かすだけ。中身は libs/ に分けてある。
  libs/settings.py         環境変数・定数
  libs/queue_consumer.py   キューの読み取りと ACK
  libs/frame_processor.py  1 フレームの処理（検出 → 追跡 → 判定 → 保存 → 出力）
  libs/camera_registry.py  端末の設定と、追跡の状態
  libs/database.py         DB への書き込み
  libs/redis_output.py     Redis への出力（認識結果・画像・ハートビート）
  libs/annotator.py        検出枠つきの画像を描く
  libs/stats.py            処理件数・時間の集計
追跡・線・ゲートの計算は aggregator/、検出器は common/ にある。
"""

import logging
import signal

import redis

from common.detectors import make_detector
from libs.camera_registry import CameraRegistry
from libs.database import ResultWriter
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
    writer = ResultWriter()
    output = RedisOutput(rdb, stats)

    # 1 フレームの処理と、キューの読み取りを組み合わせる
    processor = FrameProcessor(registry, detector, writer, output, stats)
    consumer = QueueConsumer(rdb, processor.handle, output.heartbeat, stats)

    # 停止の合図（docker stop など）を受けたら、処理中のフレームを終えてから止まる
    signal.signal(signal.SIGTERM, consumer.stop)
    signal.signal(signal.SIGINT, consumer.stop)

    consumer.run()


if __name__ == "__main__":
    main()
