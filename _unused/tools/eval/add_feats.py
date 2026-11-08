"""検出の JSON の各枠に、服の色のヒストグラム（胴体：枠の高さの 15〜55%、幅の中央 60%。HSV の色相 12 × 彩度 4、明るさが暗すぎる画素は除く）を足す。
枠は [x1, y1, x2, y2, スコア, 色の特徴(48)] になる。
  python add_feats.py <入力 JSON> <出力 JSON> <動画 または JPEG のフォルダ>"""
import glob, json, os, sys
import cv2, numpy as np
src, dst, media = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open(src)); W, H = d["w"], d["h"]
if os.path.isdir(media):
    files = sorted(glob.glob(media + "/*.jpg"))
    frames = (cv2.resize(cv2.imread(f), (W, H)) for f in files)
else:
    cap = cv2.VideoCapture(media); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; step = max(1, round(fps / d["fps"]))
    def gen():
        i = 0
        while True:
            ok, f = cap.read()
            if not ok: return
            if i % step == 0: yield cv2.resize(f, (W, H), interpolation=cv2.INTER_AREA)
            i += 1
    frames = gen()
def feat(img, b):
    x1, y1, x2, y2 = b[:4]; h, w = y2 - y1, x2 - x1
    xa, xb = int(max(0, x1 + 0.2 * w)), int(min(W, x2 - 0.2 * w)); ya, yb = int(max(0, y1 + 0.15 * h)), int(min(H, y1 + 0.55 * h))
    if xb - xa < 3 or yb - ya < 3: return None
    hsv = cv2.cvtColor(img[ya:yb, xa:xb], cv2.COLOR_BGR2HSV)
    mask = (hsv[..., 2] > 30).astype(np.uint8)
    hist = cv2.calcHist([hsv], [0, 1], mask, [12, 4], [0, 180, 0, 256]).flatten()
    s = hist.sum()
    return [round(float(v / s), 4) for v in hist] if s > 0 else None
out = []
for fr, img in zip(d["frames"], frames):
    out.append([b[:5] + ([feat(img, b)] if feat(img, b) is not None else []) for b in fr])
d["frames"] = out + d["frames"][len(out):]
json.dump(d, open(dst, "w"))
print(dst, len(out), "frames")
