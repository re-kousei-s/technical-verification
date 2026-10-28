"""動画の読み込みと、フレームの間引き。

検出は「複数の間引き条件の和集合」のフレームにだけ1回ずつ行い、
各フレームがどの間引き条件に含まれるかを一緒に返す（同じフレームを何度も推論しない）。
"""

import cv2


def video_info(path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(path)
    info = {
        "w": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "h": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": cap.get(cv2.CAP_PROP_FPS) or 30.0,
        "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
    }
    cap.release()
    return info


def iter_sampled_frames(path, fps_list):
    """(frame_idx, t_sec, frame_bgr, 含まれる間引き条件の集合) を返す。

    fps=0 は全フレーム。それ以外は 1/fps 秒ごとに、その時刻以降で最初のフレームを採る。
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    next_k = {f: 0 for f in fps_list if f}  # 次に採る k（時刻 k/fps）
    eps = 0.5 / src_fps
    idx = -1
    while cap.grab():
        idx += 1
        msec = cap.get(cv2.CAP_PROP_POS_MSEC)
        t = msec / 1000.0 if (msec > 0 or idx == 0) else idx / src_fps
        hit = {f for f in fps_list if not f}
        for f in next_k:
            if t + eps >= next_k[f] / f:
                hit.add(f)
                # 長く飛んだ場合も、時刻の格子からずれないように進める
                while next_k[f] / f <= t + eps:
                    next_k[f] += 1
        if not hit:
            continue
        ok, frame = cap.retrieve()
        if not ok:
            break
        yield idx, t, frame, hit
    cap.release()


def read_frames_at(path, times_sec):
    """指定時刻に最も近いフレームを返す（正解人数との比較用）。"""
    cap = cv2.VideoCapture(str(path))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    for t in times_sec:
        idx = int(round(t * src_fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if ok:
            yield t, idx, frame
    cap.release()
