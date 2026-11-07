"""認識の結果を PostgreSQL に書き込む。"""

import logging
import time

import psycopg

from common.live import ts_iso
from libs.settings import DATABASE_URL, DETECTOR

log = logging.getLogger("worker")


def connect_db():
    """DB につなぐ。つながるまで 2 秒おきに再試行する。"""
    while True:
        try:
            return psycopg.connect(DATABASE_URL, autocommit=False)
        except psycopg.OperationalError as e:
            log.warning("DB に接続できない（再試行）: %s", e)
            time.sleep(2)


class ResultWriter:
    """1 フレームぶんの結果を、4 つのテーブルにまとめて（1 回のコミットで）書く。

    - crossings    … 通過（IN/OUT）の記録
    - floor_counts … フロアの人数（前回 + IN − OUT、下限 0）
    - camera_state … 端末ごとの累計 IN/OUT と、最後に処理したフレームの様子
    - frame_log    … 処理時間・遅れ（性能の確認用）
    """

    def __init__(self):
        self.db = connect_db()

    def write(self, camera_id, cam, ts_ms, w, h, events, n_dets, n_tracks, infer_ms, lag_ms, model=None):
        """events は (時刻, "in"/"out", 追跡ID, x, y, 線の名前) のリスト。"""
        floor = cam.get("floor")
        ts = ts_iso(ts_ms)
        d_in = sum(1 for e in events if e[1] == "in")
        d_out = len(events) - d_in
        delta = d_in - d_out  # フロアの人数の増減

        # 接続が切れていたら、つなぎ直して 1 回だけやり直す
        for attempt in (1, 2):
            try:
                with self.db.cursor() as cur:
                    self._insert_crossings(cur, camera_id, floor, ts, events)
                    self._update_floor_count(cur, floor, delta)
                    self._update_camera_state(cur, camera_id, floor, d_in, d_out, ts, n_dets, n_tracks, w, h)
                    cur.execute(
                        "INSERT INTO frame_log (camera_id, ts, n_dets, infer_ms, lag_ms, model) VALUES (%s, %s, %s, %s, %s, %s)",
                        (camera_id, ts, n_dets, infer_ms, lag_ms, model or DETECTOR),
                    )
                self.db.commit()
                return
            except psycopg.OperationalError:
                log.warning("DB 書き込みに失敗。再接続する（%d回目）", attempt)
                try:
                    self.db.close()
                except Exception:
                    pass
                self.db = connect_db()
                if attempt == 2:
                    raise

    @staticmethod
    def _insert_crossings(cur, camera_id, floor, ts, events):
        """通過の記録。どの線を越えたか（線の名前）も入れる。"""
        for _, direction, tid, x, y, line_name in events:
            cur.execute(
                "INSERT INTO crossings (camera_id, floor, ts, direction, track_id, x, y, line_name) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (camera_id, floor, ts, direction, tid, float(x), float(y), line_name),
            )

    @staticmethod
    def _update_floor_count(cur, floor, delta):
        """フロアの人数を増減する（下限 0）。増減がなくても、行が無ければ作っておく。"""
        if floor is None:
            return
        if delta:
            cur.execute(
                "INSERT INTO floor_counts (floor, count, updated_at) VALUES (%s, GREATEST(%s, 0), now()) "
                "ON CONFLICT (floor) DO UPDATE SET count = GREATEST(floor_counts.count + %s, 0), updated_at = now()",
                (floor, delta, delta),
            )
        else:
            cur.execute("INSERT INTO floor_counts (floor) VALUES (%s) ON CONFLICT DO NOTHING", (floor,))

    @staticmethod
    def _update_camera_state(cur, camera_id, floor, d_in, d_out, ts, n_dets, n_tracks, w, h):
        """端末ごとの累計。増減分を足していくので、worker を再起動しても累計は消えない。"""
        cur.execute(
            "INSERT INTO camera_state (camera_id, floor, in_count, out_count, last_frame_ts, last_dets, "
            "last_tracks, frame_w, frame_h, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (camera_id) DO UPDATE SET floor = EXCLUDED.floor, "
            "in_count = camera_state.in_count + EXCLUDED.in_count, "
            "out_count = camera_state.out_count + EXCLUDED.out_count, last_frame_ts = EXCLUDED.last_frame_ts, "
            "last_dets = EXCLUDED.last_dets, last_tracks = EXCLUDED.last_tracks, "
            "frame_w = EXCLUDED.frame_w, frame_h = EXCLUDED.frame_h, updated_at = now()",
            (camera_id, floor, d_in, d_out, ts, n_dets, n_tracks, w, h),
        )
