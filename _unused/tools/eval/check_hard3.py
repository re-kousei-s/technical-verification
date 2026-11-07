"""指定した追跡 ID の、時刻ごとの足元・線との距離（枠の高さ比）・スコアを出す。  python check_hard3.py <ID>,<ID> [線の名前]"""
import json
import sys

import numpy as np
import yaml

sys.path.insert(0, "/t")
import evalcore as E  # noqa: E402
from check_hard import LINES  # noqa: E402
from aggregator.counter import CameraCounter  # noqa: E402

cfg = yaml.safe_load(open("/config/matrix.yaml"))["aggregator"]
want = {int(x) for x in sys.argv[1].split(",")}
line = sys.argv[2] if len(sys.argv) > 2 else "線1"
d, fr = E.load("/o/hard.yolox.json", 0.3)
c = CameraCounter(LINES, d["w"], d["h"], json.loads(json.dumps(E.TRACKERS["lowfps"])), d["fps"], "bottom_center", 0.0, cfg.get("edge_margin", 0.0), 1.5, "heading", dict(cfg["heading"]))
gi = [n for n, _ in c.zones].index(line)
g = c.gates[gi]
for k, m in enumerate(E.messages(d, fr)):
    tr = c.process(m)
    for i in range(len(tr)):
        tid = int(tr.tracker_id[i])
        if tid not in want:
            continue
        x1, y1, x2, y2 = tr.xyxy[i]
        h = y2 - y1
        pt = np.array([(x1 + x2) / 2, y2])
        dist = float(np.dot(pt - g.a, g.n)) / h
        st = g.tracks.get(tid)
        print(f"#{tid} t={k / d['fps']:5.1f} 足元=({pt[0]/d['w']:.2f},{pt[1]/d['h']:.2f}) 高さ={h:4.0f} d/h={dist:+.2f} score={st.score:+.1f} inz={int(st.inz)} min_d/h={st.min_d / h:.2f} counted={st.counted} pend={st.pending}")
