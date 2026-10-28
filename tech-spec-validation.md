# 技術まとめ：検証環境の構築用

作成日：2026-10-07
※「案」「仮定」と書いた箇所は、公開情報にない私の提案です。実測で決めてください。

---

## 1. 目的と検証したいこと

階段・EVの出入口に置いたスマホで人を検出し、通過IN/OUTからフロアの混雑度（青・黄・赤）を自動判定できるかを確かめる。

| # | 検証したいこと |
|---|---|
| Q1 | スマホ上で、人を十分に検出できるか（モデル、入力サイズ、分割、画角） |
| Q2 | 追跡してIN/OUTを数えられるか（撮影間隔1秒〜で足りるか） |
| Q3 | 3段階の判定が、手動で切り替える今の判断と合うか |
| Q4 | 端末の実用性（速度、発熱、電池、安い端末での動作） |
| Q5 | 会場Wi-Fiが不安定でも崩れないか |

---

## 2. 全体構成（主案）

```
[Androidスマホ]                         [サーバー（AWS）]
 カメラ → 人を検出(MediaPipe等)  ──→   トラッキング(ByteTrack)
 座標だけをJSONで送信                    → 線の通過判定(IN/OUT)
 ※画像は端末の外に出さない               → フロア人数を更新
                                         → 3段階に変換 → ダッシュボード
```

- **比較用の別案（ベースライン）**：スマホは圧縮画像を送るだけ、サーバーのCPUでRF-DETR＋ByteTrackを動かす。精度の比較用に1本作っておく。
- トラッカーは**カメラごとに状態を持つ**（Ultralyticsの説明でも、別ストリームは別トラッカー）。サーバー側は、カメラを特定のワーカーに固定する。

---

## 3. 検証の進め方（3段階）

| 段階 | 場所 | やること | 目的 |
|---|---|---|---|
| Stage 0 | PC | 階段・EVの動画を撮り、モデル・追跡・ライン判定をオフラインで比較 | Q1・Q2を低コストで潰す |
| Stage 1 | スマホ実機 | MediaPipeで検出し、速度・発熱・電池を測る | Q1・Q4 |
| Stage 2 | スマホ＋サーバー | 実機から座標を送り、ダッシュボードまで通す | Q3・Q5 |

**Stage 0から始める。** 動画を使えば、同じ映像でモデルや条件を何度でも比較できる。

### 3.1 当面の検証範囲：ローカルPCで2系統を比較する

まずはStage 0だけを行い、**サーバーサイドのモデル**と**エンドデバイス（スマホ）で動くモデル**を、同じ動画・同じ追跡・同じ判定で比べる。

| 系統 | モデル（候補） | PCでの動かし方 |
|---|---|---|
| A. サーバーサイド | RF-DETR（Nano / Small / Medium） | CPUのみ（スレッド数を4に制限して、サーバー相当の負荷を測る）。GPUがあれば参考値として追加 |
| B. エンドデバイス | MediaPipe（SSD MobileNetV2 / EfficientDet-Lite0 / Lite2） | MediaPipeのPython版。余裕があればPicoDet、NanoDet、YOLOXも追加 |

**共通にするもの**：元動画、フレームの間引き（1秒に1枚、2枚、3枚など）、タイル分割の有無、ByteTrack、LineZone、線の位置。

**比較の考え方**
- 比べるのは**カウントの精度**。検出の多さではなく、最終的なIN/OUTの誤差と、3段階の一致率で見る。
- **PCの速度はスマホの速度を表さない。** PCでは精度を比べ、スマホの速度は公式値（Pixel 6）と、あとで行う実機測定で見る。RF-DETRのCPU時間は、サーバー費の見積もりに使う（相対比較のみ）。
- 判断の目安（案）：エンドデバイス系の誤差が、サーバー系との差で±10ポイント以内ならスマホ上の検出を採用し、超えるなら分割や大きいモデルを足す。

**出力（条件ごとに1行のCSV）**：動画ID、モデル、間引き、分割、IN数、OUT数、正解IN、正解OUT、誤差率、推論時間（PC、参考）

**正解データ**：動画を見ながら、人が通過数を数える（IN/OUT）。検出の取りこぼしは、サンプルのフレーム10〜20枚だけ人数を数えて比べる。

**必要な動画（案）**：階段（狭い所・広い所）とEVホールの各シーンで、空き・普通・混雑の3段階を、各3分ほど。

### 3.2 docker-compose 構成（ローカルPCで実行）

あとでコンテナとしてAWSへ載せやすいよう、最初からdocker-composeで動かす。**未実行の雛形**なので、動かしながら直すこと。

**フォルダ構成（案）**

```
repo/
├─ docker-compose.yml
├─ common/              # 共通：フレーム間引き、ByteTrack、LineZone、CSV出力
├─ server_model/        # 系統A：RF-DETR（Dockerfile / requirements.txt / run.py）
├─ edge_model/          # 系統B：MediaPipe（Dockerfile / requirements.txt / run.py）
├─ evaluator/           # 集計（誤差率、3段階の一致率）
├─ configs/matrix.yaml  # 検証条件（モデル、間引き、分割、線の位置）
├─ data/                # videos/ と ground_truth.csv
├─ models/              # .tflite と重みのキャッシュ
└─ outputs/             # 条件ごとのCSV
```

**docker-compose.yml（雛形）**

```yaml
services:
  server-model:
    build: ./server_model
    profiles: ["server"]
    cpus: 4              # c7i.xlargeの4vCPUを意識した制限（速度は同じにならない）
    mem_limit: 8g
    environment:
      - OMP_NUM_THREADS=4
      - CONFIG=/configs/matrix.yaml
      - PYTHONPATH=/app
    volumes:
      - ./data:/data:ro
      - ./configs:/configs:ro
      - ./common:/app/common:ro
      - ./models:/models
      - ./outputs:/outputs
    command: python run.py

  edge-model:
    build: ./edge_model
    profiles: ["edge"]
    cpus: 2              # スマホ相当ではない。PCが速すぎないよう絞る
    mem_limit: 4g
    environment:
      - CONFIG=/configs/matrix.yaml
      - PYTHONPATH=/app
    volumes:
      - ./data:/data:ro
      - ./configs:/configs:ro
      - ./common:/app/common:ro
      - ./models:/models:ro
      - ./outputs:/outputs
    command: python run.py

  evaluator:
    build: ./evaluator
    profiles: ["eval"]
    volumes:
      - ./data:/data:ro
      - ./outputs:/outputs
    command: python evaluate.py
```

**実行**

```
docker compose --profile server run --rm server-model
docker compose --profile edge   run --rm edge-model
docker compose --profile eval   run --rm evaluator
```

**設計のポイント**
- **イメージは系統ごとに分ける。** RF-DETR（PyTorch）とMediaPipeは、依存パッケージ（numpyやprotobufなど）が衝突しやすいため。
- **共通処理は`common/`にまとめて、両方から読む。** フレームの間引き、ByteTrack、LineZone、CSV出力を共通にしないと、比較が公平にならない。この`common/`は、あとでAPIサーバー（FastAPI）のコンテナにそのまま使える。
- **`cpus`の制限は目安。** コア数を揃えるだけで、1コアあたりの速度（PCとc7iとスマホ）は違う。PCの推論時間は、相対比較とサーバー費の見積もりにだけ使う。
- **GPUは使わない。** MediaPipeのGPU delegateは、コンテナ（PC）では使えない前提。スマホのGPU速度は実機で測る。
- **重み・モデルは`models/`に置く。** RF-DETRの重みは初回ダウンロードをキャッシュして、毎回の取得を避ける。
- **バージョンを固定する。** `requirements.txt`で、torch（CPU版）、rfdetr、mediapipe、supervisionなどを固定する（パッケージ名とバージョンは要確認）。
- **Apple Silicon（M1/M2/M3等）のMacの場合**：MediaPipeのLinux ARM用ホイールが使えるかを確認する。使えなければ、`platform: linux/amd64`を指定する（遅くなる）。

---

## 4. 技術スタック

| 役割 | 候補 | ライセンス | 確認状況 |
|---|---|---|---|
| スマホ上の検出（主案） | MediaPipe Object Detector（EfficientDet-Lite0 / Lite2、SSD MobileNetV2） | コード例はApache 2.0（ドキュメント記載） | モデル本体は要確認 |
| 〃（精度優先の代替） | PP-PicoDet、NanoDet-Plus、YOLOX | PicoDet・NanoDetは未確認、YOLOXはApache 2.0 | 実装は重い（ncnn等） |
| サーバー検出（比較用） | RF-DETR（Nano〜Medium） | Apache 2.0（XL/2XLは別ライセンスなので避ける） | 公式で確認 |
| トラッキング | ByteTrack | MIT | 確認済み |
| ライン判定 | supervision（LineZone） | MIT | 確認済み |
| サーバー | Python（FastAPI）、検証段階は1台（EC2かローカルPC） | — | 案 |
| DB | DynamoDB（または検証中はSQLite） | — | 案 |
| ダッシュボード | 静的HTML＋数秒ごとのポーリング | — | 案 |
| スマホアプリ | Android（Kotlin）、CameraX＋MediaPipe Tasks | — | 案 |

**避けるもの**：UltralyticsのYOLO（AGPL-3.0で、サービス用途は有料ライセンスの対象になり得る）、RF-DETRのXL/2XL。

**入力サイズの目安**（MediaPipe公式）

| モデル | 入力 | Pixel 6のCPU |
|---|---|---|
| SSD MobileNetV2 | 256 | 約36ms |
| EfficientDet-Lite0（int8） | 320 | 約29ms |
| EfficientDet-Lite2（int8） | 448 | 約71ms |

---

## 5. スマホ → サーバーの通信（案）

1回の送信（1カメラ、1フレーム）：

```json
{
  "camera_id": "F2-STAIR-A",
  "floor": 2,
  "ts": "2026-10-07T10:15:03.120+09:00",
  "frame": {"w": 1280, "h": 720},
  "model": "efficientdet_lite2_int8",
  "detections": [
    {"x": 412, "y": 230, "w": 60, "h": 140, "score": 0.71}
  ],
  "device": {"battery": 82, "charging": true, "wifi_rssi": -58, "infer_ms": 74}
}
```

- 画像は送らない。座標だけなので、通信量はごく小さい。
- 切断時は端末にためて、復帰後に時刻順で送る。サーバーは`ts`の順に処理する。
- 検出の間隔、モデル、入力サイズは、サーバー側の設定から変えられるようにする。

---

## 6. 判定ロジック（案）

1. **ライン通過**：画面上にカメラごとの線を引き、追跡IDが線を越えたらIN/OUTを加算する（supervisionのLineZone）。
2. **フロア人数**：`人数 = 前回の人数 + IN − OUT`（下限0）。階段とEVの両方のカメラを合算する。
3. **3段階への変換**：フロアごとのしきい値（管理者が設定）で、青・黄・赤に分ける。
4. **ちらつき防止**：しきい値の付近で色が行き来しないよう、直近数分の平均か、上がる側と下がる側でしきい値をずらす（ヒステリシス）。更新が速すぎると、行列が振動するというシミュレーション研究もある。
5. **補正**：スタッフが1タップでフロア人数を補正できる。閉場時は全フロアを0に戻す。

supervisionの使い方の骨子（動作未確認。バージョンによってByteTrackの置き場所が変わっている可能性があるので、公式ドキュメントで確認すること）：

```python
import supervision as sv

tracker = sv.ByteTrack()
line = sv.LineZone(start=sv.Point(x1, y1), end=sv.Point(x2, y2))

detections = sv.Detections(xyxy=boxes, confidence=scores, class_id=classes)
detections = tracker.update_with_detections(detections)
line.trigger(detections)
print(line.in_count, line.out_count)
```

---

## 7. 検証マトリクス（振る条件）

| 項目 | 条件 |
|---|---|
| モデル | SSD MobileNetV2 / EfficientDet-Lite0 / Lite2 /（余裕があれば）PicoDet |
| 分割 | なし / 2×2 / 線の周りだけ |
| 撮影間隔 | 1秒 / 2秒に3枚 / 5枚 |
| 画角 | 標準 / 広角 |
| 場所 | 階段（幅の狭い所・広い所）/ EVホール |
| 混雑 | 空き / 普通 / 混雑 |
| 端末 | 開発用の端末 / 購入予定の安い端末（moto g06クラス） |
| 比較用 | サーバー側RF-DETR（画像送信） |

---

## 8. 評価指標と合格ライン（案）

| 指標 | 測り方 | 合格ライン（案） |
|---|---|---|
| 検出の取りこぼし | 動画の人数と検出数を比べる | 線の近くで8割以上 |
| IN/OUTの誤差 | 目視で数えた正解と比べる | 1回の通過で±20%以内 |
| 3段階の一致率 | スタッフが付けた色と比べる | 8割以上 |
| 速度 | 1枚あたりの推論時間 | 撮影間隔より短い |
| 発熱・電池 | 給電ありで数時間連続稼働 | 熱暴走・停止なし |
| 通信断 | Wi-Fiを切って復帰 | 欠損なく復旧 |

正解データは、**検証動画を見ながら人が数えて**作る。現地の手動の色切替ログがあれば、それも使う。

---

## 9. データ収集と取り扱い

- 動画は、階段・EVのカメラ位置ごとに、混雑度が違う時間帯で撮る（各3〜5分）。
- 撮影の前に、施設の許可と、来場者への告知を済ませる。
- 動画は検証用の保存場所だけに置き、検証後は削除する（取り扱いは学校・主催者の方針に合わせる）。
- 本番は「画像を端末の外に出さない」方針なので、検証でも、できる限りStage 1以降は座標だけを扱う。

---

## 10. 環境構築メモ（Stage 0、PC）

- 基本はdocker-compose（3.2）で動かす。直接動かす場合は、Python（バージョンは要確認）の仮想環境を作る。
- 入れるもの：`opencv-python`、`supervision`、`mediapipe`（Python版のObject Detectorが公式にある）、比較用に`rfdetr`。
- MediaPipeのモデル（`.tflite`）は、公式ページのリンクから取得する。
- 検証用スクリプトの流れ：動画を読む → 検出 → 追跡 → ライン判定 → IN/OUTと正解を比較してCSVに出す。
- 条件（モデル、分割、間隔）を設定ファイルで切り替えられるようにすると、マトリクスを一括で回せる。

---

## 11. ライセンス確認表

| 対象 | 状況 |
|---|---|
| RF-DETR（Nano〜Medium） | Apache 2.0（確認済み） |
| ByteTrack、supervision | MIT（確認済み） |
| MediaPipe（コード例） | Apache 2.0（ドキュメント記載） |
| MediaPipeのモデルファイル | **要確認** |
| YOLOX | Apache 2.0（確認済み） |
| PP-PicoDet、NanoDet | **要確認** |
| Ultralytics YOLO | AGPL-3.0／有料ライセンス（避ける） |

最終判断は、各リポジトリのLICENSEファイルを読むか、専門家に確認する。

---

## 12. リスクと未確認

**リスク**
- 撮影間隔が長い（1秒）と、人が大きく動いて追跡が途切れやすい（私の推測）。
- SSD MobileNetV2は、検出数が少なめに頭打ちになる可能性がある（要確認）。
- 広角だと人が小さくなり、見落としが増える。
- 階段・EVは同時通過や団体で精度が落ちやすい。
- 累積誤差（補正機能で抑える）。
- スマホの発熱とバッテリー。

**未確認**
- 購入予定の端末での推論速度（公式の値はPixel 6）
- MediaPipeモデル、PicoDet、NanoDetのライセンス
- 階段・EVでの実測精度
- 会場のWi-Fi品質
