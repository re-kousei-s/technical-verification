"""方向スコアの「履歴の長さ（smooth）」と「前の向きとのつじつま（cos_min）」を振って、正解（全 6 件）との合致を比べる。"""
import itertools
import sys

sys.path.insert(0, "/t")
import run_grid as G  # noqa: E402

det = sys.argv[1]
rows = []
for vf, vb, cnt, md, zone in itertools.product([2, 3, 4], [0, 1, 2, 3], [3, 4], [0.15, 0.2], [0.4, 0.5]):
    h = dict(zone=zone, reach=0.3, count=cnt, v_min=0.1, min_disp=md, smooth=1, cos_min=0.3, vanish_frames=vf, vanish_bonus=vb)
    tot, per = G.evaluate(det, 0.25, 1, anchor="bottom_center", method="heading", heading=h)
    rows.append((tot[0] - 2 * tot[1] - tot[2], tot, h, per))
rows.sort(key=lambda r: -r[0])
print(f"== {det} smooth grid (合致, 過検出, 見逃し) / 全 6 件")
for r in rows[:5]:
    print(f"score={r[0]:+.0f} {tuple(r[1])} vanish_frames={r[2]['vanish_frames']} bonus={r[2]['vanish_bonus']} count={r[2]['count']} min_disp={r[2]['min_disp']} zone={r[2]['zone']} per={r[3]}")
ref = dict(zone=0.4, reach=0.3, count=4, v_min=0.1, min_disp=0.2, smooth=1, cos_min=0.3, vanish_bonus=0)  # 消えた加算なし
print("-- 消えた加算なし:", tuple(G.evaluate(det, 0.25, 1, anchor="bottom_center", method="heading", heading=ref)[0]))
cur = dict(zone=0.4, reach=0.3, count=4, v_min=0.1, min_disp=0.2)
print("-- 新しい既定（bonus 2, 3 フレーム）:", tuple(G.evaluate(det, 0.25, 1, anchor="bottom_center", method="heading", heading=cur)[0]))
