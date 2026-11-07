"""数え方の設定を、「検出の揺れ」に強いかで選ぶ：最難関の動画を、4 種類の入力（生・H.264→JPEG 品質 5/7・4Mbps）× min_score 2 種で数え、
IN 12 / OUT 12 からのずれの合計が小さい設定を選ぶ。4 本の動画（正解あり）は、6/6 を保つこと。"""
import itertools
import sys

import yaml

sys.path.insert(0, "/t")
import evalcore as E  # noqa: E402
import run_grid as G  # noqa: E402
from check_hard import LINES  # noqa: E402

cfg = yaml.safe_load(open("/config/matrix.yaml"))["aggregator"]
base = dict(cfg["heading"])
SETS = ["hard.yolox", "hard_q5", "hard_q7", "hard_hi", "hard.rfdetr"]
data = {(s, ms): E.load(f"/o/{s}.json", ms) for s in SETS for ms in (0.25, 0.3)}
vids = {v: E.load(f"/o/{v}.yx3.json", 0.3) for v in G.VIDEOS}
import os
grid = eval(os.environ.get("GRID", '{"threshold": [2.5, 3.0], "confirm_frames": [3, 4], "born_bonus": [2.0, 3.0], "v_min": [0.08, 0.1], "min_win": [0.08, 0.12]}'))
rows = []
for combo in itertools.product(*grid.values()):
    h = {**base, "exit_all": True, **dict(zip(grid, combo))}
    dev, ins = 0, []
    for key, (d, fr) in data.items():
        ev, _ = E.run(d, fr, LINES, method="heading", heading=h, edge=cfg.get("edge_margin", 0.0))
        i = sum(1 for e in ev if e[1] == "in"); o = len(ev) - i
        dev += abs(i - 12) + abs(o - 12); ins.append(f"{i}/{o}")
    tp = 0
    for v, (lines, truth) in G.VIDEOS.items():
        d, fr = vids[v]
        ev, _ = E.run(d, fr, lines, method="heading", heading=h, edge=cfg.get("edge_margin", 0.0))
        tp += G.score(ev, truth)[0]
    rows.append((dev, -tp, combo, " ".join(ins)))
rows.sort()
print("ずれの合計（小さいほど良い） / 4本の合致 / 設定", list(grid))
for dev, ntp, combo, ins in rows[:8]:
    print(dev, -ntp, combo, ins)
print("--- いまの設定")
for dev, ntp, combo, ins in rows:
    if combo == (3.0, 4, 3.0, 0.1, 0.12): print(dev, -ntp, combo, ins)
