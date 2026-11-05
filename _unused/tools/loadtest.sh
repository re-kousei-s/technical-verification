#!/usr/bin/env bash
# 負荷試験：worker 1 台に、スマホの代わりを N 台ぶん流して、どこまで追いつくかを見る。
#   使い方: _unused/tools/loadtest.sh "1 2 3 4 6"    （プロジェクトのルートから。段ごとに 60 秒）
# 追いつくなら「処理 fps ≒ 期待 fps（台数 × 3）」、追いつかないなら、処理 fps が頭打ちになり、遅れ（lag）が伸びる。
set -u
API=${API:-https://localhost:8080}
STAGES=${1:-"1 2 3 4"}
SECS=${SECS:-60}
j() { curl -sk -m 10 "$@"; }
snap() { j $API/api/overview | python3 -c "
import sys,json
d=json.load(sys.stdin)
w=d['workers']
print(sum(int(x['processed']) for x in w), d['backlog'], max(float(x['lag_ms_avg']) for x in w), max(float(x['infer_ms_avg']) for x in w), sum(1 for x in w if x['alive']))"; }
for n in $STAGES; do
  ids=()
  for i in $(seq 1 $n); do
    id=$(j -X POST $API/api/cameras -H 'content-type: application/json' -d "{\"floor\":9,\"name\":\"LT-$n-$i\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
    ids+=($id)
    j -X POST $API/api/camera/$id/recognize -H 'content-type: application/json' -d '{"on":true}' >/dev/null
    docker run -d --rm --name lt-$id --network hdt-net -v $PWD/_unused/data:/data:ro -v $PWD/_unused/tools:/app:ro hdt-tools \
      python stream_video.py /data/loadtest/clip_960_3fps.mp4 --url ws://backend:8000/ws/$id --loop >/dev/null
  done
  sleep 20                                  # 立ち上がりを待つ
  read p0 b0 l0 i0 a0 < <(snap); t0=$(date +%s)
  sleep $SECS
  read p1 b1 l1 i1 a1 < <(snap); t1=$(date +%s)
  fps=$(python3 -c "print(round(($p1-$p0)/($t1-$t0),2))")
  cpu=$(docker stats --no-stream --format '{{.Name}}={{.CPUPerc}}' | grep -E 'worker|backend' | tr '\n' ' ')
  echo "台数=$n 期待=$((n*3))fps 処理=${fps}fps 滞留=$b1 遅れ平均=${l1}ms 推論平均=${i1}ms 生存worker=$a1 | $cpu"
  for id in "${ids[@]}"; do docker rm -f lt-$id >/dev/null 2>&1; j -X DELETE $API/api/camera/$id >/dev/null; done
  sleep 20                                  # 溜まった分が捌けるのを待つ
done
