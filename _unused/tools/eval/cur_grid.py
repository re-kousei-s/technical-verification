"""いま、管理画面に置いてある線（LINES_JSON）で、設定の組み合わせを、まとめて採点する（合致・数えすぎ・数え漏れを、向きごと）。  環境変数 GRID に、設定の候補（JSON）を入れる。"""
import itertools, json, math, os, sys
sys.path.insert(0, "/t")
import evalcore as E
import score_hard as H
LINES = json.load(open(os.environ["LINES_JSON"]))
grid = json.loads(os.environ["GRID"])
def dist(pt, ab):
    ax, ay, bx, by, px, py = ab[0][0] * 16, ab[0][1] * 9, ab[1][0] * 16, ab[1][1] * 9, pt[0] * 16, pt[1] * 9
    dx, dy = bx - ax, by - ay; t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
for t in H.truth: t["line"] = min(LINES, key=lambda L: dist((t["x"], t["y"]), L["line"]))["name"]
SETS = ["hard.yolox", "hard_q5", "hard_q7", "hard_hi", "hard.rfdetr"]
data = {s: E.load(f"/o/{s}.json", 0.1) for s in SETS}
rows = []
for combo in itertools.product(*grid.values()):
    p = dict(zip(grid, combo))
    mi = mo = ei = eo = 0
    for s in SETS:
        d, fr = data[s]
        ev, _ = E.run(d, fr, LINES, method="episode", heading=p, pad=20)
        tp, ex, ms = H.score(ev)
        for x in ex: ei += x[1] == "in"; eo += x[1] == "out"
        for m in ms: mi += m["dir"] == "in"; mo += m["dir"] == "out"
    hits = 120 - mi - mo
    rows.append((-(hits - 0.5 * (ei + eo)), hits, ei + eo, mi, mo, ei, eo, p))
rows.sort(key=lambda r: r[0])
print("合致 / 数えすぎ | IN 漏れ OUT 漏れ | IN 過 OUT 過 | 設定")
for _, hits, fp, mi, mo, ei, eo, p in rows[:int(os.environ.get("TOP", "8"))]:
    print(f"{hits:3d} {fp:3d} | {mi:2d} {mo:2d} | {ei:2d} {eo:2d} | {p}")
