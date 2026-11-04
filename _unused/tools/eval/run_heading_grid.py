"""方向スコアの判定（heading）のパラメータを振って、正解（全 6 件）との合致を比べる。線をまたぐ方式（line）と並べて出す。"""
import itertools
import sys

sys.path.insert(0, "/t")
import run_grid as G  # noqa: E402

det = sys.argv[1]
rows = []
for zone, md, reach, cnt, vmin in itertools.product([0.4, 0.5, 0.6], [0.15, 0.2, 0.3], [0.3, 0.4], [3, 4], [0.1, 0.15, 0.2]):
    h = dict(zone=zone, min_disp=md, reach=reach, count=cnt, v_min=vmin)
    tot, per = G.evaluate(det, 0.25, 1, anchor="bottom_center", method="heading", heading=h)
    rows.append((tot[0] - 2 * tot[1] - tot[2], tot, h, per))
rows.sort(key=lambda r: -r[0])
print(f"== {det} heading  (合致, 過検出, 見逃し) / 全 6 件")
for r in rows[:6]:
    print(f"score={r[0]:+.0f} {tuple(r[1])} {r[2]} per-video={r[3]}")
worst = rows[-1]
print("-- 最低:", tuple(worst[1]), worst[2])
print("-- 参考 line 方式（現在）:", tuple(G.evaluate(det, 0.25, 1, anchor="bottom_center", edge=0.3)[0]))
