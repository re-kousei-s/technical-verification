"""最難関の動画を、ユーザーが付けた正解（hard_truth.json）で採点する。向きと時刻で合わせる（線は問わない）。
アルゴリズムの出力は、確定待ちのぶん遅れるので、正解の時刻の −1.5 秒〜＋3.0 秒を許す。  python score_hard.py [入力名...]"""
import json
import sys

import yaml

sys.path.insert(0, "/t")
import evalcore as E  # noqa: E402
from check_hard import LINES  # noqa: E402

import os
LO, HI = -1.5, float(os.environ.get("HI", "3.0"))  # 許す遅れ（秒）。HI を環境変数で変えられる
TMIN = float(os.environ.get("TMIN", "0"))  # この秒より前の出力は、採点しない（ラベルの無い区間）
LINEONLY = os.environ.get("LINEONLY", "")  # 指定した線だけで、採点する（正解も出力も、その線だけ）
LINEFREE = os.environ.get("LINEFREE") == "1"  # 1 なら、線は問わない
ONLY1 = os.environ.get("ONLY1") == "1"  # 線1 の出力だけを採点する（ラベルは線1 のみ）
truth = [t for t in json.load(open("/t/hard_truth.json"))["events"] if not LINEONLY or t["line"] == LINEONLY]


def score(events):
    events = [e for e in events if e[0] >= TMIN and (not ONLY1 or e[3] == "線1") and (not LINEONLY or e[3] == LINEONLY)]  # ONLY1 は、旧ラベル用
    used, miss = set(), []
    for tr in truth:
        hit = None
        for i, e in enumerate(events):
            if i not in used and e[1] == tr["dir"] and (e[3] == tr["line"] or LINEFREE) and LO <= e[0] - tr["t"] <= HI:
                hit = i
                break
        if hit is None:
            miss.append(tr)
        else:
            used.add(hit)
    extra = [e for i, e in enumerate(events) if i not in used]
    return len(truth) - len(miss), extra, miss


if __name__ == "__main__":
    cfg = yaml.safe_load(open("/config/matrix.yaml"))["aggregator"]
    for name in sys.argv[1:] or ["hard.yolox", "hard_q5", "hard_q7", "hard_hi", "hard.rfdetr"]:
        d, fr = E.load(f"/o/{name}.json", 0.3)
        ev, _ = E.run(d, fr, LINES, method="heading", heading=cfg["heading"], edge=cfg.get("edge_margin", 0.0))
        tp, extra, miss = score(ev)
        print(f"{name:12s} 合致 {tp}/{len(truth)}  数えすぎ {len(extra)}  数え漏れ {len(miss)}")
        if len(sys.argv) > 1:
            print("  数え漏れ:", [(m["t"], m["dir"]) for m in miss])
            print("  数えすぎ:", [(e[0], e[1], e[3]) for e in extra])
