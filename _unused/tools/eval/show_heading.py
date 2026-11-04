import sys
sys.path.insert(0, "/t")
import evalcore as E
import run_grid as G
det = sys.argv[1]
h = dict(threshold=3, cross_w=1, confirm_frames=6, c_min=0.5, v_min=0.1, min_win=0.08)
for v, (lines, truth) in G.VIDEOS.items():
    d, fr = E.load(f"/o/{v}.{det}.json", 0.25)
    ev, _ = E.run(d, fr, lines, method="heading", heading=h)
    print(v[-9:], [(e[0], e[1], e[3]) for e in ev], "| 正解:", [(t[0], t[1], t[2], t[3]) for t in truth])
