"""1条件ぶんの結果を動画に描いて確認する（outputs/render/*.mp4）。

検出枠・追跡ID・線・IN/OUTの累計を、間引き後のフレームに描く。
数え間違いの原因（取りこぼし、ID切り替わり、線の位置）を目で確かめる用。

例: python aggregator/render.py edge__efficientdet_lite0_int8__none__fps2 --video sample_people_walking
"""

import argparse

import cv2
import supervision as sv

from aggregator.counter import CameraCounter
from aggregator.preview import draw_line
from common.config import DETECTIONS_DIR, OUTPUTS_DIR, load_config, video_path
from common.messages import read_messages, read_meta


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("condition", help="outputs/detections/<video>/ のファイル名（拡張子なし）")
    parser.add_argument("--video", required=True)
    parser.add_argument("--tracker", help="トラッカー設定名（省略時は最初のもの）")
    parser.add_argument("--anchor", help="判定点（省略時は configs の最初のもの）")
    parser.add_argument("--min-score", type=float, default=0.25, help="これ未満の検出枠は描かない（追跡には使われている）")
    args = parser.parse_args()

    cfg = load_config()
    video = next(v for v in cfg["videos"] if v["id"] == args.video)
    tcfg = next(t for t in cfg["aggregator"]["trackers"] if not args.tracker or t["name"] == args.tracker)
    path = DETECTIONS_DIR / args.video / f"{args.condition}.jsonl"
    meta = read_meta(str(path).replace(".jsonl", ".meta.json"))
    msgs = read_messages(path)
    fps = meta["sample_fps"] or meta["src"]["fps"]
    anchor = args.anchor or cfg["aggregator"]["anchors"][0]
    counter = CameraCounter(video["line"], meta["src"]["w"], meta["src"]["h"], tcfg, fps, anchor,
                            cfg["aggregator"].get("min_crossing_seconds", 0.0))

    out_dir = OUTPUTS_DIR / "render"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.video}__{args.condition}__{tcfg['name']}__{anchor}.mp4"
    # 間引き後のフレームを実時間どおりの速さで並べる
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps,
                             (meta["src"]["w"], meta["src"]["h"]))
    box = sv.BoxAnnotator(thickness=2)
    label = sv.LabelAnnotator(text_scale=0.6)
    cap = cv2.VideoCapture(str(video_path(video)))
    pos = -1
    for msg in msgs:
        tracked = counter.process(msg)
        idx = msg["_offline"]["frame_idx"]
        while pos < idx:  # 順に読み進める（seek より確実）
            ok, frame = cap.read()
            pos += 1
            if not ok:
                break
        img = frame.copy()
        shown = tracked[tracked.confidence >= args.min_score] if len(tracked) else tracked
        labels = [f"#{tid} {c:.2f}" if tid >= 0 else f"? {c:.2f}" for tid, c in zip(shown.tracker_id, shown.confidence)] if len(shown) else []
        img = box.annotate(img, shown)
        img = label.annotate(img, shown, labels)
        draw_line(img, video["line"])
        text = f"t={msg['_offline']['video_t']:.1f}s IN={counter.in_count} OUT={counter.out_count} dets={len(msg['detections'])}"
        cv2.putText(img, text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 6)
        cv2.putText(img, text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
        writer.write(img)
    writer.release()
    cap.release()
    print(f"[done] {out_path}  IN={counter.in_count} OUT={counter.out_count}")


if __name__ == "__main__":
    main()
