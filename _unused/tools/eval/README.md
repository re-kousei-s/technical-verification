# 精度の検証（動画 4 本）

動画（`_unused/data/videos/silent/`、音は消してある）から、5fps で検出を取り出し（`extract_dets.py`）、数える条件を変えて、正解との合致を比べる（`run_grid.py`）。
検出は重いので、1 回だけ取り出して JSON に保存し（`_unused/outputs/eval/`）、条件の比較は、何度でも回せる。

```bash
# 検出（worker のコンテナの中で。モデル: efficientdet_lite0_int8 / efficientdet_lite2_int8 / rfdetr_nano（rfdetr のイメージ））
docker run --rm --entrypoint python -e MODELS_DIR=/app/models -v $PWD/worker/common:/app/common -v $PWD/worker/models:/app/models \
  -v $PWD/_unused/data/videos/silent:/v:ro -v $PWD/_unused/outputs/eval:/o -v $PWD/_unused/tools/eval/extract_dets.py:/e.py -w /app \
  hdt-worker-mediapipe /e.py /v/<動画>.mp4 efficientdet_lite0_int8 5 /o/<動画>.lite0.json
# 比較（lite0 / lite2 / rfdetr）
docker run --rm --entrypoint python -v $PWD/worker/aggregator:/app/aggregator -v $PWD/worker/common:/app/common -v $PWD/config:/config:ro \
  -v $PWD/_unused/tools/eval:/t:ro -v $PWD/_unused/outputs/eval:/o -w /app hdt-worker-mediapipe /t/run_grid.py lite0
```

正解（目で見て、軌跡から決めたもの。全 6 件）：V1＝A の扉から出る(OUT)→奥の扉へ入る(IN) / V2＝B の扉へ入る(IN) / V3＝B の扉から出る(OUT) / V4＝階段の扉へ入る(IN)→出る(OUT)。
線の位置は、RF-DETR の軌跡を見て置いたので、完全に独立した正解ではない（目安）。
