"""worker（検出 + 追跡）：キューからフレームを取り出して、人を検出・追跡し、追跡の結果を、判定の service へ流す（Python）。

  バックエンド（Go）が積んだ JPEG ─▶ 検出 ─▶ 追跡 ─▶ Redis（tracks:p…）─▶ judge.py（線を越えたかの判定・DB）

画像を見るのは、ここまで。線を越えたかの判定は、judge.py（画像を見ない、2 次元の幾何だけ）が行う。
このファイルは、部品を組み立てて動かすだけ。中身は libs/ に分けてある。
  libs/settings.py         環境変数・定数
  libs/queue_consumer.py   キューの読み取りと ACK
  libs/frame_processor.py  1 フレームの処理（検出 → 追跡 → 追跡の結果を流す）
  libs/camera_registry.py  端末の設定と、追跡・判定の状態
  libs/redis_output.py     Redis への出力（画像・ハートビート）
  libs/annotator.py        検出枠つきの画像を描く
  libs/stats.py            処理件数・時間の集計
追跡は aggregator/tracking.py、判定は aggregator/judge.py、検出器は common/ にある。
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
    output = RedisOutput(rdb, stats)

    # 1 フレームの処理と、キューの読み取りを組み合わせる
    processor = FrameProcessor(registry, detector, rdb, output, stats)
    consumer = QueueConsumer(rdb, processor.handle, output.heartbeat, stats)

    # 停止の合図（docker stop など）を受けたら、処理中のフレームを終えてから止まる
    signal.signal(signal.SIGTERM, consumer.stop)
    signal.signal(signal.SIGINT, consumer.stop)

    consumer.run()


if __name__ == "__main__":
    main()
