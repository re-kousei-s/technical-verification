import json, os, sys
sys.path.insert(0, "/t")
import evalcore as E
import score_hard as H
from check_hard import LINES
from aggregator.counter import CameraCounter
p = json.loads(os.environ.get("P", "{}"))
name = sys.argv[1]
d, fr = E.load(f"/o/{name}.json", 0.1)
c = CameraCounter(LINES, d["w"], d["h"], json.loads(json.dumps(E.TRACKERS["lowfps"])), d["fps"], "bottom_center", 0.0, 0.0, 1.5, "episode", p)
for m in E.messages(d, list(fr) + [[] for _ in range(20)]):
    c.process(m)
ev = [(round(e[0], 1), e[1], e[2], e[5], round(e[3] / d["w"], 2), round(e[4] / d["h"], 2)) for e in c.events]
ev4 = [(e[0], e[1], e[2], e[3]) for e in ev]
tp, extra, miss = H.score([(e[0], e[1], e[2], e[3]) for e in ev])
ex = set((e[0], e[1], e[2]) for e in extra)
print("数えすぎ（時刻, 向き, ID, 線, x, y）")
for e in ev:
    if (e[0], e[1], e[2]) in ex: print("  ", e)
