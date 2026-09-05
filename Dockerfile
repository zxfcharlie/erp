FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN mkdir -p /data
ENV ERP_DATA_DIR=/data
ENV SECRET_KEY=please-change-this-secret-key

EXPOSE 8311

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8311"]
