# syntax=docker/dockerfile:1

# ==================== BASE STAGE ====================
FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

COPY requirements.txt .

RUN python -m pip install \
        --retries 10 \
        --timeout 120 \
        --index-url https://pypi.org/simple \
        --upgrade pip setuptools wheel \
    && python -m pip install \
        --retries 10 \
        --timeout 120 \
        --index-url https://pypi.org/simple \
        -r requirements.txt


# ==================== TEST STAGE ====================
# Required by Jenkins:
# docker build --target test
FROM base AS test

COPY requirements-dev.txt .

RUN python -m pip install \
        --retries 10 \
        --timeout 120 \
        --index-url https://pypi.org/simple \
        -r requirements-dev.txt

COPY . .

CMD ["pytest", "-q"]


# ==================== RUNTIME STAGE ====================
# Used to run the actual order microservice.
FROM base AS runtime

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data

COPY --chown=appuser:appuser *.py ./

ENV PORT=5003 \
    DB_PATH=/data/orders.db

USER appuser

EXPOSE 5003

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=6 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=2)"

CMD ["sh", "-c", "exec gunicorn --workers 2 --bind 0.0.0.0:$PORT --access-logfile - app:app"]