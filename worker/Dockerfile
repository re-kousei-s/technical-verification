# Python の worker：キューから JPEG を取り出し、検出・追跡・判定をして DB を更新する。
FROM python:3.12-slim
ARG BACKEND=mediapipe
# この環境では http の Debian ミラーが 404 になるため https を使う。mediapipe は libEGL / libGLESv2 が必要
RUN if [ "$BACKEND" = "mediapipe" ]; then \
      sed -i 's#http://deb.debian.org#https://deb.debian.org#g' /etc/apt/sources.list.d/debian.sources \
      && apt-get update && apt-get install -y --no-install-recommends libegl1 libgles2 \
      && rm -rf /var/lib/apt/lists/*; \
    fi
WORKDIR /app
COPY worker/requirements-${BACKEND}.txt requirements.txt
# pip の代わりに uv を使う（依存の解決とインストールが、桁違いに速い）。
# 依存が GUI 版 opencv を引き込むと libxcb が必要になるため、headless 版に差し替える
RUN pip install --no-cache-dir uv \
 && uv pip install --system --no-cache -r requirements.txt \
 && uv pip uninstall --system opencv-python opencv-contrib-python opencv-python-headless opencv-contrib-python-headless \
 && uv pip install --system --no-cache opencv-contrib-python-headless==5.0.0.93
COPY worker/common/ common/
COPY worker/aggregator/ aggregator/
COPY worker/libs/ libs/
COPY worker/worker.py ./
ENV PYTHONPATH=/app
CMD ["python", "worker.py"]
