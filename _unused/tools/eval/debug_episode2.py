import json, sys
sys.path.insert(0, "/t")
import numpy as np
import evalcore as E
import run_grid as G
from aggregator.counter import CameraCounter
v = sys.argv[1]; lines, truth = G.VIDEOS[v]
d, fr = E.load(f"/o/{v}.yx3.json", 0.3)
c = CameraCounter(lines, d["w"], d["h"], json.loads(json.dumps(E.TRACKERS["lowfps"])), d["fps"], "bottom_center", 0.0, 0.0, 1.5, "episode", {})
g = c.gates[int(sys.argv[2])]
for k, m in enumerate(E.messages(d, fr)):
    tr = c.process(m)
    row = []
    for i in range(len(tr)):
        tid = int(tr.tracker_id[i]); x1, y1, x2, y2 = tr.xyxy[i]; h = y2 - y1
        pt = np.array([(x1 + x2) / 2, y2]); s = float(np.dot(pt - g.a, g.n)) / h
        st = g.tracks[tid]
        row.append(f"#{tid} s={s:+.2f} side={st.side:+d} sp={int(g._span(pt, h))} bn={int(st.born_near)}")
    print(f"t={k / d['fps']:4.1f}", " | ".join(row))
print("events", [(round(e[0], 1), e[1], e[2]) for e in c.events])
