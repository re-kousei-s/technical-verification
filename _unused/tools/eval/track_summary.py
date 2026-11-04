"""追跡の軌跡を、短い文字で出す（人が、どこから、どこへ歩いたか。線を置く場所と、正解を決めるために使う）。
  python track_summary.py <検出 JSON> <最低スコア>"""
import sys

sys.path.insert(0, "/t")
import evalcore as E  # noqa: E402

d, frames = E.load(sys.argv[1], float(sys.argv[2]))
_, tracks = E.run(d, frames, [{"id": "x", "name": "x", "line": [[0, 0], [0.001, 0]]}])
for tid, t in sorted(tracks.items()):
    if t["n"] < 3:
        continue
    (t0, p0), (t1, p1) = t["first"], t["last"]
    print(f"track {tid}: {t0:4.1f}s ({p0[0]:.2f},{p0[1]:.2f}) → {t1:4.1f}s ({p1[0]:.2f},{p1[1]:.2f})  {t['n']}フレーム")
