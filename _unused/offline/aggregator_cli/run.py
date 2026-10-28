"""サーバー集計役：検出結果（端末から届くJSONと同じ形式）を読み、追跡＋ライン判定で IN/OUT を数える。

outputs/detections/ にある全条件 × configs の全トラッカー設定 を処理し、
  outputs/counts/results.csv              … 条件ごとに1行（IN/OUT、推論時間など）
  outputs/counts/events/<video_id>/*.csv  … 通過イベント（時刻・向き・追跡ID）
を書く。検出（推論）はしないので速い。線やトラッカーの設定を変えたら、これだけ回し直せばよい。
"""

import argparse
import csv
import itertools

import numpy as np

from aggregator.counter import CameraCounter
from common.config import COUNTS_DIR, DETECTIONS_DIR, load_config
from common.messages import read_messages, read_meta

FIELDS = [
    "video_id", "scene", "crowd", "pipeline", "model", "tiling", "sample_fps", "tracker", "anchor",
    "in", "out", "frames", "dets_per_frame", "infer_ms_mean", "infer_ms_p95",
]


def count_one(msgs, meta, video, tracker_cfg, anchor, min_crossing_seconds):
    counter = CameraCounter(
        video["line"], meta["src"]["w"], meta["src"]["h"], tracker_cfg,
        sample_fps=meta["sample_fps"] or meta["src"]["fps"], anchor=anchor,
        min_crossing_seconds=min_crossing_seconds,
    )
    for msg in msgs:
        counter.process(msg)
    return counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trackers", nargs="+", help="トラッカー設定名で絞り込む")
    parser.add_argument("--anchors", nargs="+", help="判定点で絞り込む（bottom_center / top_center など）")
    args = parser.parse_args()
    cfg = load_config()
    agg = cfg["aggregator"]
    videos = {v["id"]: v for v in cfg["videos"]}
    tracker_cfgs = [t for t in agg["trackers"] if not args.trackers or t["name"] in args.trackers]
    anchors = [a for a in agg["anchors"] if not args.anchors or a in args.anchors]
    min_cross = agg.get("min_crossing_seconds", 0.0)

    rows = []
    for path in sorted(DETECTIONS_DIR.glob("*/*.jsonl")):
        meta = read_meta(str(path).replace(".jsonl", ".meta.json"))
        video = videos.get(meta["video_id"])
        if video is None:
            print(f"[skip] {path.name}: 動画 {meta['video_id']} が configs にない")
            continue
        msgs = read_messages(path)
        infer = np.array([m["device"]["infer_ms"] for m in msgs]) if msgs else np.zeros(1)
        n_dets = sum(len(m["detections"]) for m in msgs)
        for tcfg, anchor in itertools.product(tracker_cfgs, anchors):
            counter = count_one(msgs, meta, video, tcfg, anchor, min_cross)
            rows.append({
                "video_id": meta["video_id"], "scene": video.get("scene"), "crowd": video.get("crowd"),
                "pipeline": meta["pipeline"], "model": meta["model"], "tiling": meta["tiling"],
                "sample_fps": meta["sample_fps"], "tracker": tcfg["name"], "anchor": anchor,
                "in": counter.in_count, "out": counter.out_count, "frames": len(msgs),
                "dets_per_frame": round(n_dets / max(len(msgs), 1), 2),
                "infer_ms_mean": round(float(infer.mean()), 1),
                "infer_ms_p95": round(float(np.percentile(infer, 95)), 1),
            })
            ev_path = COUNTS_DIR / "events" / meta["video_id"] / f"{path.stem}__{tcfg['name']}__{anchor}.csv"
            ev_path.parent.mkdir(parents=True, exist_ok=True)
            with open(ev_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["video_t", "direction", "tracker_id", "anchor_x", "anchor_y"])
                w.writerows((round(t, 3), d, tid, round(x), round(y)) for t, d, tid, x, y in counter.events)

    COUNTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(COUNTS_DIR / "results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"[done] {len(rows)} 条件 -> {COUNTS_DIR / 'results.csv'}")
    for r in rows:
        print(f"  {r['video_id']:<24} {r['pipeline']:<6} {r['model']:<24} {r['tiling']:<5} "
              f"fps={r['sample_fps']!s:<4} {r['tracker']:<15} {r['anchor']:<13} IN={r['in']:<3} OUT={r['out']:<3} "
              f"{r['infer_ms_mean']}ms")


if __name__ == "__main__":
    main()
