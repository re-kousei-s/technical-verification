import sys
sys.path.insert(0, "/t")
import evalcore as E
import run_grid as G
det, ms, edge = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
for v, (lines, truth) in G.VIDEOS.items():
    d, frames = E.load(f"/o/{v}.{det}.json", ms)
    ev, _ = E.run(d, frames, lines, edge=edge)
    print(v[-9:], "events:", ev, "| truth:", [(t[0], t[1]) for t in truth])
