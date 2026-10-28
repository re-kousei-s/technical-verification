FROM python:3.12-slim
WORKDIR /app
COPY live/dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/common/ common/
COPY live/dashboard/ dashboard/
ENV PYTHONPATH=/app
EXPOSE 8080
CMD ["uvicorn", "dashboard.app:app", "--host", "0.0.0.0", "--port", "8080"]
