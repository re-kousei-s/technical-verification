"""管理画面に出す「検出枠つきの画像」を描く（① 検出が、約 1 秒に 1 回）。枠・線・判定のタイルを描く。"""

import cv2
import numpy as np

from aggregator.preview import draw_line
from aggregator.tile_judge import LineTiles
from common.tiling import line_to_px

TILE_COLOR = {1: (80, 200, 80), -1: (0, 140, 255)}  # IN 側は緑、OUT 側は橙（BGR）


class Annotator:
    def __init__(self, tiles_cfg=None):
        self.tiles_cfg = {k: v for k, v in (tiles_cfg or {}).items() if k in ("cols", "rows", "depth", "gap", "extend")}

    def render(self, camera_id, frame, dets, cam):
        """フレームに、検出枠（スコア 0.25 以上）・タイル・線を描き、JPEG（幅 800 まで縮小）にして返す。dets は [[x1, y1, x2, y2, スコア], ...]。"""
        img = frame.copy()
        h, w = img.shape[:2]
        for x1, y1, x2, y2, s in dets:
            if s >= 0.25:
                cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (255, 200, 0), 2)

        for i, item in enumerate(cam["lines"]):
            tiles = LineTiles(*line_to_px(item["line"], w, h), **self.tiles_cfg, unit=h)
            for side in (1, -1):
                for row in range(tiles.rows):
                    for col in range(tiles.cols):
                        pts = [(int(p[0]), int(p[1])) for p in tiles.corners(side, row, col)]
                        cv2.polylines(img, [np.array(pts, np.int32)], True, TILE_COLOR[side], 1)
            draw_line(img, item["line"], label=(i == 0))
            if len(cam["lines"]) > 1:  # 線が複数あるときは、始点のそばに番号を付ける（日本語は cv2 で描けないので、番号）
                (x1, y1), _ = line_to_px(item["line"], w, h)
                self._put_text(img, str(i + 1), (int(x1) + 8, int(y1) - 10), 1.1, color=(0, 200, 255))

        self._put_text(img, camera_id, (20, 50), 1.2)
        scale = 800 / w
        if scale < 1:
            img = cv2.resize(img, None, fx=scale, fy=scale)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None

    @staticmethod
    def _put_text(img, text, pos, scale, color=(255, 255, 255)):
        """黒の縁取りつきの文字（背景が明るくても暗くても読める）。"""
        cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 5)
        cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2)
