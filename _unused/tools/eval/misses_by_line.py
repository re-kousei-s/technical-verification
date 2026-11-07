import json, os, sys
from collections import Counter
sys.path.insert(0, "/t")
import evalcore as E
import score_hard as H
from check_hard import LINES
p = json.loads(os.environ.get("P", "{}"))
m, e = Counter(), Counter()
for name in ["hard.yolox", "hard_q5", "hard_q7", "hard_hi", "hard.rfdetr"]:
    d, fr = E.load(f"/o/{name}.json", 0.1)
    ev, _ = E.run(d, fr, LINES, method="episode", heading=p, pad=20)
    tp, extra, miss = H.score(ev)
    for t in miss: m[(t["line"], t["dir"])] += 1
    for x in extra: e[(x[3], x[1])] += 1
print("数え漏れ（5 入力の合計）", sorted(m.items()))
print("数えすぎ（5 入力の合計）", sorted(e.items()))
tm = Counter((t["line"], t["dir"]) for t in H.truth)
print("正解（1 入力あたり）", sorted(tm.items()))
