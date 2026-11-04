"""スコア方式（軌跡の向き + 線をまたいだ事実 + 消えた・戻った）の、重みとしきい値を振って、正解（全 6 件）との合致を比べる。"""
import itertools
import sys

sys.path.insert(0, "/t")
import run_grid as G  # noqa: E402

det = sys.argv[1]
rows = []
for thr, cw, conf, cmin, vmin, mw in itertools.product([3, 4, 5], [1, 2, 3], [2, 4, 6], [0.4, 0.6], [0.1, 0.15], [0.08, 0.12]):
    h = dict(threshold=thr, cross_w=cw, confirm_frames=conf, c_min=cmin, v_min=vmin, min_win=mw)
    tot, per = G.evaluate(det, 0.25, 1, anchor="bottom_center", method="heading", heading=h)
    rows.append((tot[0] - 2 * tot[1] - tot[2], tot, h, per))
rows.sort(key=lambda r: -r[0])
print(f"== {det} score grid (合致, 過検出, 見逃し) / 全 6 件   組み合わせ {len(rows)}")
for r in rows[:6]:
    print(f"score={r[0]:+.0f} {tuple(r[1])} {r[2]} per={r[3]}")
print("-- 既定:", tuple(G.evaluate(det, 0.25, 1, anchor="bottom_center", method="heading", heading={})[0]))
print("-- 最低:", tuple(rows[-1][1]), rows[-1][2])
