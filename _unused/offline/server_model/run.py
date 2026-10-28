"""系統A：サーバー検出（RF-DETR、CPU）。画像送信案のベースライン。

端末から画像を受け取ってサーバーで検出する想定。出力は端末役と同じ形式の JSONL
（outputs/detections/<video_id>/server__<model>__<tiling>__fps<n>.jsonl）なので、
追跡・ライン判定は aggregator で同じように処理される。
"""

import argparse
import os

import torch

from common import detect_runner
from common.config import add_filter_args, load_config
from common.detector_rfdetr import RFDETRDetector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_filter_args(parser)
    args = parser.parse_args()
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "4")))
    cfg = load_config()
    detect_runner.run("server", cfg, "server", args, RFDETRDetector)


if __name__ == "__main__":
    main()
