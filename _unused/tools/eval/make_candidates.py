"""正解に無いのに数えた通過（数えすぎ）を、5 入力にわたって、まとめて、確認用の候補にする。 n＝その通過を数えた入力の数。"""
import json, os, sys
sys.path.insert(0, "/t")
import evalcore as E
import score_hard as H
from check_hard import LINES
from aggregator.counter import CameraCounter
p = json.loads(os.environ.get("P", "{}"))
cands = []
for name in ["hard.yolox", "hard_q5", "hard_q7", "hard_hi", "hard.rfdetr"]:
    d, fr = E.load(f"/o/{name}.json", 0.1)
    c = CameraCounter(LINES, d["w"], d["h"], json.loads(json.dumps(E.TRACKERS["lowfps"])), d["fps"], "bottom_center", 0.0, 0.0, 1.5, "episode", p)
    for m in E.messages(d, list(fr) + [[] for _ in range(20)]):
        c.process(m)
    ev = [(e[0], e[1], e[2], e[5], e[3] / d["w"], e[4] / d["h"]) for e in c.events]
    tp, extra, miss = H.score([(e[0], e[1], e[2], e[3]) for e in ev])
    ex = {(e[0], e[1], e[2], e[3]) for e in extra}
    for e in ev:
        if (e[0], e[1], e[2], e[3]) in ex:
            cands.append({"t": e[0], "dir": e[1], "line": e[3], "x": float(e[4]), "y": float(e[5])})
cands.sort(key=lambda c: (c["line"], c["dir"], c["t"]))
merged = []
for c in cands:
    if merged and merged[-1]["line"] == c["line"] and merged[-1]["dir"] == c["dir"] and c["t"] - merged[-1]["last"] <= 1.5:
        m = merged[-1]; m["n"] += 1; m["t"] += c["t"]; m["x"] += c["x"]; m["y"] += c["y"]; m["last"] = c["t"]
    else:
        merged.append({**c, "n": 1, "last": c["t"]})
out = [{"t": round(m["t"] / m["n"], 1), "dir": m["dir"], "line": m["line"], "x": round(m["x"] / m["n"], 3), "y": round(m["y"] / m["n"], 3), "n": m["n"]} for m in merged]
out.sort(key=lambda c: c["t"])
print(len(out), "件")
open("/o/candidates.json", "w").write(json.dumps(out, ensure_ascii=False))
