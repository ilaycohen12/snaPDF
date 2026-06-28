# Stage 1: install Python dependencies into an isolated directory
FROM python:3.11-slim AS builder
WORKDIR /install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: lean runtime image with LibreOffice + copied Python packages
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /install /usr/local
COPY app.py worker.py ./

EXPOSE 5000
CMD ["python", "app.py"]
