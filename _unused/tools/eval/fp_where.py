"""数えすぎが、正解の位置（扉の近く 3 か所）から、どれくらい離れているか。"""
import json, math, os, sys
sys.path.insert(0, "/t")
import evalcore as E
import score_hard as H
from check_hard import LINES
from aggregator.counter import CameraCounter
p = json.loads(os.environ.get("P", "{}"))
CL = [(0.62, 0.49), (0.48, 0.60), (0.29, 0.82)]  # 正解のラベルの位置（クラスタの中心）
def dist(a, b): return math.hypot((a[0] - b[0]) * 16, (a[1] - b[1]) * 9) / 9  # 画面の高さを 1 とした距離
near = far = 0
far_list = []
for name in ["hard.yolox", "hard_q5", "hard_q7", "hard_hi", "hard.rfdetr"]:
    d, fr = E.load(f"/o/{name}.json", 0.1)
    c = CameraCounter(LINES, d["w"], d["h"], json.loads(json.dumps(E.TRACKERS["lowfps"])), d["fps"], "bottom_center", 0.0, 0.0, 1.5, os.environ.get("METHOD", "episode"), p)
    for m in E.messages(d, list(fr) + [[] for _ in range(20)]):
        c.process(m)
    ev = [(round(e[0], 1), e[1], e[2], e[5], e[3] / d["w"], e[4] / d["h"]) for e in c.events]
    tp, extra, miss = H.score([(e[0], e[1], e[2], e[3]) for e in ev])
    ex = {(e[0], e[1], e[2]) for e in extra}
    for e in ev:
        if (e[0], e[1], e[2]) in ex:
            dm = min(dist((e[4], e[5]), cl) for cl in CL)
            if dm <= 0.15: near += 1
            else: far += 1; far_list.append((name[-5:], e[0], e[1], e[3], round(e[4], 2), round(e[5], 2), round(dm, 2)))
print(f"数えすぎ：扉の近く（画面の高さの 0.15 以内）{near} 件、離れた場所 {far} 件")
for x in far_list[:16]: print("  離れた場所:", x)
