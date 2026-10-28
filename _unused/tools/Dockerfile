# テスト送信（スマホの代わり）：動画ファイルを H.264 として、バックエンドへ流す
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir av==19.0.2 websockets==17.3
COPY stream_video.py fake_phone.py ./
CMD ["python", "stream_video.py"]
