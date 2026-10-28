FROM python:3.12-slim
WORKDIR /app
COPY shared/aggregator/requirements.txt .
# trackers が GUI 版 opencv を引き込むと libxcb が必要になるため、headless 版に揃える
RUN pip install --no-cache-dir -r requirements.txt \
 && pip uninstall -y opencv-python opencv-contrib-python \
 && pip install --no-cache-dir --force-reinstall --no-deps opencv-python-headless==5.0.0.93
COPY shared/common/ common/
COPY shared/aggregator/ aggregator/
ENV PYTHONPATH=/app
CMD ["python", "aggregator/run.py"]
