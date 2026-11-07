"""新しい数え方（episode）を、最難関の動画（ユーザーの正解 26 件）× 5 種類の入力と、4 本の動画（正解 6 件）で採点する。
  python eval_episode.py                    … 既定の設定
  GRID='{"margin":[0.1,0.15],...}' python eval_episode.py   … 設定の組み合わせを、まとめて比べる"""
import itertools
import json
import os
import sys

sys.path.insert(0, "/t")
import evalcore as E  # noqa: E402
import run_grid as G  # noqa: E402
import score_hard as H  # noqa: E402
from check_hard import LINES  # noqa: E402

METHOD = os.environ.get("METHOD", "episode")
SETS = os.environ.get("SETS", "hard.yolox,hard_q5,hard_q7,hard_hi,hard.rfdetr").split(",")
_cache = {}


def load(name, ms):
    if (name, ms) not in _cache:
        _cache[(name, ms)] = E.load(name, ms)
    return _cache[(name, ms)]
grid = json.loads(os.environ.get("GRID", "{}")) or {"margin": [0.15]}


def run(params):
    params = dict(params)
    ms = params.pop("ms", 0.3)
    trk = {k[4:]: params.pop(k) for k in list(params) if k.startswith("trk_")}
    tp = fp = fn = 0
    per, cnt = [], []
    for s in SETS:
        d, fr = load(f"/o/{s}.json", ms)
        ev, _ = E.run(d, fr, LINES, method=METHOD, heading=params, pad=20, tracker_over=trk)
        t, extra, miss = H.score(ev)
        tp += t; fp += len(extra); fn += len(miss); per.append(t)
        ni = sum(1 for e in ev if e[1] == "in"); cnt.append((ni, len(ev) - ni))
    vt = vf = 0
    for v, (lines, truth) in G.VIDEOS.items():
        d, fr = load(f"/o/{v}.yx3.json", ms)
        ev, _ = E.run(d, fr, lines, method=METHOD, heading=params, pad=20, tracker_over=trk)
        a, b, c = G.score(ev, truth)
        vt += a; vf += b
    return tp, fp, fn, per, vt, vf, cnt


rows = []
for combo in itertools.product(*grid.values()):
    p = dict(zip(grid, combo))
    tp, fp, fn, per, vt, vf, cnt = run(p)
    dev = sum(abs(i - 12) + abs(o - 12) for i, o in cnt)  # 総数の、12 / 12 からのずれ（5 入力の合計）
    rows.append((dev, p, tp, fp, fn, per, vt, vf, cnt))
rows.sort(key=lambda r: (r[0] - (r[2] - r[3]) * float(os.environ.get("W", "0")), -r[6]) if os.environ.get("BY") == "count" else (-r[2] + r[3], -r[6]))
print("5 入力の合計（正解 130 件）： 合致 / 数えすぎ / 数え漏れ ｜ 入力ごとの合致 ｜ 4 本（正解 6）：合致 / 数えすぎ")
for dev, p, tp, fp, fn, per, vt, vf, cnt in rows[:int(os.environ.get("TOP", "10"))]:
    print(f"{tp:3d} {fp:3d} {fn:3d} | ずれ{dev:3d} {cnt} | {vt}/6 {vf} | {p}")
