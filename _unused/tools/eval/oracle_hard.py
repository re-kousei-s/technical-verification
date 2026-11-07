"""上限の確認：正解の通過ごとに、前後の数秒に、足元が線1 の側を入れ替えた追跡が、そもそもあったか（幾何だけで見て）。"""
import json, sys
import numpy as np
sys.path.insert(0, "/t")
import evalcore as E
from check_hard import LINES
from aggregator.counter import CameraCounter
truth = json.load(open("/t/hard_truth.json"))["events"]
name = sys.argv[1]
d, fr = E.load(f"/o/{name}.json", 0.1)
c = CameraCounter(LINES, d["w"], d["h"], json.loads(json.dumps(E.TRACKERS["lowfps"])), d["fps"], "bottom_center", 0.0, 0.0, 1.5, "episode", {})
g = c.gates[0]
ser = {}
for k, m in enumerate(E.messages(d, fr)):
    tr = c.process(m)
    t = k / d["fps"]
    for i in range(len(tr)):
        tid = int(tr.tracker_id[i]); x1, y1, x2, y2 = tr.xyxy[i]; h = y2 - y1
        pt = np.array([(x1 + x2) / 2, y2])
        if g._span(pt, h):
            ser.setdefault(tid, []).append((t, float(np.dot(pt - g.a, g.n)) / h))
cross = []  # (時刻, 向き, ID)
for tid, v in ser.items():
    for (t0, s0), (t1, s1) in zip(v, v[1:]):
        if s0 * s1 < 0 and t1 - t0 < 1.5:
            cross.append(((t0 + t1) / 2, "in" if s1 > s0 else "out", tid))
hit = 0
for tr in truth:
    ok = [c_ for c_ in cross if c_[1] == tr["dir"] and -1.5 <= c_[0] - tr["t"] <= 2.0]
    near = [c_ for c_ in cross if -1.5 <= c_[0] - tr["t"] <= 2.0 and c_[1] != tr["dir"]]
    hit += bool(ok)
    print(f"{tr['t']:6.1f} {tr['dir']:3s} {'あり ' + str([(round(a,1), t) for a,_,t in ok]) if ok else ('なし（逆向きの越えはある ' + str([(round(a,1), t) for a,_,t in near]) + '）' if near else 'なし')}")
print(f"足元が線1 の側を入れ替えた追跡があった: {hit}/{len(truth)}　（線1 の越え全体: {len(cross)} 件）")
