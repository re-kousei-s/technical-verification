#!/usr/bin/env bash
# 検出（エッジ・サーバー）→ 集計 → 評価 を順に回す。
# 引数はそのまま検出側に渡る（例: ./offline/run_all.sh --videos stair_a_crowded --models efficientdet_lite0_int8）
# 出力済みの条件は検出をスキップする。やり直すときは --force。
# 一部のモデルが失敗しても（重みのダウンロード失敗など）、出せた分で集計・評価まで進め、最後に失敗を返す。
set -uo pipefail
cd "$(dirname "$0")/.."
status=0

docker compose --profile edge   run --rm edge-device  python edge_device/run.py "$@" || status=1
docker compose --profile server run --rm server-model python server_model/run.py "$@" || status=1
docker compose --profile aggregate run --rm aggregator python aggregator/preview.py || status=1
docker compose --profile aggregate run --rm aggregator || exit 1
docker compose --profile eval   run --rm evaluator || exit 1

[ $status -ne 0 ] && echo "[warn] 検出で失敗した条件があります。ログを確認して ./offline/run_all.sh を再実行してください（続きから回ります）"
exit $status
