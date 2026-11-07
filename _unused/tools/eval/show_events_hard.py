import sys, yaml
sys.path.insert(0, "/t")
import evalcore as E
from check_hard import LINES
cfg = yaml.safe_load(open("/config/matrix.yaml"))["aggregator"]
d, fr = E.load(f"/o/{sys.argv[1]}.json", float(sys.argv[2]))
h = {**cfg["heading"], "exit_all": True}
ev, _ = E.run(d, fr, LINES, method="heading", heading=h, edge=cfg.get("edge_margin", 0.0))
last = {}
for e in ev:
    mark = ""
    if e[2] in last and e[0] - last[e[2]][0] <= 8: mark = f"  ← 同じ ID #{e[2]} が {e[0]-last[e[2]][0]:.1f} 秒前にも（{last[e[2]][1]} {last[e[2]][2]}）"
    last[e[2]] = (e[0], e[1], e[3])
    print(e, mark)
