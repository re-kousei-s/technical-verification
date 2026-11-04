"""追跡のしきい値（追跡を作る信頼度 high / 低い信頼度 low）と、検出の最低スコアを振って、軽いモデルの見逃しを減らせるかを比べる。"""
import itertools
import sys

sys.path.insert(0, "/t")
import run_grid as G  # noqa: E402

det = sys.argv[1]
rows = []
for ms, hi, lo, lost in itertools.product([0.1, 0.15, 0.2], [0.15, 0.2, 0.25], [0.1, 0.15, 0.2], [2.0, 3.0]):
    if lo > hi:
        continue
    tot, per = G.evaluate(det, ms, 1, anchor="bottom_center", edge=0.3,
                          tracker_over={"high_conf_det_threshold": hi, "low_conf_det_threshold": lo, "lost_track_seconds": lost})
    rows.append((tot[0] - 2 * tot[1] - tot[2], tot, ms, hi, lo, lost, per))
rows.sort(key=lambda r: -r[0])
print(f"== {det}  tracker grid  (合致, 過検出, 見逃し)")
for r in rows[:6]:
    print(f"score={r[0]:+.0f} {tuple(r[1])} min_score={r[2]} high={r[3]} low={r[4]} lost={r[5]} per-video={r[6]}")
base = G.evaluate(det, 0.25, 1, anchor="bottom_center", edge=0.3)
print("-- 現在（min_score 0.25 / high 0.25 / low 0.2 / lost 2.0）:", tuple(base[0]))
