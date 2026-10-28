"""検出側（端末役 / サーバー検出）の共通ループ。

動画 × モデル × 分割 ごとに検出し、間引き条件ごとの JSONL（送信メッセージ列）を書き出す。
検出器は detect(image_bgr) -> (xyxy[N,4] float32, scores[N] float32) を持つ人物専用のもの。
"""

import csv
import json
import os
import platform
import time
import traceback
from pathlib import Path

from common.config import (
    DATA_DIR,
    DETECTIONS_DIR,
    FRAME_COUNTS_DIR,
    camera_id,
    fps_tag,
    pick,
    select_videos,
    video_path,
)
from common.messages import build_message, make_ts, write_meta
from common.tiling import detect_tiled, make_tiles
from common.video import iter_sampled_frames, read_frames_at, video_info


def detections_path(video_id, pipeline, model, tiling, fps):
    return DETECTIONS_DIR / video_id / f"{pipeline}__{model}__{tiling}__fps{fps_tag(fps)}.jsonl"


def load_frame_count_gt():
    """data/frame_counts.csv（video_id,time_sec,gt_count）。無ければ空。"""
    path = DATA_DIR / "frame_counts.csv"
    gt = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("video_id") and row.get("time_sec"):
                    gt.setdefault(row["video_id"], []).append(float(row["time_sec"]))
    return gt


def run(pipeline, cfg, section, args, make_detector):
    videos = select_videos(cfg, args.videos)
    models = pick(cfg[section]["models"], args.models)
    tilings = pick(cfg["tiling"]["modes"], args.tiling)
    fps_list = pick(cfg["sampling"]["fps"], args.fps)
    tile_opts = {k: v for k, v in cfg["tiling"].items() if k != "modes"}
    min_score = cfg["detector"]["min_score"]
    ts_base = cfg.get("ts_base", "2026-01-01T00:00:00+09:00")
    frame_gt = load_frame_count_gt()

    failed = []
    for model in models:
        detector = None  # 必要になるまで読み込まない（全部出力済みならモデルを落とさない）
        for video in videos:
            if model in failed:
                break
            vpath = video_path(video)
            info = video_info(vpath)
            for tiling in tilings:
                tiles = make_tiles(info["w"], info["h"], tiling, video.get("line"), **tile_opts)
                todo = [
                    f for f in fps_list
                    if args.force or not detections_path(video["id"], pipeline, model, tiling, f).exists()
                ]
                fc_path = FRAME_COUNTS_DIR / video["id"] / f"{pipeline}__{model}__{tiling}.csv"
                need_fc = video["id"] in frame_gt and (args.force or not fc_path.exists())
                if not todo and not need_fc:
                    print(f"[skip] {video['id']} {model} {tiling}: 出力済み")
                    continue
                if detector is None:
                    try:
                        detector = make_detector(model, min_score)
                    except Exception:
                        # 重みのダウンロード失敗など。このモデルだけ飛ばして、残りの条件は続ける
                        traceback.print_exc()
                        print(f"[error] {model} を読み込めないので飛ばします")
                        failed.append(model)
                        break
                detect = lambda img: detect_tiled(detector.detect, img, tiles)  # noqa: E731
                if todo:
                    _run_sampled(pipeline, video, vpath, info, model, tiling, tiles, todo, detect, ts_base, min_score)
                if need_fc:
                    _run_frame_counts(video, vpath, frame_gt[video["id"]], fc_path, detect)
    if failed:
        raise SystemExit(f"[error] 読み込めなかったモデル: {failed}（他の条件は出力済み。再実行すると続きから回る）")


def _run_sampled(pipeline, video, vpath, info, model, tiling, tiles, fps_list, detect, ts_base, min_score):
    out = {f: detections_path(video["id"], pipeline, model, tiling, f) for f in fps_list}
    for p in out.values():
        p.parent.mkdir(parents=True, exist_ok=True)
    tmp = {f: Path(str(p) + ".tmp") for f, p in out.items()}
    files = {f: open(p, "w", encoding="utf-8") for f, p in tmp.items()}
    n, total_ms, t_start = 0, 0.0, time.time()
    try:
        for idx, t, frame, hit in iter_sampled_frames(vpath, fps_list):
            t0 = time.perf_counter()
            boxes, scores = detect(frame)
            ms = (time.perf_counter() - t0) * 1000
            n, total_ms = n + 1, total_ms + ms
            msg = build_message(
                camera_id=camera_id(video), floor=video.get("floor"), ts=make_ts(ts_base, t),
                w=info["w"], h=info["h"], model=model, boxes=boxes, scores=scores,
                infer_ms=ms, frame_idx=idx, video_t=t,
            )
            line = json.dumps(msg, ensure_ascii=False) + "\n"
            for f in hit:
                files[f].write(line)
            if n % 50 == 0:
                print(f"  {video['id']} {model} {tiling}: {n} frames, t={t:.1f}s, {total_ms / n:.1f} ms/frame", flush=True)
    finally:
        for fh in files.values():
            fh.close()
    for f, p in out.items():
        os.replace(tmp[f], p)
        write_meta(str(p).replace(".jsonl", ".meta.json"), {
            "pipeline": pipeline, "video_id": video["id"], "camera_id": camera_id(video),
            "model": model, "tiling": tiling, "tiles": tiles, "sample_fps": f,
            "src": info, "min_score": min_score, "host": platform.node(),
            "cpu_limit_threads": os.environ.get("OMP_NUM_THREADS"),
        })
    print(f"[done] {pipeline} {video['id']} {model} {tiling}: {n} frames, "
          f"{total_ms / max(n, 1):.1f} ms/frame, wall {time.time() - t_start:.0f}s")


def _run_frame_counts(video, vpath, times, path, detect):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["video_id", "time_sec", "frame_idx", "scores"])
        for t, idx, frame in read_frames_at(vpath, times):
            _, scores = detect(frame)
            w.writerow([video["id"], t, idx, " ".join(f"{s:.3f}" for s in scores)])
    print(f"[done] frame counts -> {path}")
