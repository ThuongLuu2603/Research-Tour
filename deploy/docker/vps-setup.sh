#!/usr/bin/env bash
# Lần đầu trên VPS Ubuntu — cài Docker + clone + build OTA Platform.
# Usage: sudo bash deploy/docker/vps-setup.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ThuongLuu2603/Research-Tour.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/ota-platform}"

if [[ -f docker-compose.yml ]]; then
  INSTALL_DIR="$(pwd)"
  echo "==> Dùng repo hiện tại: ${INSTALL_DIR}"
elif [[ -d "${INSTALL_DIR}/.git" ]]; then
  cd "${INSTALL_DIR}"
else
  echo "==> Clone ${REPO_URL} → ${INSTALL_DIR}"
  mkdir -p "$(dirname "${INSTALL_DIR}")"
  git clone "${REPO_URL}" "${INSTALL_DIR}"
  cd "${INSTALL_DIR}"
fi

if ! command -v docker &>/dev/null; then
  echo "==> Cài Docker…"
  apt-get update -qq
  apt-get install -y ca-certificates curl git
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "${VERSION_CODENAME:-jammy}") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
fi

cd "${INSTALL_DIR}"

if [[ ! -f .env ]]; then
  cp deploy/docker/env.production.example .env
  echo ""
  echo "!!! Sửa ${INSTALL_DIR}/.env (POSTGRES_PASSWORD, SECRET_KEY, GOOGLE_CREDENTIALS_JSON, FRONTEND_URL)"
  echo "    Rồi chạy lại: docker compose up -d --build"
  echo ""
  exit 0
fi

echo "==> Build & start stack…"
docker compose up -d --build

echo ""
echo "Kiểm tra: curl -sf http://127.0.0.1:${HOST_PORT:-8000}/health"
echo "UI:       http://<IP-VPS>:${HOST_PORT:-8000}"
