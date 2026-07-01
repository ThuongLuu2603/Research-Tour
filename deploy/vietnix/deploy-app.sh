#!/usr/bin/env bash
# Deploy OTA app lên VPS Vietnix.
# Chạy SAU setup-vps.sh + postgres-tune.sh.
# Usage: bash deploy-app.sh <git-repo-url>
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Phải chạy root." >&2
    exit 1
fi

REPO_URL="${1:-}"
if [[ -z "${REPO_URL}" ]]; then
    echo "Usage: bash deploy-app.sh <git-repo-url>" >&2
    echo "  Vd: bash deploy-app.sh https://github.com/<user>/ota-platform.git" >&2
    exit 1
fi

APP_DIR=/var/www/ota
BACKEND_DIR="${APP_DIR}/backend"
FRONTEND_DIR="${APP_DIR}/frontend"

# ─────────────────────────────────────────────────────────────────────────────
# 1. Clone hoặc pull
# ─────────────────────────────────────────────────────────────────────────────
if [[ -d "${APP_DIR}/.git" ]]; then
    echo "▸ Repo đã tồn tại, pull latest…"
    sudo -u ota git -C "${APP_DIR}" pull --ff-only
else
    echo "▸ Clone repo…"
    rm -rf "${APP_DIR}"/* "${APP_DIR}"/.[!.]* 2>/dev/null || true
    sudo -u ota git clone "${REPO_URL}" "${APP_DIR}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 2. Backend venv + dependencies
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Backend venv…"
if [[ ! -d "${BACKEND_DIR}/venv" ]]; then
    sudo -u ota python3.11 -m venv "${BACKEND_DIR}/venv"
fi
sudo -u ota "${BACKEND_DIR}/venv/bin/pip" install --upgrade pip wheel
sudo -u ota "${BACKEND_DIR}/venv/bin/pip" install -r "${BACKEND_DIR}/requirements.txt"
# Production server
sudo -u ota "${BACKEND_DIR}/venv/bin/pip" install gunicorn

# ─────────────────────────────────────────────────────────────────────────────
# 3. .env file
# ─────────────────────────────────────────────────────────────────────────────
if [[ ! -f "${BACKEND_DIR}/.env" ]]; then
    echo "⚠ Backend chưa có .env — copy template…"
    cp "${APP_DIR}/deploy/vietnix/env.template" "${BACKEND_DIR}/.env"
    chown ota:ota "${BACKEND_DIR}/.env"
    chmod 600 "${BACKEND_DIR}/.env"
    echo
    echo "═══════════════════════════════════════════════════════════════════"
    echo " HÀNH ĐỘNG CẦN: Edit ${BACKEND_DIR}/.env với env vars thực tế"
    echo " (copy từ Render dashboard). Sau đó rerun script."
    echo "═══════════════════════════════════════════════════════════════════"
    exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# 4. Frontend build
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Frontend build…"
cd "${FRONTEND_DIR}"
sudo -u ota npm ci --no-audit --no-fund
sudo -u ota npm run build
# Output: ${FRONTEND_DIR}/dist

# ─────────────────────────────────────────────────────────────────────────────
# 5. systemd unit
# ─────────────────────────────────────────────────────────────────────────────
SERVICE_FILE=/etc/systemd/system/ota-backend.service
if [[ ! -f "${SERVICE_FILE}" ]]; then
    echo "▸ Install systemd unit…"
    cp "${APP_DIR}/deploy/vietnix/ota-backend.service" "${SERVICE_FILE}"
    systemctl daemon-reload
fi

# ─────────────────────────────────────────────────────────────────────────────
# 6. Start/restart service
# ─────────────────────────────────────────────────────────────────────────────
systemctl enable ota-backend
systemctl restart ota-backend
sleep 3
systemctl status ota-backend --no-pager | head -15

# ─────────────────────────────────────────────────────────────────────────────
# 7. Smoke test
# ─────────────────────────────────────────────────────────────────────────────
echo
echo "▸ Smoke test (chờ 5s)…"
sleep 5
if curl -sf --unix-socket /var/www/ota/backend/ota.sock http://localhost/health; then
    echo
    echo "✓ Backend healthy"
else
    echo "✗ Backend KHÔNG response. Check: journalctl -u ota-backend -n 50"
    exit 1
fi

echo
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  App deployed.                                                  ║"
echo "║                                                                 ║"
echo "║  Service : systemctl status ota-backend                         ║"
echo "║  Logs    : journalctl -u ota-backend -f                         ║"
echo "║  Socket  : /var/www/ota/backend/ota.sock                        ║"
echo "║                                                                 ║"
echo "║  Next: bash setup-nginx.sh <domain>                             ║"
echo "╚════════════════════════════════════════════════════════════════╝"
