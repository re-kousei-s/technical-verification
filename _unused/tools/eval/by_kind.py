"""通過の種類（cross / born / vanish）ごとに、正解と合ったもの・数えすぎを数える。"""
import json, os, sys
from collections import Counter
sys.path.insert(0, "/t")
import evalcore as E
import score_hard as H
from check_hard import LINES
from aggregator.counter import CameraCounter
p = json.loads(os.environ.get("P", "{}"))
ok, bad = Counter(), Counter()
for name in ["hard.yolox", "hard_q5", "hard_q7", "hard_hi", "hard.rfdetr"]:
    d, fr = E.load(f"/o/{name}.json", 0.1)
    c = CameraCounter(LINES, d["w"], d["h"], json.loads(json.dumps(E.TRACKERS["lowfps"])), d["fps"], "bottom_center", 0.0, 0.0, 1.5, os.environ.get("METHOD", "episode"), p)
    for m in E.messages(d, list(fr) + [[] for _ in range(20)]):
        c.process(m)
    ev = [(e[0], e[1], e[2], e[5]) for e in c.events]
    tp, extra, miss = H.score(ev)
    ex = {(e[0], e[1], e[2], e[3]) for e in extra}
    kinds = {n: g.kinds for (n, _), g in zip(c.zones, c.gates)}
    for e in ev:
        k = kinds[e[3]].get((e[2], e[1]), "?")
        (bad if e in ex else ok)[(k, e[1])] += 1
print("種類 向き: 合致 / 数えすぎ")
for k in sorted(set(list(ok) + list(bad))):
    print(f"  {k[0]:7s}{k[1]:4s}: {ok[k]:3d} / {bad[k]:3d}")
