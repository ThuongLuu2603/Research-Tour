#!/usr/bin/env bash
# Cấu hình Nginx reverse proxy + SSL Let's Encrypt cho OTA platform.
# Usage: bash setup-nginx.sh <domain> [<email>]
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Phải chạy root." >&2
    exit 1
fi

DOMAIN="${1:-}"
EMAIL="${2:-admin@${DOMAIN}}"

if [[ -z "${DOMAIN}" ]]; then
    echo "Usage: bash setup-nginx.sh <domain> [<email>]" >&2
    echo "  Vd: bash setup-nginx.sh ota.example.com admin@example.com" >&2
    exit 1
fi

SITE_AVAIL=/etc/nginx/sites-available/ota
SITE_ENABLED=/etc/nginx/sites-enabled/ota

# ─────────────────────────────────────────────────────────────────────────────
# 1. Render Nginx config từ template
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Render Nginx config cho ${DOMAIN}…"
sed "s/{{DOMAIN}}/${DOMAIN}/g" /var/www/ota/deploy/vietnix/nginx.conf > "${SITE_AVAIL}"

# ─────────────────────────────────────────────────────────────────────────────
# 2. Bỏ default site (nếu có) + enable site mới
# ─────────────────────────────────────────────────────────────────────────────
rm -f /etc/nginx/sites-enabled/default
ln -sf "${SITE_AVAIL}" "${SITE_ENABLED}"

# Test config (chưa có SSL cert nên chỉ test HTTP block trước)
# Tạm thời comment HTTPS block để Nginx start được trước khi certbot chạy
sed -i.tmp '/^    listen 443/,/^}/s/^/#/' "${SITE_AVAIL}"

nginx -t
systemctl reload nginx

# ─────────────────────────────────────────────────────────────────────────────
# 3. Lấy SSL cert (certbot tự edit Nginx config)
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Lấy SSL Let's Encrypt…"
certbot --nginx \
    -d "${DOMAIN}" \
    -m "${EMAIL}" \
    --agree-tos \
    --no-eff-email \
    --redirect \
    --hsts \
    --non-interactive

# ─────────────────────────────────────────────────────────────────────────────
# 4. Uncomment HTTPS block + reload
# ─────────────────────────────────────────────────────────────────────────────
# Certbot đã thêm dòng ssl_certificate vào HTTP server — nhưng chúng ta muốn dùng
# block riêng. Reload từ template gốc sau khi cert có sẵn.
sed "s/{{DOMAIN}}/${DOMAIN}/g" /var/www/ota/deploy/vietnix/nginx.conf > "${SITE_AVAIL}"

nginx -t
systemctl reload nginx

# ─────────────────────────────────────────────────────────────────────────────
# 5. Test certbot auto-renew
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Test certbot auto-renew (dry-run)…"
certbot renew --dry-run

# ─────────────────────────────────────────────────────────────────────────────
# 6. Smoke test
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Smoke test HTTPS…"
sleep 2
if curl -sf -o /dev/null -w "%{http_code}\n" "https://${DOMAIN}/api/health"; then
    echo "✓ HTTPS endpoint live"
else
    echo "✗ HTTPS chưa response — kiểm tra DNS đã trỏ về VPS chưa?"
fi

echo
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Nginx + SSL DONE.                                              ║"
echo "║                                                                 ║"
echo "║  Site    : https://${DOMAIN}"
echo "║  Config  : ${SITE_AVAIL}"
echo "║  Logs    : /var/log/nginx/{access,error}.log                    ║"
echo "║  SSL     : /etc/letsencrypt/live/${DOMAIN}/"
echo "║                                                                 ║"
echo "║  Auto-renew: systemctl status certbot.timer                     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
