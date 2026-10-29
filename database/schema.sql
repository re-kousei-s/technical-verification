-- ライブ検証のデータベース。db-init サービスが起動のたびに流す（何度流しても同じになるように書く）。
-- 列の追加は ALTER TABLE ... ADD COLUMN IF NOT EXISTS で足す。

-- スマホなどの端末（= カメラ）の登録。フロアごとに何台でも登録できる。
-- NULL の項目は configs/cameras.yaml の defaults を使う。yaml に書いたカメラとは別に、送信ページから登録される。
CREATE TABLE IF NOT EXISTS cameras (
    camera_id      TEXT PRIMARY KEY,
    floor          INT         NOT NULL,
    name           TEXT,
    line           JSONB       NOT NULL,           -- [[x1, y1], [x2, y2]]  画面に対する割合
    sample_fps     REAL,
    anchor         TEXT,
    tracker        TEXT,
    tiling         TEXT,
    registered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 線の通過イベント（1行 = 1人の通過）
CREATE TABLE IF NOT EXISTS crossings (
    id          BIGSERIAL PRIMARY KEY,
    camera_id   TEXT        NOT NULL,
    floor       INT,
    ts          TIMESTAMPTZ NOT NULL,           -- フレームの撮影（受信）時刻
    direction   TEXT        NOT NULL CHECK (direction IN ('in', 'out')),
    track_id    INT         NOT NULL,
    x           REAL,                           -- 判定点の画面座標(px)
    y           REAL
);
CREATE INDEX IF NOT EXISTS crossings_ts_idx ON crossings (ts DESC);

-- フロアの現在人数 = 前回 + IN − OUT（下限0）。階段・EVなど複数カメラを合算する
CREATE TABLE IF NOT EXISTS floor_counts (
    floor       INT PRIMARY KEY,
    count       INT         NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 最後に人が補正（人数の設定・リセット）した時刻。以降の通過件数が、概算値の誤差の目安になる
ALTER TABLE floor_counts ADD COLUMN IF NOT EXISTS corrected_at TIMESTAMPTZ;

-- カメラごとの累計と、最後に処理したフレームの様子
CREATE TABLE IF NOT EXISTS camera_state (
    camera_id      TEXT PRIMARY KEY,
    floor          INT,
    in_count       INT         NOT NULL DEFAULT 0,
    out_count      INT         NOT NULL DEFAULT 0,
    last_frame_ts  TIMESTAMPTZ,
    last_dets      INT,
    last_tracks    INT,
    frame_w        INT,
    frame_h        INT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- フレームごとの処理記録（速度・遅延の評価用）。lag_ms = フレームの時刻から処理完了までの遅れ
CREATE TABLE IF NOT EXISTS frame_log (
    id          BIGSERIAL PRIMARY KEY,
    camera_id   TEXT        NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    n_dets      INT         NOT NULL,
    infer_ms    REAL        NOT NULL,
    lag_ms      REAL        NOT NULL,
    model       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS frame_log_created_idx ON frame_log (created_at DESC);

-- 入口・エレベーター・階段などの「ゲート」（ドアの領域）。1台のカメラに複数持てる。
-- 例: [{"id": "g1a2b", "name": "エレベーター1", "kind": "elevator", "quad": [[x,y],[x,y],[x,y],[x,y]]}]
-- quad は [左上, 右上, 右下, 左下]（画面に対する割合）。ゲートがあるカメラは、線の通過ではなくゲートで数える。
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS gates JSONB NOT NULL DEFAULT '[]';
-- どのゲートでの出入りか（線の通過なら NULL）
ALTER TABLE crossings ADD COLUMN IF NOT EXISTS gate TEXT;

-- 認識中か（管理画面が決める。スマホは、この指示に従って映像を送る）。再起動しても、続きから再開できるよう、DB に持つ
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS recognizing BOOLEAN NOT NULL DEFAULT FALSE;

-- スマホのカメラの設定（管理画面が決める）。例: {"res":"1280x960","zoom":1.0,"device_id":"…"}。空なら、スマホの既定
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS camera_settings JSONB NOT NULL DEFAULT '{}';

-- 端末ごとの「カウントライン」。1 台に何本でも引ける（入口が複数なら、入口ごとに 1 本）。
-- 例: [{"id": "l1", "name": "入口A", "line": [[x1,y1],[x2,y2]]}]  座標は画面に対する割合。
-- 線は 1 本以上ある前提（0 本にはできない）。IN の向きは、始点→終点に対して画面の左側。
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS lines JSONB NOT NULL DEFAULT '[]';
ALTER TABLE cameras ALTER COLUMN line SET DEFAULT '[[0,0.5],[1,0.5]]';   -- 旧：線は 1 本だけだった列（今は使わない）
-- 旧データの移行：線が 1 本だけの端末は、その線を lines の 1 本目にする（lines が空のときだけ。何度流しても同じ）
UPDATE cameras SET lines = jsonb_build_array(jsonb_build_object('id', 'l1', 'name', '線1', 'line', line))
 WHERE lines = '[]'::jsonb;
-- どの線での通過か（線の名前）
ALTER TABLE crossings ADD COLUMN IF NOT EXISTS line_name TEXT;
