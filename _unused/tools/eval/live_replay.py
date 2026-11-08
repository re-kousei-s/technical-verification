"""ライブで記録した検出結果（worker の RECORD_DIR）を、追跡・人の状態管理・判定だけ、オフラインで再生して、採点する。
画像は使わない（検出と服の色は、記録したものをそのまま使う）。なので、追跡・判定の変更を、ライブと同じ入力で比べられる。

  python live_replay.py <記録.jsonl> [回の番号]
    LINES_JSON … 線（既定 /s/lines_now.json）   P … 設定の上書き（JSON）
    回の区切り … 5 秒以上、フレームが来ない所。回の番号を省くと、最後の回。
採点は、正解 24 件（hard_truth.json）と、時刻のずれ（動画の 0 秒が、記録のどこか）を、合致が最大になるように探して、合わせる。"""
import json
import math
import os
import sys

sys.path.insert(0, "/t")
import evalcore as E  # noqa: E402
import score_hard as H  # noqa: E402
from aggregator.counter import CameraCounter  # noqa: E402

rows = [json.loads(line) for line in open(sys.argv[1])]
runs, cur = [], []
for r in rows:
    if cur and r["ts_ms"] - cur[-1]["ts_ms"] > 5000:
        runs.append(cur)
        cur = []
    cur.append(r)
runs.append(cur)
for i, run in enumerate(runs):
    print(f"回 {i}: {len(run)} フレーム  {(run[-1]['ts_ms'] - run[0]['ts_ms']) / 1000:.0f} 秒")
run = runs[int(sys.argv[2]) if len(sys.argv) > 2 else -1]

if os.environ.get("SKIP_STILL") == "1":  # 送り始めの、止まった映像（同じコマの繰り返し）を除く
    k = 0
    while k + 1 < len(run) and [b[:5] for b in run[k + 1]["dets"]] == [b[:5] for b in run[0]["dets"]]:
        k += 1
    run = run[k:]
if os.environ.get("UNIFORM") == "1":  # 時刻を、ちょうど 1/3 秒おきに並べ直す（届いた時刻のゆらぎを除く）
    run = [{**r, "ts_ms": run[0]["ts_ms"] + round(i * 1000 / 3)} for i, r in enumerate(run)]

LINES = json.load(open(os.environ.get("LINES_JSON", "/s/lines_now.json")))


def dist(pt, ab):
    ax, ay, bx, by, px, py = ab[0][0] * 16, ab[0][1] * 9, ab[1][0] * 16, ab[1][1] * 9, pt[0] * 16, pt[1] * 9
    dx, dy = bx - ax, by - ay
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


for t in H.truth:
    t["line"] = min(LINES, key=lambda L: dist((t["x"], t["y"]), L["line"]))["name"]

params = {**E.MATRIX["aggregator"]["episode"], **json.loads(os.environ.get("P", "{}"))}
trk = json.loads(json.dumps(E.TRACKERS["lowfps"]))
w, h = run[0]["w"], run[0]["h"]
c = CameraCounter(LINES, w, h, trk, 3.0, method="episode", heading=params)
t0 = run[0]["ts_ms"]
pad = [{"ts_ms": run[-1]["ts_ms"] + 333 * (k + 1), "dets": []} for k in range(20)]
for r in run + pad:
    sec = (r["ts_ms"] - t0) / 1000
    c.process({"ts": "2026-11-04T10:%02d:%09.6f+09:00" % (int(sec // 60), sec % 60),
               "detections": [{"x": b[0], "y": b[1], "w": b[2] - b[0], "h": b[3] - b[1], "score": b[4], "feat": b[5]} for b in r["dets"]]})
ev = [(round(e[0], 1), e[1], e[2], e[5]) for e in c.events]

res = []
for k in range(-100, 401):  # 動画の 0 秒 ＝ 記録の開始から k/10 秒
    off = k / 10
    res.append((*H.score([(e[0] - off, *e[1:]) for e in ev]), off))
top = max(r[0] for r in res)
tp, ex, ms, off = [r for r in res if r[0] == top][len([r for r in res if r[0] == top]) // 2]  # 合致が最大の範囲の、真ん中
ni = sum(e[1] == "in" for e in ev)
print(f"数えた IN {ni} / OUT {len(ev) - ni}   合致 {tp}/24  数えすぎ {len(ex)}  （動画の 0 秒 ＝ 記録の {off:.1f} 秒）")
for m in ms:
    print(f"  漏れ   {m['t']:5.1f} {m['dir']:3s} {m['line']}")
for e in ex:
    print(f"  数えすぎ {e[0]:5.1f} {e[1]:3s} {e[3]} 人{e[2]}")
