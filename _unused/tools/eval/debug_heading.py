import sys
sys.path.insert(0, "/t")
import numpy as np
import evalcore as E
from user_lines import LINES
from aggregator.counter import CameraCounter
v, li, t0, t1 = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
d, fr = E.load(f"/o/{v}.lite0.json", 0.25)
c = CameraCounter(LINES, d["w"], d["h"], E.TRACKERS["lowfps"], d["fps"], "bottom_center", 0.0, 0.0, 1.5, "heading", None)
g = c.gates[li]
for k, m in enumerate(E.messages(d, fr)):
    tr = c.process(m)
    for i in range(len(tr)):
        tid = int(tr.tracker_id[i]); x1, y1, x2, y2 = tr.xyxy[i]; h = y2 - y1; pt = ((x1 + x2) / 2, y2)
        st = g.tracks.get(tid)
        if st and t0 <= k / d["fps"] <= t1:
            dd = float(np.dot(np.asarray(pt) - g.a, g.n))
            vn = (float(np.dot(st.vec, g.n)) / h) if st.vec is not None else 0.0
            print(f"{k/d['fps']:4.1f}s id{tid} h={h:4.0f} d={dd:6.0f} zone={g._zone(pt, dd, h)} score={st.score:4.1f} conf={st.conf:.2f} vn={vn:5.2f} min_d={st.min_d:5.0f} pend={st.pending} counted={st.counted}")
print(c.events)
