# syntax=docker/dockerfile:1
# Single image: Vite builds the SPA, Django (gunicorn + WhiteNoise) serves API and SPA on one origin.

# ---- 1. Frontend build ---------------------------------------------------------------------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. Runtime ----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"
# One worker, many threads: the in-process cache and rate-limit counters are then shared by all
# requests (set REDIS_URL to scale out to more workers). Plans can take ~10 s cold, hence timeout.
# `exec` makes gunicorn PID 1 so it receives SIGTERM for graceful shutdown.
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 1 --threads 8 --timeout 90 --access-logfile - --forwarded-allow-ips='*'"]
