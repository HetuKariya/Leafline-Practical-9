# syntax=docker/dockerfile:1
# ---- base: Python 3.10 (spyne 2.13.16 needs <=3.10) + pinned runtime dependencies
FROM python:3.10-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && pip install -r requirements.txt

# ---- test: used by Jenkins ("docker build --target test"); runs pytest + coverage
FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY . .
# Reports land in /app/reports; the pipeline copies them out with "docker cp".
CMD ["pytest", "-q"]

# ---- runtime: the image docker-compose runs (last stage = default build target)
FROM base AS runtime
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data && chown appuser:appuser /data
COPY --chown=appuser:appuser *.py ./
ENV PORT=5001 \
    DB_PATH=/data/catalog.db
USER appuser
EXPOSE 5001
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=6 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=2)"
CMD ["sh", "-c", "exec gunicorn --workers 2 --bind 0.0.0.0:$PORT --access-logfile - app:app"]
