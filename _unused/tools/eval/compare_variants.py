"""数え方の変更案を、4 本の動画（正解あり）と、最難関の動画（IN 12 / OUT 12）で、まとめて比べる（YOLOX-tiny・3fps・横 960）。
  python compare_variants.py [min_score]"""
import sys

import yaml

sys.path.insert(0, "/t")
import evalcore as E  # noqa: E402
import run_grid as G  # noqa: E402
from check_hard import LINES as HARD_LINES  # noqa: E402

ms = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3
cfg = yaml.safe_load(open("/config/matrix.yaml"))["aggregator"]
base = dict(cfg["heading"])
VARIANTS = {
    "いまの設定": {},
    "exit_all（足早に出た人も、待たずに確定）": {"exit_all": True},
    "exit_all + confirm_frames 3": {"exit_all": True, "confirm_frames": 3},
    "exit_all + born_bonus 2": {"exit_all": True, "born_bonus": 2.0},
}
for name, over in VARIANTS.items():
    h = {**base, **over}
    tot = [0, 0, 0]
    for v, (lines, truth) in G.VIDEOS.items():
        d, fr = E.load(f"/o/{v}.yx3.json", ms)
        ev, _ = E.run(d, fr, lines, method="heading", heading=h, edge=cfg.get("edge_margin", 0.0))
        tp, fp, fn = G.score(ev, truth)
        tot[0] += tp; tot[1] += fp; tot[2] += fn
    d, fr = E.load("/o/hard.yolox.json", ms)
    ev, _ = E.run(d, fr, HARD_LINES, method="heading", heading=h, edge=cfg.get("edge_margin", 0.0))
    i = sum(1 for e in ev if e[1] == "in")
    print(f"{name:42s} 4 本：合致 {tot[0]}/6 過検出 {tot[1]} 見逃し {tot[2]} ｜ 最難関：IN {i}/12 OUT {len(ev) - i}/12")
