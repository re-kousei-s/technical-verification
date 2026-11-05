"""YOLOX を INT8 に量子化する（onnxruntime の静的量子化）。キャリブレーションは、現場に近い動画のフレームで行う。
  python quantize_yolox.py <入力 onnx> <出力 onnx> <入力の大きさ> <モード: qdq|qop|qdq_nohead> <動画...>
"""
import sys

import cv2
import numpy as np
from onnxruntime.quantization import CalibrationDataReader, QuantFormat, QuantType, quantize_static

src, dst, imgsz, mode, videos = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5:]


def prep(bgr):
    h, w = bgr.shape[:2]
    r = imgsz / max(h, w)
    nh, nw = int(round(h * r)), int(round(w * r))
    canvas = np.full((imgsz, imgsz, 3), 114, np.uint8)
    canvas[:nh, :nw] = cv2.resize(bgr, (nw, nh))
    return np.ascontiguousarray(canvas.transpose(2, 0, 1)[None].astype(np.float32))


class Reader(CalibrationDataReader):
    def __init__(self, per_video=40):
        self.items = []
        for v in videos:
            cap = cv2.VideoCapture(v)
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            for k in np.linspace(0, max(0, n - 1), per_video).astype(int):
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(k))
                ok, f = cap.read()
                if ok:
                    self.items.append(prep(f))
        self.it = iter(self.items)
        print(f"キャリブレーション画像 {len(self.items)} 枚")

    def get_next(self):
        x = next(self.it, None)
        return None if x is None else {"images": x}


exclude = []
if mode == "qdq_nohead":  # 出力に近い層（枠・物体らしさの推定）は、量子化の影響が大きいので、元の精度のまま
    import onnx
    m = onnx.load(src)
    exclude = [n.name for n in m.graph.node if n.op_type == "Conv" and any(t in n.name for t in ("head", "pred", "cls", "reg", "obj"))]
    print("除外する層", len(exclude))
quantize_static(
    src, dst, Reader(),
    quant_format=QuantFormat.QOperator if mode == "qop" else QuantFormat.QDQ,
    activation_type=QuantType.QUInt8, weight_type=QuantType.QInt8, per_channel=True,
    nodes_to_exclude=exclude,
)
print("書き出し", dst)
