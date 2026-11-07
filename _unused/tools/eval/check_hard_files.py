import sys, yaml
sys.path.insert(0, "/t")
import evalcore as E
from check_hard import LINES
cfg = yaml.safe_load(open("/config/matrix.yaml"))["aggregator"]
for name in sys.argv[1:]:
    for ms in (0.25, 0.3):
        d, fr = E.load(f"/o/{name}.json", ms)
        ev, _ = E.run(d, fr, LINES, method="heading", heading=cfg["heading"], edge=cfg.get("edge_margin", 0.0))
        i = sum(1 for e in ev if e[1] == "in")
        print(f"{name:12s} min_score={ms}: IN {i} / OUT {len(ev) - i}")
