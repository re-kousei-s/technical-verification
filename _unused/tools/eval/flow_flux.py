"""オプティカルフローで、線を横切る動きの量（流束）を、線ごと・フレームごとに測る（検出・追跡を使わない）。
3fps・横 960 のフレーム（本番と同じ）で、Farneback のフローを計算し、線の周りの帯の中で、線に垂直な成分（IN の向きが正）を合計する。
  python flow_flux.py <動画> <線の JSON> <出力 JSON> [帯の幅 px=40]"""
import json, sys
import cv2, numpy as np
video, lines_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
band = float(sys.argv[4]) if len(sys.argv) > 4 else 40.0
LINES = json.load(open(lines_path))
cap = cv2.VideoCapture(video)
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
step = max(1, round(fps / 3))
W, H = 960, None
masks, prev, res, i, k = None, None, {L["name"]: [] for L in LINES}, 0, 0
while True:
    ok, f = cap.read()
    if not ok: break
    if i % step == 0:
        if H is None:
            H = int(round(f.shape[0] * W / f.shape[1])) & ~1
            yy, xx = np.mgrid[0:H, 0:W]
            masks = []
            for L in LINES:
                a = np.array(L["line"][0]) * [W, H]; b = np.array(L["line"][1]) * [W, H]
                v = b - a; ln = np.hypot(*v); u = v / ln; n = np.array([v[1], -v[0]]) / ln
                al = (xx - a[0]) * u[0] + (yy - a[1]) * u[1]; d = (xx - a[0]) * n[0] + (yy - a[1]) * n[1]
                masks.append((L["name"], (al >= 0) & (al <= ln) & (np.abs(d) <= band), n, ln))
        g = cv2.cvtColor(cv2.resize(f, (W, H), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        if prev is not None:
            fl = cv2.calcOpticalFlowFarneback(prev, g, None, 0.5, 4, 21, 3, 5, 1.1, 0)
            for name, m, n, ln in masks:
                comp = fl[..., 0][m] * n[0] + fl[..., 1][m] * n[1]
                res[name].append([round(k / 3.0, 3), float(comp.sum() / ln), float(np.abs(comp).sum() / ln)])  # 時刻、流束（正＝IN の向き）、動きの量
        prev = g; k += 1
    i += 1
json.dump({"fps": 3.0, "band": band, "flux": res}, open(out, "w"))
print({k: len(v) for k, v in res.items()})
