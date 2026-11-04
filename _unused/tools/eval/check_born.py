import sys
sys.path.insert(0, "/t")
import run_grid as G
base = dict(threshold=3, cross_w=1, confirm_frames=6, c_min=0.5, v_min=0.1, min_win=0.08)
for det in ("lite0", "rfdetr"):
    for bb in (0, 1, 2, 3):
        tot, per = G.evaluate(det, 0.25, 1, anchor="bottom_center", method="heading", heading={**base, "born_bonus": bb})
        print(det, "born_bonus", bb, tuple(tot), per)
