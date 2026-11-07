import json, os, sys
sys.path.insert(0, "/t")
import evalcore as E
import score_hard as H
from check_hard import LINES
p = json.loads(os.environ.get("P", "{}"))
for name in sys.argv[1:]:
    d, fr = E.load(f"/o/{name}.json", 0.1)
    ev, _ = E.run(d, fr, LINES, method="episode", heading=p, pad=20)
    tp, extra, miss = H.score(ev)
    print(name, "合致", tp, "| 数えすぎ", len(extra), ":", [(e[0], e[1], e[2], e[3][-1]) for e in extra])
    print("   数え漏れ:", [(m["t"], m["dir"]) for m in miss])
