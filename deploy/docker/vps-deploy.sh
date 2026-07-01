#!/usr/bin/env bash
# Cập nhật OTA Platform trên VPS (sau setup lần đầu).
# Usage: cd /opt/ota-platform && bash deploy/docker/vps-deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${ROOT}"

BRANCH="${BRANCH:-main}"
PORT="${HOST_PORT:-8000}"

echo "==> git pull origin ${BRANCH}"
git fetch origin "${BRANCH}"
git checkout "${BRANCH}"
git pull origin "${BRANCH}"

echo "==> docker compose build & up"
docker compose build
docker compose up -d

echo "==> health"
sleep 5
curl -sf "http://127.0.0.1:${PORT}/health" && echo " — OK" || {
  echo " — chờ thêm (DB bootstrap có thể mất ~30s)"
  sleep 20
  curl -sf "http://127.0.0.1:${PORT}/health" && echo " — OK" || echo " — FAIL (docker compose logs ota)"
}

docker compose ps
