"""検出に、小さなゆらぎを加えて、何回も採点する（もろさを測る）。決まった入力だけで採点すると、1 つの枠の有無で、結果が大きく変わるため。
  ゆらぎ：スコア 0.45 未満の枠を、DROP の割合で消す／座標を ±JIT 画素、スコアを ±0.03 ずらす。SEEDS 回 × 入力の数。
  GRID（設定の候補、JSON）・LINES_JSON・SETS は cur_grid.py と同じ。trk_ で始まる値は、追跡の設定。"""
import itertools, json, math, os, random, statistics, sys
sys.path.insert(0, "/t")
import evalcore as E
import score_hard as H
LINES = json.load(open(os.environ["LINES_JSON"]))
grid = json.loads(os.environ.get("GRID", "{}")) or {"_": [0]}
def dist(pt, ab):
    ax, ay, bx, by, px, py = ab[0][0] * 16, ab[0][1] * 9, ab[1][0] * 16, ab[1][1] * 9, pt[0] * 16, pt[1] * 9
    dx, dy = bx - ax, by - ay; t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
for t in H.truth: t["line"] = min(LINES, key=lambda L: dist((t["x"], t["y"]), L["line"]))["name"]
SETS = os.environ.get("SETS", "hard.yolox,hard_q5,hard_q7,hard_hi,hard.rfdetr,live1").split(",")
SEEDS, DROP, JIT = int(os.environ.get("SEEDS", "4")), float(os.environ.get("DROP", "0.15")), float(os.environ.get("JIT", "1.5"))
data = {s: E.load(f"/o/{s}.feat.json" if os.path.exists(f"/o/{s}.feat.json") else f"/o/{s}.json", 0.1) for s in SETS}
BASE = E.MATRIX["aggregator"]["episode"]

def perturb(frames, seed):
    if seed == 0:
        return frames  # 0 回目は、ゆらぎなし
    rnd = random.Random(seed)
    out = []
    for fr in frames:
        f2 = []
        for b in fr:
            if b[4] < 0.45 and rnd.random() < DROP:
                continue
            f2.append([b[0] + rnd.uniform(-JIT, JIT), b[1] + rnd.uniform(-JIT, JIT), b[2] + rnd.uniform(-JIT, JIT), b[3] + rnd.uniform(-JIT, JIT),
                       min(1, max(0.1, b[4] + rnd.uniform(-0.03, 0.03))), *b[5:]])
        out.append(f2)
    return out

print(f"入力 {len(SETS)} × ゆらぎ {SEEDS} 回（1 回目はゆらぎなし）。1 回あたり正解 24 件")
print("合致 平均 [最小〜最大] | 数えすぎ 平均 | ゆらぎなしの入力ごとの合致 | 設定")
rows = []
MISS, EXTRA = {}, {}
for combo in itertools.product(*grid.values()):
    p = {k: v for k, v in zip(grid, combo) if k != "_"}
    trk = {k[4:]: p.pop(k) for k in list(p) if k.startswith("trk_")}
    hits, fps, base = [], [], []
    for s in SETS:
        d, fr = data[s]
        for seed in range(SEEDS):
            ev, _ = E.run(d, perturb(fr, seed), LINES, method="episode", heading={**BASE, **p}, pad=20, tracker_over=trk)
            tp, ex, ms = H.score(ev)
            hits.append(tp); fps.append(len(ex))
            for m in ms: MISS[(round(m["t"], 1), m["dir"], m["line"])] = MISS.get((round(m["t"], 1), m["dir"], m["line"]), 0) + 1
            for e in ex: EXTRA[(e[1], e[3])] = EXTRA.get((e[1], e[3]), 0) + 1
            if seed == 0: base.append(tp)
    rows.append((statistics.mean(hits) - 0.5 * statistics.mean(fps), hits, fps, base, {**p, **{"trk_" + k: v for k, v in trk.items()}}))
rows.sort(key=lambda r: -r[0])
for _, hits, fps, base, p in rows[:int(os.environ.get("TOP", "10"))]:
    print(f"{statistics.mean(hits):5.2f} [{min(hits)}〜{max(hits)}] | {statistics.mean(fps):4.2f} | {base} | {p}")
if os.environ.get("DETAIL") == "1":  # 最後の設定の、通過ごとの、落ちた回数
    n = len(SETS) * SEEDS
    print(f"落ちた回数（{n} 回中）:")
    for k, v in sorted(MISS.items()):
        print(f"  {k[0]:5.1f} {k[1]:3s} {k[2]}  {v:2d}  {'#' * v}")
    print("数えすぎ（向き・線）:", sorted(EXTRA.items(), key=lambda kv: -kv[1]))
