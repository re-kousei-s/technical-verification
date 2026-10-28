"""系統B：エッジ端末役（MediaPipe Object Detector）。

スマホと同じく「画像から人を検出して、座標だけを送る」ところまでを行う。
追跡・ライン判定はしない（それは aggregator = サーバー集計役の仕事）。
送信の代わりに outputs/detections/<video_id>/edge__<model>__<tiling>__fps<n>.jsonl に書く。
"""

import argparse

from common import detect_runner
from common.config import add_filter_args, load_config
from common.detector_mediapipe import MediaPipeDetector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_filter_args(parser)
    args = parser.parse_args()
    cfg = load_config()
    detect_runner.run("edge", cfg, "edge", args, MediaPipeDetector)


if __name__ == "__main__":
    main()
