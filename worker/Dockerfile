# ----- Build stage -----
FROM python:3.11-slim AS builder
WORKDIR /install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ----- Runtime stage -----
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /install /usr/local
COPY worker.py .

CMD ["python", "worker.py"]
