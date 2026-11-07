"""数えられなかった人を探す：人（追跡 ID）ごと・線ごとに、IN 側・OUT 側の最大スコアと、数えられたか、を出す。"""
import sys
from collections import defaultdict

import yaml

sys.path.insert(0, "/t")
import evalcore as E  # noqa: E402
from check_hard import LINES  # noqa: E402,F401
from aggregator.counter import CameraCounter  # noqa: E402
import json  # noqa: E402

cfg = yaml.safe_load(open("/config/matrix.yaml"))["aggregator"]
heading = dict(cfg["heading"])
for kv in sys.argv[2:]:
    k, v = kv.split("="); heading[k] = float(v)
ms = float(sys.argv[1])
d, fr = E.load("/o/hard.yolox.json", ms)
trk = json.loads(json.dumps(E.TRACKERS["lowfps"]))
c = CameraCounter(LINES, d["w"], d["h"], trk, d["fps"], "bottom_center", 0.0, cfg.get("edge_margin", 0.0), 1.5, "heading", heading)
agg = defaultdict(lambda: {"pos": 0.0, "neg": 0.0, "t0": 1e9, "t1": 0, "n": 0})
for k, m in enumerate(E.messages(d, fr)):
    c.process(m)
    for row in c.debug:
        tid, x, y, vx, vy, sp, lines = row
        for name, direction, score, inz, counted in lines:
            a = agg[(tid, name)]
            s = score * direction
            a["pos" if s > 0 else "neg"] = max(a["pos" if s > 0 else "neg"], abs(score)) if True else 0
            a["t0"] = min(a["t0"], k / d["fps"]); a["t1"] = max(a["t1"], k / d["fps"]); a["n"] += 1
counted = {(e[2], e[5]) for e in c.events}
ins = sum(1 for e in c.events if e[1] == "in")
print(f"IN={ins} OUT={len(c.events) - ins}")
print("追跡ID 線  最大IN側 最大OUT側 時間帯 数えた？（IN 側が 1.5 以上で、数えていない人だけ）")
for (tid, name), a in sorted(agg.items()):
    if (tid, name) in counted: continue
    if a["pos"] >= 1.5 or a["neg"] >= 1.5:
        print(f"#{tid:3d} {name} IN={a['pos']:.1f} OUT={a['neg']:.1f} {a['t0']:.1f}-{a['t1']:.1f}s n={a['n']}")
