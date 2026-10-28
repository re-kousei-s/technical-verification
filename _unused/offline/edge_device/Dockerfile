FROM python:3.12-slim
# この環境では http の Debian ミラーが 404 になるため https を使う
RUN sed -i 's#http://deb.debian.org#https://deb.debian.org#g' /etc/apt/sources.list.d/debian.sources \
 && apt-get update && apt-get install -y --no-install-recommends libegl1 libgles2 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY offline/edge_device/requirements.txt .
# mediapipe は GUI 版の opencv-contrib-python を引き込み libxcb を要求するため、headless 版に差し替える
RUN pip install --no-cache-dir -r requirements.txt \
 && pip uninstall -y opencv-contrib-python opencv-python opencv-python-headless \
 && pip install --no-cache-dir opencv-contrib-python-headless==5.0.0.93
COPY shared/common/ common/
COPY offline/edge_device/ edge_device/
ENV PYTHONPATH=/app
CMD ["python", "edge_device/run.py"]
