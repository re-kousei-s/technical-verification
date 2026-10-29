# 構成図・フロー図

図は Mermaid で書いてある（GitHub、VS Code の Markdown プレビューで、そのまま図になる）。

## 1. システム全体

```mermaid
flowchart LR
  subgraph Phone["スマホ（Android Chrome）"]
    P1["送信ページ<br/>sender.html"]
    P2["カメラ映像<br/>WebCodecs で H.264 に符号化"]
  end

  subgraph PC["PC のブラウザ"]
    A1["管理画面<br/>React + TypeScript + Tailwind"]
    A2["ライブ映像<br/>WebCodecs でデコード"]
  end

  subgraph Docker["docker compose --profile live"]
    GW["gateway（nginx）<br/>自己署名の HTTPS<br/>:8000 / :8443 と :8080 / :8444"]

    subgraph BE["backend（Go: echo + gorm）"]
      DEV["スマホ向けサーバー :8000<br/>送信ページ・登録 API・スマホとの WS（1 本）"]
      ADM["管理画面向けサーバー :8080<br/>一覧 API・操作 API・ライブ中継 WS"]
      STR["StreamService<br/>受信・指示・間引き"]
      HUB["Device（端末ごとのハブ）<br/>購読者に H.264 を配る・GOP を覚える"]
      FF["ffmpeg<br/>H.264 → JPEG（全フレーム）"]
    end

    RD[("Redis<br/>frames:p0… キュー<br/>result・annotated・worker")]
    WK["worker（Python）<br/>検出 → 追跡 → 線の判定"]
    PG[("PostgreSQL<br/>端末・通過・人数")]
    INIT["db-init<br/>schema.sql を流して終了"]
  end

  P2 --> P1
  P1 -- "H.264 / WebSocket" --> GW
  GW --> DEV
  A1 -- "HTTPS / WebSocket" --> GW
  GW --> ADM
  ADM --> A2
  A2 --> A1

  DEV --> STR
  STR -- "全チャンクを、そのまま" --> HUB
  HUB -- "H.264 をコピーして中継" --> ADM
  STR -- "全フレームをデコード" --> FF
  FF -- "5fps に間引いた JPEG" --> RD
  RD -- "XREADGROUP" --> WK
  WK -- "通過・人数・処理記録" --> PG
  WK -- "認識結果・検出枠つき画像・ハートビート" --> RD
  ADM -- "一覧・設定" --> PG
  ADM -- "キュー・認識結果の読み取り" --> RD
  DEV -- "端末の登録・設定" --> PG
  INIT -- "起動時に 1 回" --> PG
```

**読み方：** 認識用の経路は「スマホ → backend（ffmpeg でデコード、5fps に間引き）→ Redis → worker → PostgreSQL」。
ライブ用の経路は、デコードせずに、H.264 を管理画面のブラウザまで、そのまま届ける。

## 2. 認識の流れ（1 フレームの一生）

```mermaid
sequenceDiagram
  autonumber
  participant Ph as スマホ
  participant Be as backend（Go）
  participant Ff as ffmpeg
  participant Rd as Redis
  participant Wk as worker（Python）
  participant Pg as PostgreSQL
  participant Ad as 管理画面

  Ph->>Be: H.264 のチャンク（約 5fps、WebSocket）
  Be->>Ff: 標準入力へ（全フレームをデコード）
  Ff-->>Be: JPEG（全フレーム）
  Note over Be: 認識用の頻度（sample_fps = 5）に間引く<br/>キューが MAX_QUEUE を超えたら、新しいフレームを捨てる
  Be->>Rd: XADD frames:p{n}（camera_id, ts_ms, w, h, jpeg）
  Wk->>Rd: XREADGROUP（グループ recognizers）
  Rd-->>Wk: フレーム
  Note over Wk: 検出（人の枠）→ 追跡 → 線の通過を判定
  Wk->>Pg: crossings（通過）・camera_state・floor_counts・frame_log
  Wk->>Rd: result:{id}（枠・イベント）、annotated:{id}（画像）、worker:{name}（ハートビート）
  Wk->>Rd: XACK + XDEL
  loop 2 秒ごと
    Ad->>Be: GET /api/overview
    Be->>Pg: 端末・人数・通過
    Be->>Rd: キューの長さ・worker の様子
    Be-->>Ad: 一覧
  end
```

**パーティション：** 端末 ID の md5 を `PARTITIONS` で割った余りで、キュー（`frames:p0`…）が決まる（Go と Python で同じ計算）。
同じ端末のフレームは、必ず同じ worker が、積まれた順に処理する（追跡の状態を持つため）。

## 3. 端末ごとのハブ（Device）：購読者のコールバックに配る

スマホとの接続は、**1 台 1 本の WebSocket**（`/ws/:id`）。届いた H.264 のチャンクは、端末ごとのハブ（`Device`）に入り、登録されている購読者のコールバックに配られる。

```mermaid
flowchart LR
  PH["スマホ<br/>/ws/:id（1 本）"] -- "H.264 のチャンク" --> PUB["Device.Publish<br/>GOP を覚える・受信の実測"]
  PUB --> S1["購読者 1：Recognizer<br/>認識中だけ登録<br/>ffmpeg でデコード → 5fps に間引き → Redis"]
  PUB --> S2["購読者 2：Viewer<br/>見ている間だけ登録<br/>H.264 をそのまま管理画面の WS へ"]
  S1 --> RD[("Redis<br/>frames:p{n}")]
  S2 --> AD["管理画面<br/>（ブラウザがデコード）"]
  RD --> WK["worker"]
  WK --> RS[("Redis<br/>result:{id}")]
  RS -- "見ている間だけ、0.25 秒ごとに読む<br/>変わったら、同じ WS でテキストで流す" --> AD
  CTL["control（0.3 秒ごと）<br/>あるべき状態を計算"] -- "状態の JSON（変わったときだけ）" --> PH
  CTL -. "認識中になったら登録、止まったら解除" .-> S1
```

- 購読者が 1 つもなければ、届いたチャンクは、捨てる。普段（認識中だけ）は、Recognizer（Redis へ書く）の 1 つだけ。
- 見ている人は 2 種類。**一覧の小さな表示（thumb）**は、低い fps（`thumb_fps` = 1）でよく、時間の上限もない。**リアルタイム表示**は、高い fps（`live_fps` = 15）を頼む。どちらも、認識していなくても、見られている間は、スマホが送る。
- 見ている人がいる間だけ、Viewer が増える。新しい購読者には、覚えている GOP（最後のキーフレームから今まで）を最初に渡すので、途中から始めても映る。

## 4. スマホとサーバーのやり取り（1 本の WebSocket）

```mermaid
sequenceDiagram
  autonumber
  participant Ad as 管理画面
  participant Be as backend（Device）
  participant Pg as PostgreSQL
  participant Ph as スマホ（/ws/:id）

  Ph->>Be: 接続（送信ページを開いている間は、つなぎ続ける）
  Be-->>Ph: {"recognize":false,"send_fps":0,"preview":false}（送らない）

  Ad->>Be: POST /api/camera/:id/recognize {on: true}
  Be->>Pg: cameras.recognizing = true（再起動しても残る）
  Be->>Be: Recognizer を購読者に登録
  Be-->>Ph: {"recognize":true,"send_fps":5,"preview":false}
  Ph->>Be: H.264（5fps、解像度を落として送る）→ 認識（図 2）

  Ad->>Be: ライブを開始（WebSocket /api/live/:id）
  Be->>Be: Viewer を購読者に登録（GOP を先に渡す）
  Be-->>Ph: {"recognize":true,"send_fps":15,"preview":true,"idr":true}
  Ph->>Be: 15fps・元の解像度・最初は IDR
  Be-->>Ad: H.264 をそのまま中継 + 認識結果をテキストで

  Ad->>Be: ライブを停止（WebSocket を閉じる）
  Be-->>Ph: {"recognize":true,"send_fps":5,"preview":false}
  Note over Ph: 解像度を落として、5fps に戻る

  Ad->>Be: POST /api/camera/:id/recognize {on: false}
  Be-->>Ph: {"recognize":false,"send_fps":0,"preview":false}
  Note over Ph: 映像を送るのをやめる（接続は、つないだまま）
```

**スマホは、状態に従うだけ。** サーバーは、状態が変わったときだけ（念のため 10 秒ごとにも）、全体を 1 通で伝える。命令を何種類も送らないので、再接続しても、取りこぼさない。
認識中でなく、誰も見ていなければ、`send_fps` は 0。ライブだけを見る場合も、認識は始まらない（Recognizer は登録されず、数えない）。

## 5. スマホの送信ページの状態

```mermaid
stateDiagram-v2
  [*] --> 未登録
  未登録 --> 待機中: フロアと名前を登録（接続する）
  待機中 --> 認識中: send_fps = 5、recognize = true
  認識中 --> 待機中: send_fps = 0
  待機中 --> ライブ配信中: send_fps = 15、recognize = false
  ライブ配信中 --> 待機中: send_fps = 0
  ライブ配信中 --> 認識中: recognize = true（認識も始まる）
  認識中 --> 認識中: preview の切り替え（解像度を変える）・fps の切り替え
  note right of 待機中
    カメラのプレビューと、設定パネルは、いつでも使える。
    認識の開始・線の編集は、管理画面だけが行う
  end note
```

## 6. 線を越えたかの判定（worker）

```mermaid
flowchart TD
  F["キューから JPEG を取り出す"] --> D["検出<br/>MediaPipe EfficientDet-Lite0（または RF-DETR）<br/>最低スコア 0.1"]
  D --> T["追跡（lowfps トラッカー）<br/>枠に追跡 ID を付ける<br/>高い信頼度 0.25 以上で、追跡を作る"]
  T --> A["判定する点を決める<br/>既定は足元（bottom_center）"]
  A --> L{"線ごとに判定"}
  L --> Z["LineZone<br/>点が、線の片側から反対側へ動いた"]
  L --> E["EdgeCrossing（線の際）"]

  Z --> C1{"越えた？"}
  C1 -- "はい" --> EV["通過の記録<br/>方向（in / out）・追跡 ID・線の名前"]
  C1 -- "いいえ" --> E

  E --> R1{"際（枠の高さ x 0.3 以内）で<br/>見え始めて、外へ出た"}
  R1 -- "はい" --> EV
  R1 -- "いいえ" --> R2{"線へ向かって動いていた人が<br/>際の中で見えなくなった"}
  R2 -- "いいえ" --> NO["数えない"]
  R2 -- "はい" --> W["1.5 秒、確定を待つ"]
  W --> R3{"同じ人が、また見えた<br/>または近くに別の ID で現れた"}
  R3 -- "はい" --> NO
  R3 -- "いいえ（本当に消えた）" --> EV

  EV --> DB["PostgreSQL に書く<br/>crossings・camera_state<br/>floor_counts（IN − OUT、下限 0）"]
  EV --> OUT["Redis の result:{id} にイベントを出す<br/>（スマホの画面に IN/OUT が出る）"]
```

IN の向きは、線の始点から終点を見て、**画面の左側**。線の長さの範囲の外にいる人は、際の対象にしない（別の入口の前を通る人を数えないため）。

## 7. フロアの人数の概算

```mermaid
flowchart LR
  X1["端末 A の線<br/>IN / OUT"] --> S["フロアの合計<br/>人数 = 前回 + IN − OUT<br/>（下限 0）"]
  X2["端末 B の線<br/>IN / OUT"] --> S
  X3["端末 C の線<br/>IN / OUT"] --> S
  S --> N["概算 約 N 人"]
  S --> M["範囲 = 補正してからの通過件数 x 誤差率（20%）"]
  N --> LV{"しきい値（仮）"}
  LV -- "黄の値未満" --> BL["青"]
  LV -- "黄以上、赤未満" --> YL["黄"]
  LV -- "赤以上" --> RL["赤"]
  H["スタッフが数えた人数"] -- "人数を補正" --> S
  H -- "補正すると、通過件数が 0 に戻り、範囲が小さくなる" --> M
```

## 8. データの置き場所

```mermaid
erDiagram
  cameras ||--o| camera_state : "端末ごとの累計"
  cameras ||--o{ crossings : "通過の記録"
  cameras ||--o{ frame_log : "処理の記録"
  floor_counts ||--o{ cameras : "階ごとに合算"

  cameras {
    text camera_id PK
    int floor
    text name
    jsonb lines "線のリスト（名前・座標）"
    real sample_fps
    text anchor "判定する点"
    text tracker
    bool recognizing "認識中か（管理画面が決める）"
  }
  crossings {
    bigint id PK
    text camera_id
    int floor
    timestamptz ts
    text direction "in または out"
    int track_id
    text line_name "どの線か"
  }
  camera_state {
    text camera_id PK
    int in_count
    int out_count
    int last_dets
    int last_tracks
    timestamptz last_frame_ts
  }
  floor_counts {
    int floor PK
    int count "概算の人数"
    timestamptz corrected_at "最後に人が補正した時刻"
  }
  frame_log {
    bigint id PK
    text camera_id
    int n_dets
    real infer_ms
    real lag_ms
  }
```

**Redis（消えてよい一時データ）**

| キー | 中身 | 書く人 → 読む人 |
|---|---|---|
| `frames:p{n}`（Streams） | 認識待ちのフレーム（JPEG）。グループ `recognizers` | backend → worker |
| `result:{id}` | 最新の認識結果（検出枠・イベント） | worker → backend → 管理画面・スマホ |
| `annotated:{id}` | 検出枠つきの最新画像（約 1 秒ごと） | worker → backend → 管理画面 |
| `worker:{name}` | worker のハートビートと処理の統計 | worker → backend（システムのページ） |

## 9. コードの構成

```mermaid
flowchart TB
  subgraph Go["backend（Go）：依存は、上から下へ"]
    C["controller/<br/>HTTP・WebSocket の入口<br/>device_controller（スマホ）・admin_controller（管理画面）"]
    S["services/<br/>業務ロジック<br/>stream（受信・指示）・decoder・live_hub<br/>camera・floor・overview"]
    R["repository/<br/>DB_repository（gorm）・queue_repository（go-redis）"]
    M["models/<br/>テーブルと API の形"]
    CF["config/<br/>環境変数・cameras.yaml の読み込み"]
    C --> S --> R --> M
    S --> CF
  end

  subgraph Py["worker（Python）"]
    WM["worker.py<br/>部品を組み立てて動かすだけ"]
    LB["libs/<br/>queue_consumer・frame_processor<br/>camera_registry・database・redis_output<br/>annotator・stats・settings"]
    AG["aggregator/<br/>counter（追跡 + 線）・lowfps_tracker<br/>edge_crossing（線の際）"]
    CM["common/<br/>detectors（MediaPipe・RF-DETR）・tiling・messages"]
    WM --> LB --> AG
    LB --> CM
  end

  subgraph Web["画面"]
    SND["backend/web/sender.html<br/>スマホの送信ページ（素の JS）"]
    ADM["backend/admin/<br/>管理画面（React + TypeScript + Tailwind）<br/>Docker のビルドで、Go に埋め込まれる"]
  end

  Go -. "配信" .-> Web
```

## 10. 管理画面の部品（端末 ID を渡すだけで使える）

```mermaid
flowchart TB
  APP["App（HashRouter）<br/>OverviewProvider が /api/overview を 2 秒ごとに読んで、全ページで共有"]
  APP --> DASH["ダッシュボード"]
  APP --> FLR["フロア"]
  APP --> CAMS["端末の一覧"]
  APP --> DET["端末のページ /cameras/:id"]
  APP --> CRS["通過の履歴"]
  APP --> SYS["システム"]
  APP --> SET["リセット"]

  DET --> RB["RecognizeButton cameraId<br/>認識の開始・停止"]
  DET --> LV["CameraLiveView cameraId<br/>ライブ・線・IN/OUT・枠・線の編集"]
  DET --> ST["CameraStats / CameraLines / CameraSnapshot"]
  DET --> RS["CameraResetButton"]
  DET --> CT["CrossingsTable cameraId"]
  CAMS --> CC["CameraCard cameraId"]
  DASH --> CC
  DASH --> FC["FloorCard"]
  FLR --> FC

  LV --> H1["useCameraLive<br/>WebSocket + VideoDecoder"]
  LV --> H2["useLineEditor<br/>線の編集の状態・保存"]
  LV --> OV["LineOverlay<br/>SVG で線と枠を描く・ドラッグ"]
```

## 11. 起動の順序と、ポート

```mermaid
flowchart LR
  R["redis<br/>healthy"] --> B["backend"]
  P["postgres<br/>healthy"] --> I["db-init<br/>schema.sql を流して終了"]
  I --> B
  I --> W["worker"]
  R --> W
  B --> G["gateway（nginx）"]

  G -- "8000 / 8443" --> B1["backend :8000<br/>スマホ向け"]
  G -- "8080 / 8444" --> B2["backend :8080<br/>管理画面向け"]
```

外へ公開するのは、gateway の 4 つのポート（8000・8080・8443・8444）だけ。redis・postgres・backend の直接のポートは、コンテナの中だけ。
