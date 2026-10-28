"""端末 → サーバーの送信メッセージ（仕様書5章の形式）。

オフライン検証では、実際に送る代わりに JSONL（1行=1回の送信）に書き出す。
集計側（aggregator）はこの JSONL を ts 順に読み、実機から届いた場合と同じ処理をする。
検証用の付加情報は "_offline" に入れる（本番の送信には含めない）。
"""

import json
from datetime import datetime, timedelta


def make_ts(base_iso, t_sec):
    base = datetime.fromisoformat(base_iso)
    return (base + timedelta(seconds=t_sec)).isoformat(timespec="milliseconds")


def ts_to_sec(ts):
    return datetime.fromisoformat(ts).timestamp()


def build_message(*, camera_id, floor, ts, w, h, model, boxes, scores, infer_ms, frame_idx, video_t):
    dets = [
        {
            "x": round(float(x1), 1),
            "y": round(float(y1), 1),
            "w": round(float(x2 - x1), 1),
            "h": round(float(y2 - y1), 1),
            "score": round(float(s), 3),
        }
        for (x1, y1, x2, y2), s in zip(boxes, scores)
    ]
    return {
        "camera_id": camera_id,
        "floor": floor,
        "ts": ts,
        "frame": {"w": w, "h": h},
        "model": model,
        "detections": dets,
        "device": {"infer_ms": round(infer_ms, 2)},
        "_offline": {"frame_idx": frame_idx, "video_t": round(video_t, 4)},
    }


def write_meta(path, meta):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def read_meta(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_messages(path):
    with open(path, encoding="utf-8") as f:
        msgs = [json.loads(line) for line in f if line.strip()]
    # 通信断のあと時刻順に再送される前提なので、集計側は ts 順に処理する
    msgs.sort(key=lambda m: ts_to_sec(m["ts"]))
    return msgs
