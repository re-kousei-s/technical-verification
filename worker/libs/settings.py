"""worker の設定。環境変数から読む値と、定数をここにまとめる。"""

import os
import socket

from common.live import PARTITIONS

# --- 接続先 ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://hdt:hdt@postgres:5432/hdt")

# --- 検出器（MediaPipe / RF-DETR のモデル名） ---
DETECTOR = os.environ.get("DETECTOR", "efficientdet_lite0_int8")

# --- この worker の名前と、担当するキュー ---
NAME = os.environ.get("WORKER_NAME") or socket.gethostname()
# 担当パーティション。ふだんは、動いている worker どうしが、自動で分け合う（libs/partition_owner.py）ので、空で始まる。
# WORKER_PARTITIONS="0,1" のように指定すると、自動をやめて、その分割だけを、固定で担当する。
# 端末は、backend が、いずれかの分割に固定する。同じ端末のフレームは、同じ分割に届き、積まれた順に処理される（追跡の状態を持つため）
STATIC_PARTITIONS = [int(p) for p in os.environ.get("WORKER_PARTITIONS", "").split(",") if p.strip() != ""]
OWNED = list(STATIC_PARTITIONS)  # いま担当している分割（自動のときは、実行中に、変わる。同じリストを、書き換えていく）

# --- 設定ファイル（config/ をマウントしたもの） ---
MATRIX = os.environ.get("CONFIG", "/config/matrix.yaml")  # 検出の最低スコア、トラッカーの定義

# --- 定数 ---
RESULT_MIN_SCORE = 0.25  # 認識結果として表示する検出の最低スコア（追跡には、これより低いものも使われている）
STALE_MS = int(os.environ.get("STALE_MS", "8000"))  # これより古いフレームは、処理せずに捨てる（キューが溜まったとき）
CAMERAS_RELOAD_S = 3.0  # 端末の登録・ライン・fps の変更を拾い直す間隔（秒）
ANNOTATE_EVERY_S = 1.0  # 検出枠つき画像（管理画面用）の更新間隔（秒）
