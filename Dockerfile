FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

EXPOSE 3007

CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-3007}"]
