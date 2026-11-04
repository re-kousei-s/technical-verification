"""検出器ごとに、数えの精度（正解 6 件。heading 方式の既定 / line 方式）を並べる。"""
import sys
sys.path.insert(0, "/t")
import run_grid as G
for det in sys.argv[1:]:
    for ms in (0.25, 0.4, 0.5):
        h = G.evaluate(det, ms, 1, anchor="bottom_center", method="heading", heading={})
        l = G.evaluate(det, ms, 1, anchor="bottom_center", edge=0.3)
        print(f"{det:7s} min_score={ms}  heading {tuple(h[0])} {h[1]}   line+edge {tuple(l[0])} {l[1]}")
