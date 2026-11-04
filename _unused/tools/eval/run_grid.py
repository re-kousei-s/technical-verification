"""数える条件を変えながら、4 本の動画で、正解（目で見て決めた通過）との合致を比べる。
  正解：V1＝A の扉から出る(OUT)→奥の階段の扉へ入る(IN) / V2＝B の扉へ入る(IN) / V3＝B の扉から出る(OUT) / V4＝階段の扉へ入る(IN)→出る(OUT)
  数え方：同じ線・向き・時間の窓（±）に入れば、合致。正解に無い通過は、過検出。
"""
import itertools
import sys

sys.path.insert(0, "/t")
import evalcore as E  # noqa: E402

O = "/o/"
HALL = [  # V1〜V3 は、同じ固定カメラ。A＝左のエレベーター、B＝中央のエレベーター、S＝奥の階段の扉
    {"id": "A", "name": "A", "line": [[0.24, 0.84], [0.44, 0.83]]},
    {"id": "B", "name": "B", "line": [[0.49, 0.72], [0.62, 0.70]]},
    {"id": "S", "name": "S", "line": [[0.68, 0.65], [0.82, 0.63]]},
]
STAIR = [{"id": "S", "name": "S", "line": [[0.70, 0.86], [0.98, 0.79]]}]
VIDEOS = {
    "PXL_20261030_032559675": (HALL, [("A", "out", 0.0, 6.0), ("S", "in", 6.5, 10.5)]),
    "PXL_20261030_032725923": (HALL, [("B", "in", 8.0, 12.4)]),
    "PXL_20261030_032742907": (HALL, [("B", "out", 1.5, 6.0)]),
    "PXL_20261027_064147198": (STAIR, [("S", "in", 2.4, 5.5), ("S", "out", 8.5, 11.8)]),
}


def score(events, truth):
    tp, used = 0, set()
    for (name, direc, a, b) in truth:
        for i, e in enumerate(events):
            if i not in used and e[3] == name and e[1] == direc and a <= e[0] <= b:
                tp += 1
                used.add(i)
                break
    return tp, len(events) - tp, len(truth) - tp  # 合致, 過検出, 見逃し


def evaluate(det, min_score, fps_div, tracker_over=None, **kw):
    tot = [0, 0, 0]
    per = []
    for v, (lines, truth) in VIDEOS.items():
        d, frames = E.load(f"{O}{v}.{det}.json", min_score)
        if fps_div > 1:
            frames, d = frames[::fps_div], {**d, "fps": d["fps"] / fps_div}
        ev, _ = E.run(d, frames, lines, tracker_over=tracker_over, **kw)
        s = score(ev, truth)
        per.append(s)
        tot = [x + y for x, y in zip(tot, s)]
    return tot, per


if __name__ == "__main__":
    det = sys.argv[1]
    rows = []
    for ms, anchor, edge, fdiv in itertools.product([0.2, 0.3, 0.4, 0.5], ["bottom_center", "center"], [0.0, 0.3, 0.5], [1, 2]):
        tot, per = evaluate(det, ms, fdiv, anchor=anchor, edge=edge)
        rows.append((tot[0] - tot[1] - tot[2] * 1.0, tot, ms, anchor, edge, 5 // fdiv if fdiv == 1 else 2.5, per))
    rows.sort(key=lambda r: -r[0])
    print(f"== {det}  (合致, 過検出, 見逃し) / 全 6 件")
    for r in rows[:8]:
        print(f"score={r[0]:+.0f} {tuple(r[1])} min_score={r[2]} anchor={r[3]} edge={r[4]} fps={r[5]}  per-video={r[6]}")
    print("-- 現在の設定（0.25 / bottom_center / edge 0.3 / 5fps）:", evaluate(det, 0.25, 1, anchor="bottom_center", edge=0.3))
    print("-- 際なし:", evaluate(det, 0.25, 1, anchor="bottom_center", edge=0.0)[0])
