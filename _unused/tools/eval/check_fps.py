import sys
sys.path.insert(0, "/t")
import run_grid as G
h = dict(zone=0.4, reach=0.3, v_min=0.1, min_win=0.12, c_min=0.5, window=5, cross_w=1.0, threshold=3.0, confirm_frames=4, vanish_frames=3, vanish_bonus=2.0, born_bonus=2.0)
for det in ("yolo", "lite0"):
    for div, label in ((1, "5fps"), (2, "2.5fps")):
        for name, hh in (("現行", h), ("frames 短め(c3 v2)", {**h, "confirm_frames": 3, "vanish_frames": 2})):
            tot, per = G.evaluate(det, 0.25, div, anchor="bottom_center", method="heading", heading=hh)
            print(det, label, name, tuple(tot), per)
