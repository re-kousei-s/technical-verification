"""管理画面に出す「検出枠つきの画像」を描く。"""

import cv2
import supervision as sv

from aggregator.preview import draw_line
from common.tiling import line_to_px

class Annotator:
    def __init__(self):
        self._box = sv.BoxAnnotator(thickness=2)
        self._label = sv.LabelAnnotator(text_scale=0.5)

    def render(self, camera_id, frame, tracked, cam):
        """フレームに、検出枠・追跡ID・線を描き、JPEG（幅 800 まで縮小）にして返す。"""
        img = frame.copy()
        if len(tracked):
            shown = tracked[tracked.confidence >= 0.25]
            labels = [f"#{t}" if t >= 0 else "?" for t in shown.tracker_id]
            img = self._label.annotate(self._box.annotate(img, shown), shown, labels)

        # 線を全部描く。線が複数あるときは、始点のそばに番号を付ける（日本語は cv2 で描けないので、番号にしている）
        for i, item in enumerate(cam["lines"]):
            draw_line(img, item["line"], label=(i == 0))
            if len(cam["lines"]) > 1:
                (x1, y1), _ = line_to_px(item["line"], img.shape[1], img.shape[0])
                self._put_text(img, str(i + 1), (int(x1) + 8, int(y1) - 10), 1.1, color=(0, 200, 255))

        # IN/OUT の累計は、DB の値を管理画面のカードに出す（ここで数えた値は起動後だけの数で、リセットと食い違う）
        self._put_text(img, camera_id, (20, 50), 1.2)

        scale = 800 / img.shape[1]
        if scale < 1:
            img = cv2.resize(img, None, fx=scale, fy=scale)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None

    @staticmethod
    def _put_text(img, text, pos, scale, color=(255, 255, 255)):
        """黒の縁取りつきの文字（背景が明るくても暗くても読める）。"""
        cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 5)
        cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2)
