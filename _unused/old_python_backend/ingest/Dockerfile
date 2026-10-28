FROM python:3.12-slim
WORKDIR /app
COPY live/ingest/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/common/ common/
COPY live/ingest/ ingest/
COPY live/db/ db/
COPY live/tools/ tools/
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "ingest.app:app", "--host", "0.0.0.0", "--port", "8000"]
