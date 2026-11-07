"""動画の確認用の画像：一定間隔のフレームに、線（赤＝線1、黄＝線2）と時刻を重ねて、並べる。正解を、目で作るため。
  python make_sheets.py <動画> <出力フォルダ> [間隔秒=1.0] [1 枚のコマ数=9] [開始秒] [終了秒]"""
import sys

import cv2
import numpy as np

video, out = sys.argv[1], sys.argv[2]
step = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
per = int(sys.argv[4]) if len(sys.argv) > 4 else 9
t0 = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0
t1 = float(sys.argv[6]) if len(sys.argv) > 6 else 1e9
LINES = [((0.5555, 0.5068), (0.1397, 1.0), (0, 0, 255)), ((0.6522, 0.4482), (0.5873, 0.5377), (0, 220, 255))]
cap = cv2.VideoCapture(video)
fps = cap.get(cv2.CAP_PROP_FPS)
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
dur = n / fps
W = 600
tiles, k, t = [], 0, t0
while t < min(dur, t1):
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, f = cap.read()
    if not ok:
        break
    h, w = f.shape[:2]
    f = cv2.resize(f, (W, int(h * W / w)))
    hh = f.shape[0]
    for a, b, col in LINES:
        cv2.line(f, (int(a[0] * W), int(a[1] * hh)), (int(b[0] * W), int(b[1] * hh)), col, 2)
    cv2.putText(f, f"{t:5.1f}s", (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 3)
    cv2.putText(f, f"{t:5.1f}s", (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 1)
    tiles.append(f)
    if len(tiles) == per:
        cols = 3
        rows = [np.hstack(tiles[i:i + cols]) for i in range(0, per, cols)]
        cv2.imwrite(f"{out}/sheet_{k:02d}.jpg", np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 80])
        tiles, k = [], k + 1
    t += step
if tiles:
    while len(tiles) % 3:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)]
    cv2.imwrite(f"{out}/sheet_{k:02d}.jpg", np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 80])
