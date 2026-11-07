import json, os, sys
sys.path.insert(0, "/t")
import evalcore as E
import run_grid as G
p = json.loads(os.environ.get("P", "{}"))
for v, (lines, truth) in G.VIDEOS.items():
    d, fr = E.load(f"/o/{v}.yx3.json", 0.3)
    ev, tr = E.run(d, fr, lines, method="episode", heading=p, pad=20)
    print(v[-9:], "出力:", [(e[0], e[1], e[2], e[3]) for e in ev], "\n          正解:", truth)
