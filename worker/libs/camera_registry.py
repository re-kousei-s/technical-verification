"""端末ごとの設定と、追跡の状態（トラッカー・線）を持つ。"""

import json
import logging
import time

from aggregator.counter import CameraCounter
from common.live import load_cameras, load_yaml
from common.tiling import make_tiles
from libs.settings import CAMERAS_RELOAD_S, MATRIX

log = logging.getLogger("worker")


class CameraRegistry:
    """端末の設定（登録・線・ゲート・fps）を読み、端末ごとの追跡の状態を作って持つ。

    設定は数秒ごとに読み直す。線・fps・トラッカーが変わった端末は、追跡を作り直す
    （作り直すと追跡IDは振り直しになるが、累計は DB に残る）。
    """

    def __init__(self):
        matrix = load_yaml(MATRIX)
        self.min_score = matrix["detector"]["min_score"]  # 検出器に渡す最低スコア
        self.agg = matrix["aggregator"]
        self.trackers = {t["name"]: t for t in self.agg["trackers"]}  # トラッカー設定を名前で引く
        self.cameras = load_cameras()
        self._loaded_at = time.time()
        self._state = {}  # 端末ID → (CameraCounter, 設定の署名, タイル)

    def get(self, camera_id):
        """端末の設定。未登録なら None。変更を拾うため、数秒ごとに設定を読み直す。"""
        if time.time() - self._loaded_at >= CAMERAS_RELOAD_S:
            self.cameras, self._loaded_at = load_cameras(), time.time()
        if camera_id not in self.cameras:
            self.cameras = load_cameras()  # 登録されたばかりの端末かもしれない
            if camera_id not in self.cameras:
                return None
        return self.cameras[camera_id]

    @staticmethod
    def _signature(cam, w, h):
        """追跡を作り直すべきかを判断するための、設定の「印」。これが変わったら作り直す。"""
        return (json.dumps(cam["lines"]), cam["anchor"], cam["tracker"],
                float(cam["sample_fps"]), cam.get("tiling"), w, h)

    def trackers_for(self, camera_id, w, h):
        """端末の (追跡＋線の判定, 検出のタイル分割) を返す。無ければ作る。"""
        cam = self.cameras[camera_id]
        sig = self._signature(cam, w, h)
        state = self._state.get(camera_id)
        if state is None or state[1] != sig:
            if state is not None:
                log.info("設定が変わったので追跡を作り直す: %s", camera_id)
            counter = CameraCounter(
                cam["lines"], w, h, self.trackers[cam["tracker"]], float(cam["sample_fps"]),
                cam["anchor"], self.agg.get("min_crossing_seconds", 0.0), self.agg.get("edge_margin", 0.0),
                self.agg.get("edge_confirm_seconds", 1.5),
            )
            # 分割して検出する設定（tiling: line）のときだけ、1 本目の線の周りを切り出す
            tiles = make_tiles(w, h, cam.get("tiling", "none"), cam["lines"][0]["line"])
            state = self._state[camera_id] = (counter, sig, tiles)
        return state[0], state[2]
