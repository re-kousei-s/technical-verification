# 判定・追跡 v1（2026-11-10 まで本番で使っていたもの）

線のどちら側にいたか（episode）で数える判定と、それを支える追跡・人の状態管理。シンプルな作り（タイル判定・距離だけの追跡・3 段のパイプライン）に置き換えたので、ここに残す。

| ファイル | 中身 |
|---|---|
| aggregator/judge.py | 判定の入口（線ごとの判定を束ねる、同じ人の重複除け、画面用の情報） |
| aggregator/episode_gate.py | 線のどちら側に確かにいたかの入れ替わりで数える（margin 0.12） |
| aggregator/block_gate.py | 線の両側のブロックに「入って、出た／消えた／留まった」で数える（試作） |
| aggregator/lifecycle.py | 人の状態管理（starting → moving → deleted、見え始め前・消えたあとの予想、隠れの対策） |
| aggregator/lowfps_tracker.py | 予想位置との距離 ＋ 服の色で対応付ける追跡（cascade・lost_gate） |
| aggregator/appearance.py | 服の色（胴体の HSV ヒストグラム） |
| aggregator/tracking.py / counter.py | 追跡の入口・評価用に一続きにしたもの |
| libs/frame_processor.py / camera_registry.py | 検出 ＋ 追跡 ＋ 状態管理の worker の 1 フレームの処理・端末ごとの状態 |
| judge_service.py / worker_service.py | judge と worker のサービス本体 |
| config/matrix.yaml | 当時の設定（episode・lowfps の値） |

評価の結果（正解 24 件の動画、検出にゆらぎを加えた評価・いまの線 3 本）：合致 平均 19.6 件、数えすぎ 3.9 件、IN の取りこぼし 2.1 件・OUT 2.3 件。
戻すときは、これらを worker/ と config/ の元の場所へ戻す（git の履歴にもある）。
