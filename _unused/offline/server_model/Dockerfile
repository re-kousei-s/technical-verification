FROM python:3.12-slim
WORKDIR /app
COPY offline/server_model/requirements.txt .
# 依存が GUI 版 opencv を引き込むと libxcb が必要になるため、headless 版に揃える
RUN pip install --no-cache-dir -r requirements.txt \
 && pip uninstall -y opencv-python opencv-contrib-python \
 && pip install --no-cache-dir --force-reinstall --no-deps opencv-python-headless==5.0.0.93
COPY shared/common/ common/
COPY offline/server_model/ server_model/
ENV PYTHONPATH=/app
CMD ["python", "server_model/run.py"]
