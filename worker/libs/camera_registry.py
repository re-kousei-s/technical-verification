"""端末ごとの設定と、追跡・判定の状態を持つ。追跡は検出の worker が、判定は judge の service が使う。"""

import json
import logging
import time

from aggregator.judge import Judge
from aggregator.lifecycle import Lifecycle
from aggregator.tracking import Tracker
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
        self._tracker = {}  # 端末ID → (追跡, 設定の署名, タイル)
        self._judge = {}  # 端末ID → (判定, 設定の署名)

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
    def _tracker_signature(cam, w, h):
        """追跡を作り直すべきかを判断するための、設定の「印」。これが変わったら作り直す。"""
        return (cam["tracker"], float(cam["sample_fps"]), cam.get("tiling"), json.dumps(cam["lines"][:1]), w, h)

    @staticmethod
    def _judge_signature(cam, w, h):
        return (json.dumps(cam["lines"]), cam["anchor"], float(cam["sample_fps"]), w, h)

    def tracker_for(self, camera_id, w, h):
        """端末の (追跡, 検出のタイル分割, 人の状態管理) を返す。無ければ作る。（検出 + 追跡の worker が使う）"""
        cam = self.cameras[camera_id]
        sig = self._tracker_signature(cam, w, h)
        state = self._tracker.get(camera_id)
        if state is None or state[1] != sig:
            if state is not None:
                log.info("設定が変わったので追跡を作り直す: %s", camera_id)
            tracker = Tracker(self.trackers[cam["tracker"]], float(cam["sample_fps"]))
            # 分割して検出する設定（tiling: line）のときだけ、1 本目の線の周りを切り出す
            tiles = make_tiles(w, h, cam.get("tiling", "none"), cam["lines"][0]["line"])
            # 人の状態管理（starting → moving → deleted）。追跡と一緒に作り直す（追跡 ID が振り直しになるため）
            lifecycle = Lifecycle(float(cam["sample_fps"]), (w, h), **(self.agg.get("episode") or {}))
            state = self._tracker[camera_id] = (tracker, sig, tiles, lifecycle)
        return state[0], state[2], state[3]

    def judge_for(self, camera_id, w, h):
        """端末の判定を返す。無ければ作る。線・fps が変わったら作り直す（判定の状態は、リセットされる）。（judge の service が使う）"""
        cam = self.cameras[camera_id]
        sig = self._judge_signature(cam, w, h)
        state = self._judge.get(camera_id)
        if state is None or state[1] != sig:
            if state is not None:
                log.info("線が変わったので判定を作り直す: %s", camera_id)
            method = self.agg.get("method", "episode")
            params = self.agg.get("episode")
            judge = Judge(cam["lines"], w, h, float(cam["sample_fps"]), method, params, cam["anchor"])
            state = self._judge[camera_id] = (judge, sig)
        return state[0]
