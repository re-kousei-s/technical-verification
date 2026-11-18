"""端末ごとの設定と、② 追跡・③ 判定の状態を持つ。

設定は数秒ごとに読み直す。線・fps が変わった端末は、追跡・判定を作り直す（ID は振り直しになるが、累計は DB に残る）。
"""

import json
import logging
import time

from aggregator.simple_tracker import SimpleTracker
from aggregator.tile_judge import TileJudge
from common.live import load_cameras, load_yaml
from libs.settings import CAMERAS_RELOAD_S, MATRIX

log = logging.getLogger("registry")


class CameraRegistry:
    def __init__(self):
        matrix = load_yaml(MATRIX)
        self.min_score = matrix["detector"]["min_score"]  # ① 検出が、検出器に渡す最低スコア
        self.tracker_cfg = matrix["aggregator"]["tracker"]  # ② 追跡の設定
        self.tiles_cfg = matrix["aggregator"]["tiles"]  # ③ 判定（タイル）の設定
        self.cameras = load_cameras()
        self._loaded_at = time.time()
        self._tracker = {}  # 端末ID → (追跡, 設定の印)
        self._judge = {}  # 端末ID → (判定, 設定の印)

    def get(self, camera_id):
        """端末の設定。未登録なら None。変更を拾うため、数秒ごとに設定を読み直す。"""
        if time.time() - self._loaded_at >= CAMERAS_RELOAD_S:
            self.cameras, self._loaded_at = load_cameras(), time.time()
        if camera_id not in self.cameras:
            self.cameras = load_cameras()  # 登録されたばかりの端末かもしれない
            if camera_id not in self.cameras:
                return None
        return self.cameras[camera_id]

    def tracker_for(self, camera_id, w, h):
        """② 追跡。fps・画面の大きさが変わったら作り直す。"""
        cam = self.cameras[camera_id]
        sig = (float(cam["sample_fps"]), w, h)
        state = self._tracker.get(camera_id)
        if state is None or state[1] != sig:
            if state is not None:
                log.info("設定が変わったので追跡を作り直す: %s", camera_id)
            state = self._tracker[camera_id] = (SimpleTracker(**self.tracker_cfg), sig)
        return state[0]

    def judge_for(self, camera_id, w, h):
        """③ 判定。線・画面の大きさが変わったら作り直す（踏んだ側の記憶は、リセットされる）。"""
        cam = self.cameras[camera_id]
        sig = (json.dumps(cam["lines"]), w, h)
        state = self._judge.get(camera_id)
        if state is None or state[1] != sig:
            if state is not None:
                log.info("線が変わったので判定を作り直す: %s", camera_id)
            state = self._judge[camera_id] = (TileJudge(cam["lines"], w, h, **self.tiles_cfg), sig)
        return state[0]
