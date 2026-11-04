"""立ち止まっている人の、足元の点の、ぶれの大きさ（枠の高さに対する割合）を測る。v_min / min_win を決める根拠。
動画 2（…725923）で、人が、エレベーターのボタンを押して待っている区間（約 6.5〜9.5 秒）が、立ち止まりに当たる。"""
import sys
sys.path.insert(0, "/t")
import numpy as np
import evalcore as E
from user_lines import LINES

for det, ms in (("lite0", 0.25), ("rfdetr", 0.5)):
    d, fr = E.load(f"/o/PXL_20261030_032725923.{det}.json", ms)
    _, tracks = E.run(d, fr, LINES, method="line")
    # 追跡の点を、直接取り出す（E.run は、最初と最後しか持たないため、検出から再計算する）
    from aggregator.counter import CameraCounter
    c = CameraCounter(LINES, d["w"], d["h"], E.TRACKERS["lowfps"], d["fps"], "bottom_center", 0.0)
    rows = []
    for k, m in enumerate(E.messages(d, fr)):
        tr = c.process(m)
        for i in range(len(tr)):
            x1, y1, x2, y2 = tr.xyxy[i]
            rows.append((k / d["fps"], (x1 + x2) / 2, y2, y2 - y1))
    seg = [r for r in rows if 6.5 <= r[0] <= 9.5]
    if len(seg) < 4:
        print(det, "区間のデータが少ない", len(seg)); continue
    a = np.array(seg)
    h = a[:, 3].mean()
    step = np.hypot(np.diff(a[:, 1]), np.diff(a[:, 2])) / h  # 1 フレームあたりの動き（枠の高さ）
    print(f"{det}: 立ち止まり区間 {len(seg)} フレーム  1 フレームの動き 平均 {step.mean():.3f}h / 最大 {step.max():.3f}h  → 速さ {step.mean() * d['fps']:.2f}〜{step.max() * d['fps']:.2f} h/秒")
    # 歩いている区間（3〜6 秒）
    w = np.array([r for r in rows if 3.4 <= r[0] <= 6.0])
    if len(w) > 3:
        ws = np.hypot(np.diff(w[:, 1]), np.diff(w[:, 2])) / w[:, 3].mean()
        print(f"{det}: 歩いている区間 {len(w)} フレーム  1 フレームの動き 平均 {ws.mean():.3f}h  → 速さ 平均 {ws.mean() * d['fps']:.2f} h/秒")
