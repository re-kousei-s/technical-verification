"""正解づくりの補助：線の上の画素を時間方向に積んだ「スリットスキャン」画像を作る。

各フレームから線に沿った帯（幅 --band ピクセル）を取り出し、上から下へ時間順に並べる。
線を越えた人は1つの塊として写るので、動画を再生するより速く通過数を数えられる。
線の上で立ち止まっている人は縦に長い縞になる（通過ではない）。
--events を付けると、その条件で数えた通過を重ねて描く（緑○=IN、赤○=OUT）。
数え漏れ・多重カウントの確認にも使える。

出力: outputs/slitscan/<video_id>_<n>.png（--seconds-per-image 秒ごとに分割）

例: python aggregator/slitscan.py --video stair_a_crowded \
      --events server__rfdetr_nano__none__fpsall__bytetrack__bottom_center
"""

import argparse
import csv

import cv2
import numpy as np

from common.config import COUNTS_DIR, OUTPUTS_DIR, load_config, select_videos, video_path
from common.tiling import line_to_px


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", required=True)
    parser.add_argument("--events", nargs="*", default=[],
                        help="重ねる通過イベント（outputs/counts/events/<video>/ のファイル名、拡張子なし）")
    parser.add_argument("--band", type=int, default=9, help="線に沿って平均する帯の太さ（px）")
    parser.add_argument("--px-per-second", type=int, default=100, help="時間軸の縮尺")
    parser.add_argument("--seconds-per-image", type=float, default=7.0)
    args = parser.parse_args()

    cfg = load_config()
    video = select_videos(cfg, [args.video])[0]
    cap = cv2.VideoCapture(str(video_path(video)))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # 線に沿ったサンプル点（線の長さぶん）と、線に垂直な方向へのずらし
    (x1, y1), (x2, y2) = line_to_px(video["line"], w, h)
    length = int(np.hypot(x2 - x1, y2 - y1))
    d = np.array([x2 - x1, y2 - y1]) / max(length, 1)
    n = np.array([d[1], -d[0]])
    s = np.arange(length)
    offsets = np.arange(args.band) - args.band // 2
    map_x = (x1 + d[0] * s[None, :] + n[0] * offsets[:, None]).astype(np.float32)
    map_y = (y1 + d[1] * s[None, :] + n[1] * offsets[:, None]).astype(np.float32)

    rows, times = [], []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        msec = cap.get(cv2.CAP_PROP_POS_MSEC)
        times.append(msec / 1000.0 if msec > 0 or not times else len(times) / fps)
        rows.append(cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR).mean(axis=0))
    cap.release()
    times = np.array(times)

    # 時間軸を等間隔（px_per_second）に並べ直す（可変フレームレートでも縮尺が揃う）
    total = times[-1]
    ys = np.arange(int(total * args.px_per_second) + 1) / args.px_per_second
    idx = np.clip(np.searchsorted(times, ys), 0, len(rows) - 1)
    img = np.stack([rows[i] for i in idx]).astype(np.uint8)

    colors = [((0, 200, 0), (0, 0, 255)), ((0, 160, 255), (255, 0, 200))]  # 1つ目、2つ目の条件
    for k, name in enumerate(args.events):
        with open(COUNTS_DIR / "events" / video["id"] / f"{name}.csv", encoding="utf-8") as f:
            for e in csv.DictReader(f):
                p = np.array([float(e["anchor_x"]), float(e["anchor_y"])])
                pos = int(np.dot(p - np.array([x1, y1]), d))  # 線上の位置
                y = int(float(e["video_t"]) * args.px_per_second)
                c = colors[k % 2][0 if e["direction"] == "in" else 1]
                if k % 2 == 0:
                    cv2.circle(img, (pos, y), 10, c, 2)
                else:
                    cv2.rectangle(img, (pos - 9, y - 9), (pos + 9, y + 9), c, 2)

    out_dir = OUTPUTS_DIR / "slitscan"
    out_dir.mkdir(parents=True, exist_ok=True)
    step = int(args.seconds_per_image * args.px_per_second)
    for part, start in enumerate(range(0, img.shape[0], step)):
        sub = img[start:start + step].copy()
        for sec in range(int(start / args.px_per_second), int((start + step) / args.px_per_second) + 1):
            y = sec * args.px_per_second - start
            if 0 <= y < sub.shape[0]:
                cv2.line(sub, (0, y), (30, y), (255, 0, 0), 2)
                cv2.putText(sub, f"{sec}s", (35, y + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
        for x in range(0, length, 200):
            cv2.putText(sub, str(x), (x, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
        path = out_dir / f"{video['id']}_{part}.png"
        cv2.imwrite(str(path), sub)
        print(f"[done] {path}")
    print("横軸 = 線の始点からの距離(px)、縦軸 = 時間（下ほど後）。"
          "凡例: 1つ目の --events は ○（緑=IN 赤=OUT）、2つ目は □（橙=IN 紫=OUT）")


if __name__ == "__main__":
    main()
