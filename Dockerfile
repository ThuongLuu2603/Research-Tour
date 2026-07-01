# OTA Platform — production image (API + React build)
# Build: docker compose build
# Run:   docker compose up -d

FROM node:22-slim AS fe
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt gunicorn

COPY backend/ ./
COPY --from=fe /fe/dist /app/frontend/dist

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -sf http://127.0.0.1:8000/health || exit 1

CMD ["gunicorn", "main:app", \
    "--workers", "2", \
    "--worker-class", "uvicorn.workers.UvicornWorker", \
    "--bind", "0.0.0.0:8000", \
    "--timeout", "180", \
    "--graceful-timeout", "30", \
    "--access-logfile", "-", \
    "--error-logfile", "-"]
