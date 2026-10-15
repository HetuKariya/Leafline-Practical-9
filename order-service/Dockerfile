# Python 3.10 runtime with more resilient dependency installation
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