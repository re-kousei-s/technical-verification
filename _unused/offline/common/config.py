"""検証条件（configs/matrix.yaml）の読み込みと、CLI での絞り込み。"""

import argparse
import os
from pathlib import Path

import yaml

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/models"))
OUTPUTS_DIR = Path(os.environ.get("OUTPUTS_DIR", "/outputs"))
DETECTIONS_DIR = OUTPUTS_DIR / "detections"
FRAME_COUNTS_DIR = OUTPUTS_DIR / "frame_counts"
COUNTS_DIR = OUTPUTS_DIR / "counts"
REPORT_DIR = OUTPUTS_DIR / "report"


def load_config(path=None):
    path = path or os.environ.get("CONFIG", "/configs/matrix.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def video_path(video):
    return DATA_DIR / "videos" / video["file"]


def camera_id(video):
    return video.get("camera_id", video["id"])


def fps_tag(fps):
    """ファイル名用の間引き表記。0 は全フレーム。"""
    return "all" if not fps else f"{fps:g}"


def add_filter_args(parser: argparse.ArgumentParser):
    parser.add_argument("--videos", nargs="+", help="動画IDで絞り込む")
    parser.add_argument("--models", nargs="+", help="モデル名で絞り込む")
    parser.add_argument("--tiling", nargs="+", help="分割方式で絞り込む（none / 2x2 / line など）")
    parser.add_argument("--fps", nargs="+", type=float, help="間引き（1秒あたり枚数、0=全フレーム）")
    parser.add_argument("--force", action="store_true", help="出力済みでもやり直す")


def pick(values, selected):
    if not selected:
        return list(values)
    missing = [s for s in selected if s not in values]
    if missing:
        print(f"[warn] 設定にない値が指定されたので、そのまま使います: {missing}")
    return list(selected)


def select_videos(cfg, selected):
    videos = cfg["videos"]
    if selected:
        videos = [v for v in videos if v["id"] in selected]
        if not videos:
            raise SystemExit(f"動画ID {selected} は configs にありません")
    return videos
