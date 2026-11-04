import sys
sys.path.insert(0, "/t")
import run_grid as G
combos = {
 "案A thr3 cw1 conf4 c.5 v.12 mw.08": dict(threshold=3, cross_w=1, confirm_frames=4, c_min=0.5, v_min=0.12, min_win=0.08),
 "案B thr3 cw1 conf4 c.5 v.15 mw.08": dict(threshold=3, cross_w=1, confirm_frames=4, c_min=0.5, v_min=0.15, min_win=0.08),
 "案C thr3 cw1 conf6 c.5 v.1  mw.08": dict(threshold=3, cross_w=1, confirm_frames=6, c_min=0.5, v_min=0.10, min_win=0.08),
 "案D thr3 cw2 conf4 c.5 v.12 mw.08": dict(threshold=3, cross_w=2, confirm_frames=4, c_min=0.5, v_min=0.12, min_win=0.08),
}
for det in ("lite0", "lite2", "rfdetr"):
    for name, h in combos.items():
        tot, per = G.evaluate(det, 0.25, 1, anchor="bottom_center", method="heading", heading=h)
        print(det, name, tuple(tot), per)
