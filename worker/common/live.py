"""ライブ検証（ingest / worker / dashboard）で共有する、設定の読み込みと Redis のキー名。

Redis のキー
  frames:p{n}        Redis Streams。ingest が積む間引き後フレーム（JPEG）。n は camera_id のハッシュ
  cam:{camera_id}    ハッシュ。ingest が更新する接続状態とカウンタ
  annotated:{id}     検出枠つきの最新画像（JPEG、worker が約1秒ごとに更新）
  liveview:{id}      ダッシュボードがライブ表示を見ている間だけ立つ（数秒で消える）。ingest が端末に高fpsを要求する合図
  livejpeg:{id}      pub/sub。ライブ表示中だけ、ingest が全フレーム（JPEG）を流す。dashboard が MJPEG にして配る
  result:{id}        最新の認識結果（検出枠・追跡ID・最近の通過）。worker が1フレームごとに更新、スマホの送信ページが表示する
  worker:{name}      ハッシュ。worker のハートビートと統計
  ingest:heartbeat   ingest の生存確認
"""

import hashlib
import os
from datetime import datetime, timezone

import yaml

CAMERAS_PATH = os.environ.get("CAMERAS", "/config/cameras.yaml")
GROUP = "recognizers"
PARTITIONS = int(os.environ.get("PARTITIONS", "1"))


def stream_name(partition):
    return f"frames:p{partition}"


def tracks_stream(frames_stream):
    """検出 + 追跡の worker が、追跡の結果を流すストリーム。フレームのストリームと、同じ分割の番号（frames:p3 → tracks:p3）"""
    return frames_stream.replace("frames:", "tracks:", 1)


JUDGE_GROUP = "judges"  # 判定の service が、追跡の結果を読むためのコンシューマーグループ


def partition_of(camera_id, n=None):
    """カメラを特定のパーティション（= 特定の worker）に固定する。トラッカーはカメラごとに状態を持つため。"""
    n = n or PARTITIONS
    return int(hashlib.md5(camera_id.encode()).hexdigest(), 16) % n


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://hdt:hdt@postgres:5432/hdt")
OVERRIDABLE = ("sample_fps", "anchor", "tracker", "tiling")
DEFAULT_LINE = [[0.0, 0.5], [1.0, 0.5]]


def db_connect(**kw):
    import psycopg  # ingest / worker / dashboard だけが使う（他のイメージには入っていない）
    return psycopg.connect(DATABASE_URL, connect_timeout=3, **kw)


def load_cameras(path=None):
    """camera_id -> 設定（defaults を埋めたもの）。

    configs/cameras.yaml に書いた固定のカメラと、送信ページから登録された端末（DB）を合わせる。
    DB に繋がらないときは yaml だけ。
    """
    raw = load_yaml(path or CAMERAS_PATH)
    defaults = raw.get("defaults", {})
    # yaml の固定カメラは、線が 1 本（line:）。端末の設定としては「線のリスト」にそろえる
    cams = {}
    for c in raw.get("cameras") or []:
        # 線は lines:（名前つきのリスト）または line:（1 本）
        if c.get("lines"):
            lines = [{"id": f"l{i + 1}", "name": ln.get("name") or f"線{i + 1}", "line": ln["line"]} for i, ln in enumerate(c["lines"])]
        else:
            lines = [{"id": "l1", "name": "線1", "line": c["line"]}]
        cams[c["id"]] = {**defaults, **c, "lines": lines, "source": "yaml"}
    try:
        from psycopg.rows import dict_row
        with db_connect(row_factory=dict_row) as conn:
            for row in conn.execute("SELECT * FROM cameras ORDER BY floor, camera_id").fetchall():
                over = {k: row[k] for k in OVERRIDABLE if row[k] is not None}
                cams[row["camera_id"]] = {
                    **defaults, **over, "id": row["camera_id"], "floor": row["floor"], "name": row["name"],
                    "lines": row["lines"] or [], "source": "db",
                }
    except Exception:
        pass
    return cams


def load_floors(path=None):
    return {int(k): v for k, v in (load_yaml(path or CAMERAS_PATH).get("floors") or {}).items()}


def load_live_params(path=None):
    """ライブ表示のパラメータ（configs/cameras.yaml の live:）。"""
    return {"normal_fps": 5, "live_fps": 30, "max_seconds": 600, "width": 960, "jpeg_quality": 70,
            **(load_yaml(path or CAMERAS_PATH).get("live") or {})}


def load_estimate(path=None):
    return {"error_rate": 0.2, **(load_yaml(path or CAMERAS_PATH).get("estimate") or {})}


def estimate_margin(n_crossings, error_rate):
    """フロア人数の概算の ± の幅 = 補正してから今までの通過件数 × 誤差率（切り上げ）。"""
    import math
    return math.ceil(n_crossings * error_rate)


def reset_history(conn, camera_id=None, floor=None):
    """IN/OUT の履歴（通過イベント）と、カメラごとの累計 IN/OUT を消す。camera_id / floor で範囲を絞る（両方 None なら全部）。

    フロア人数の概算（floor_counts）は変えない（いまそこにいる人の推定で、履歴とは別の数字）。
    戻り値は、消した通過イベントの件数。
    """
    where, args = "", []
    if camera_id is not None:
        where, args = " WHERE camera_id = %s", [camera_id]
    elif floor is not None:
        where, args = " WHERE floor = %s", [floor]
    n = conn.execute("DELETE FROM crossings" + where, args).rowcount
    conn.execute("UPDATE camera_state SET in_count = 0, out_count = 0, updated_at = now()" + where, args)
    return n


def reset_all(conn):
    """全部リセット：全端末の IN/OUT の履歴と累計を消し、全フロアの人数の概算も 0 に戻す（閉場・やり直し用）。"""
    n = reset_history(conn)
    floors = conn.execute("UPDATE floor_counts SET count = 0, updated_at = now(), corrected_at = now()").rowcount
    return {"deleted_crossings": n, "floors_reset": floors}


def ts_iso(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds")


def now_ms():
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)
