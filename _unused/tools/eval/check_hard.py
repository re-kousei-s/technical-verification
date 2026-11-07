"""技術検証最難関の動画（IN 12 / OUT 12）を、本番と同じ設定で、数え直す。どの人（追跡 ID）が、いつ、どの線で数えられたかを出す。
  python check_hard.py [min_score]"""
import sys

import yaml

sys.path.insert(0, "/t")
import evalcore as E  # noqa: E402

LINES = [{"id": "l1", "name": "線1", "line": [[0.5555, 0.5068], [0.1397, 1]]},
         {"id": "l2", "name": "線2", "line": [[0.6522, 0.4482], [0.5873, 0.5377]]}]
if __name__ == "__main__":
    cfg = yaml.safe_load(open("/config/matrix.yaml"))["aggregator"]
    heading = cfg["heading"]
    ms = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3
    d, fr = E.load("/o/hard.yolox.json", ms)
    ev, tracks = E.run(d, fr, LINES, method="heading", heading=heading, edge=cfg.get("edge_margin", 0.0))
    i = sum(1 for e in ev if e[1] == "in"); o = len(ev) - i
    print(f"min_score={ms} IN={i} OUT={o}（正解 IN12 / OUT12）")
    for e in ev:
        print(e)
