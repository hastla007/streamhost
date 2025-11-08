# syntax=docker/dockerfile:1.6

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies required by StreamHost
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libpq-dev \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy source early so we can install dependencies conditionally.
COPY . .

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel \
    && if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi \
    && if [ -f requirements-dev.txt ]; then pip install --no-cache-dir -r requirements-dev.txt; fi

# Ensure directories expected by the application exist
RUN mkdir -p /app/data/movies /app/data/cache /app/data/assets /app/data/backups

EXPOSE 8000

ENTRYPOINT ["/bin/sh", "-c"]
CMD ["python -m app.main start"]
