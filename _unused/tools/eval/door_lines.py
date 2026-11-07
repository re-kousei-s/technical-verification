"""長い線1 を、扉ごとの短い線（D1・D2）に分けたとき、正解 24 件に対して、どうなるか。正解の線は、位置から、近い線に付け直す。"""
import json, math, os, sys
sys.path.insert(0, "/t")
import evalcore as E
import score_hard as H
p = json.loads(os.environ.get("P", "{}"))
A, B = (0.5555, 0.5068), (0.1397, 1.0)
def seg(t0, t1): return [[A[0] + (B[0] - A[0]) * t0, A[1] + (B[1] - A[1]) * t0], [A[0] + (B[0] - A[0]) * t1, A[1] + (B[1] - A[1]) * t1]]
HALF = float(os.environ.get("HALF", "0.12"))
LINES = [{"id": "d1", "name": "D1", "line": seg(0.18 - HALF, 0.18 + HALF)},
         {"id": "d2", "name": "D2", "line": seg(0.64 - HALF, 0.64 + HALF)},
         {"id": "l2", "name": "線2", "line": [[0.6522, 0.4482], [0.5873, 0.5377]]}]
def dist(pt, ab):
    ax, ay, bx, by, px, py = ab[0][0] * 16, ab[0][1] * 9, ab[1][0] * 16, ab[1][1] * 9, pt[0] * 16, pt[1] * 9
    dx, dy = bx - ax, by - ay; t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
for t in H.truth:  # 正解の線を、位置から、近い線に付け直す
    t["line"] = min(LINES, key=lambda L: dist((t["x"], t["y"]), L["line"]))["name"]
tp = fp = fn = 0
cnt = []
for name in ["hard.yolox", "hard_q5", "hard_q7", "hard_hi", "hard.rfdetr"]:
    d, fr = E.load(f"/o/{name}.json", 0.1)
    ev, _ = E.run(d, fr, LINES, method="episode", heading=p, pad=20)
    a, extra, miss = H.score(ev)
    tp += a; fp += len(extra); fn += len(miss)
    ni = sum(1 for e in ev if e[1] == "in"); cnt.append((ni, len(ev) - ni))
print(f"短い線（半幅 {HALF}）： 合致 {tp}/120  数えすぎ {fp}  数え漏れ {fn} | 入力ごとの (IN, OUT) {cnt}")
