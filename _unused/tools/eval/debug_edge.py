import sys
sys.path.insert(0, "/t")
import numpy as np
import evalcore as E
import run_grid as G
v, ms = sys.argv[1], float(sys.argv[2])
lines = G.VIDEOS[v][0]
d, frames = E.load(f"/o/{v}.lite0.json", ms)
from aggregator.counter import CameraCounter
trk = E.TRACKERS["lowfps"]
c = CameraCounter(lines, d["w"], d["h"], trk, d["fps"], "bottom_center", 0.0, 0.3, 1.5)
for k, m in enumerate(E.messages(d, frames)):
    tr = c.process(m)
    for i in range(len(tr)):
        x1, y1, x2, y2 = tr.xyxy[i]; pt = ((x1 + x2) / 2, y2); h = y2 - y1
        row = []
        for (nm, z), e in zip(c.zones, c.edges):
            dd = e._dist(pt); al = float(np.dot(np.asarray(pt) - e.a, e.u))
            row.append(f"{nm}:d={dd:5.0f},al={al:5.0f}/{e.length:4.0f}")
        print(f"{k/d['fps']:4.1f}s id{int(tr.tracker_id[i])} h={h:4.0f} pt=({pt[0]/d['w']:.2f},{pt[1]/d['h']:.2f}) " + " | ".join(row))
print("events", c.events)
