"""追跡の枠・ID・足元と線の距離 s を、動画のフレームに重ねて、並べる（数え漏れの原因を、目で見る）。
  python render_tracks.py <入力名> <開始秒> <終了秒> <出力画像>"""
import json, sys
import cv2, numpy as np, yaml
sys.path.insert(0, "/t")
import evalcore as E
from check_hard import LINES
from aggregator.counter import CameraCounter
name, t0, t1, out = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
d, fr = E.load(f"/o/{name}.json", 0.3)
c = CameraCounter(LINES, d["w"], d["h"], json.loads(json.dumps(E.TRACKERS["lowfps"])), d["fps"], "bottom_center", 0.0, 0.0, 1.5, "episode", {"margin": 0.12, "stitch_seconds": 0.7, "reach": 0.5, "vanish_reach": 0.35, "vanish_frames": 2})
g = c.gates[0]
cap = cv2.VideoCapture("/v/hard_in12_out12.mp4")
tiles = []
for k, m in enumerate(E.messages(d, fr)):
    tr = c.process(m)
    t = k / d["fps"]
    if not (t0 <= t <= t1):
        continue
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, f = cap.read()
    f = cv2.resize(f, (d["w"], d["h"]))
    for L, col in zip(LINES, [(0, 0, 255), (0, 220, 255)]):
        a, b = L["line"]
        cv2.line(f, (int(a[0] * d["w"]), int(a[1] * d["h"])), (int(b[0] * d["w"]), int(b[1] * d["h"])), col, 2)
    for i in range(len(tr)):
        tid = int(tr.tracker_id[i]); x1, y1, x2, y2 = [int(v) for v in tr.xyxy[i]]
        pt = np.array([(x1 + x2) / 2, y2]); s = float(np.dot(pt - g.a, g.n)) / (y2 - y1)
        st = g.tracks.get(tid)
        cv2.rectangle(f, (x1, y1), (x2, y2), (0, 200, 0), 2)
        cv2.circle(f, (int(pt[0]), int(pt[1])), 5, (255, 0, 255), -1)
        cv2.putText(f, f"#{tid} s={s:+.2f} side={st.side if st else 0:+d}", (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
        cv2.putText(f, f"#{tid} s={s:+.2f} side={st.side if st else 0:+d}", (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(f, f"{t:.1f}s", (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)
    cv2.putText(f, f"{t:.1f}s", (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 1)
    import os
    if os.environ.get("CROP"):
        cx0, cy0, cx1, cy1 = [float(v) for v in os.environ["CROP"].split(",")]
        f = f[int(cy0 * d["h"]):int(cy1 * d["h"]), int(cx0 * d["w"]):int(cx1 * d["w"])]
        tiles.append(cv2.resize(f, (640, int(640 * f.shape[0] / f.shape[1]))))
    else:
        tiles.append(cv2.resize(f, (640, int(640 * d["h"] / d["w"]))))
while len(tiles) % 3:
    tiles.append(np.zeros_like(tiles[0]))
rows = [np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)]
cv2.imwrite(out, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 82])
