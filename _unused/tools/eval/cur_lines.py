"""いま、管理画面に置いてある線（LINES_JSON）で、正解 24 件を、向きごとに採点する。正解の線は、位置から、近い線に付け直す。"""
import json, math, os, sys
from collections import Counter
sys.path.insert(0, "/t")
import evalcore as E
import score_hard as H
LINES = json.load(open(os.environ["LINES_JSON"]))
p = json.loads(os.environ.get("P", "{}"))
METHOD = os.environ.get("METHOD", "episode")
def dist(pt, ab):
    ax, ay, bx, by, px, py = ab[0][0] * 16, ab[0][1] * 9, ab[1][0] * 16, ab[1][1] * 9, pt[0] * 16, pt[1] * 9
    dx, dy = bx - ax, by - ay; t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
for t in H.truth: t["line"] = min(LINES, key=lambda L: dist((t["x"], t["y"]), L["line"]))["name"]
hit, extra, miss = Counter(), Counter(), Counter()
for name in os.environ.get("SETS", "hard.yolox,hard_q5,hard_q7,hard_hi,hard.rfdetr").split(","):
    d, fr = E.load(f"/o/{name}.json", 0.1)
    ev, _ = E.run(d, fr, LINES, method=METHOD, heading=p, pad=20)
    tp, ex, ms = H.score(ev)
    for x in ex: extra[x[1]] += 1
    for m in ms: miss[m["dir"]] += 1
    for k in ("in", "out"): hit[k] += sum(1 for t in H.truth if t["dir"] == k)
tot = {k: hit[k] for k in hit}
print(f"IN : 正解 {tot['in']}  数え漏れ {miss['in']}  数えすぎ {extra['in']}")
print(f"OUT: 正解 {tot['out']}  数え漏れ {miss['out']}  数えすぎ {extra['out']}")
