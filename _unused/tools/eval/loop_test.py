"""動画を、くり返し再生したときの数え方（送信ページの動画は、くり返し再生される）。"""
import os
import sys

sys.path.insert(0, "/t")
import evalcore as E  # noqa: E402
from user_lines import LINES  # noqa: E402

for v in sys.argv[1:]:
    d, fr = E.load(f"/o/{v}.{os.environ.get('DET', 'lite0')}.json", 0.25)
    n = len(fr)
    for method in ("line", "heading"):
        ev, _ = E.run(d, fr * 4, LINES, edge=0.3, method=method)
        loop = n / d["fps"]
        # 1 周目と、全体の件数だけ出す（周ごとに同じなら、ぶれていない）
        first = [(round(e[0], 1), e[1], e[3]) for e in ev if e[0] < loop]
        print(v[-9:], f"{method:7s} 4 周で {len(ev)} 件 / 1 周目:", first)
