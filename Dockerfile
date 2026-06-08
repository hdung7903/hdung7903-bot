# ════════════════════════════════════════════════════
# Dockerfile – VinhUni Schedule Telegram Bot
# ════════════════════════════════════════════════════
FROM python:3.12-slim

# Metadata
LABEL maintainer="VinhUni Schedule Bot"
LABEL description="Telegram bot tự động đồng bộ lịch học VinhUni"

# Tránh interactive prompts
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Cài dependencies trước (tận dụng Docker cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Tạo thư mục data
RUN mkdir -p /app/data

# Volume cho database và credentials
VOLUME ["/app/data", "/app/credentials"]

# Chạy bot
CMD ["python", "main.py"]
