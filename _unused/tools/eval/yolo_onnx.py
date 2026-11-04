"""YOLOv8（ONNX）で、人（COCO の class 0）だけを検出する。CPU の onnxruntime。評価用。"""
import cv2
import numpy as np
import onnxruntime as ort


class YoloOnnx:
    def __init__(self, path, imgsz, conf=0.1, iou=0.5, threads=2):
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
        self.name = self.sess.get_inputs()[0].name
        self.imgsz, self.conf, self.iou = imgsz, conf, iou

    def detect(self, bgr):
        h, w = bgr.shape[:2]
        r = self.imgsz / max(h, w)  # 長い辺を imgsz に合わせて、余白を足す（letterbox）
        nh, nw = int(round(h * r)), int(round(w * r))
        img = cv2.resize(bgr, (nw, nh))
        canvas = np.full((self.imgsz, self.imgsz, 3), 114, np.uint8)
        canvas[:nh, :nw] = img
        x = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        out = self.sess.run(None, {self.name: np.ascontiguousarray(x)})[0][0]  # (84, N)
        out = out.T  # (N, 84): cx, cy, w, h, 80 クラス
        scores = out[:, 4]  # class 0 = person
        keep = scores >= self.conf
        out, scores = out[keep], scores[keep]
        if not len(out):
            return np.zeros((0, 4), np.float32), np.zeros(0, np.float32)
        boxes = np.stack([out[:, 0] - out[:, 2] / 2, out[:, 1] - out[:, 3] / 2, out[:, 0] + out[:, 2] / 2, out[:, 1] + out[:, 3] / 2], 1) / r
        idx = cv2.dnn.NMSBoxes([[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes], scores.tolist(), self.conf, self.iou)
        idx = np.array(idx).reshape(-1)
        return boxes[idx].astype(np.float32), scores[idx].astype(np.float32)
