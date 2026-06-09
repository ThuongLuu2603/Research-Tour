#!/usr/bin/env bash
# Tune Postgres 16 cho Vietnix CHEAP 1 (2GB RAM total, cap ~400MB cho Postgres)
# Chạy SAU setup-vps.sh.
# Usage: bash postgres-tune.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Phải chạy root." >&2
    exit 1
fi

PG_VERSION=16
PG_CONF="/etc/postgresql/${PG_VERSION}/main/postgresql.conf"
PG_HBA="/etc/postgresql/${PG_VERSION}/main/pg_hba.conf"

# ─────────────────────────────────────────────────────────────────────────────
# 1. Tạo DB + user
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Setup user/database…"
read -rsp "Đặt password cho user 'ota': " OTA_PG_PW
echo
if [[ -z "${OTA_PG_PW}" ]]; then
    echo "Password rỗng — abort." >&2
    exit 1
fi

sudo -u postgres psql <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='ota') THEN
        CREATE ROLE ota WITH LOGIN PASSWORD '${OTA_PG_PW}';
    ELSE
        ALTER ROLE ota WITH PASSWORD '${OTA_PG_PW}';
    END IF;
END
\$\$;
SELECT 'role ok' AS status;
EOF

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='ota'" | grep -q 1 \
    || sudo -u postgres createdb -O ota ota

sudo -u postgres psql -d ota -c "GRANT ALL ON SCHEMA public TO ota;"

# ─────────────────────────────────────────────────────────────────────────────
# 2. Tune postgresql.conf cho 2GB RAM
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Tune ${PG_CONF}…"
# Backup
cp "${PG_CONF}" "${PG_CONF}.bak-$(date +%Y%m%d-%H%M%S)"

# Append override block (idempotent — sửa lại nếu chạy lại)
sed -i '/# === OTA TUNING START ===/,/# === OTA TUNING END ===/d' "${PG_CONF}"
cat >> "${PG_CONF}" <<'EOF'

# === OTA TUNING START === (Vietnix CHEAP 1: 2GB RAM)
listen_addresses = 'localhost'
port = 5432
max_connections = 20                  # tight: app pool 3+2=5, +buffer
shared_buffers = 128MB                # ~6% RAM
effective_cache_size = 512MB          # OS+PG cache
work_mem = 8MB                        # per-sort/hash op (× max_connections risk)
maintenance_work_mem = 64MB           # VACUUM / CREATE INDEX
wal_buffers = 8MB
checkpoint_completion_target = 0.9
random_page_cost = 1.1                # SSD
effective_io_concurrency = 200        # SSD
default_statistics_target = 100
synchronous_commit = on               # giữ ACID; off = nhanh hơn nhưng risk mất tx khi crash
log_min_duration_statement = 1000     # log query > 1s
log_checkpoints = on
log_connections = off
log_disconnections = off
log_line_prefix = '%t [%p] %u@%d '
# === OTA TUNING END ===
EOF

# ─────────────────────────────────────────────────────────────────────────────
# 3. pg_hba.conf — chỉ local (Unix socket + 127.0.0.1)
# ─────────────────────────────────────────────────────────────────────────────
# Đảm bảo md5 cho local user
if ! grep -qE "^local\s+all\s+ota\s+md5" "${PG_HBA}"; then
    sed -i '/# === OTA HBA START ===/,/# === OTA HBA END ===/d' "${PG_HBA}"
    cat >> "${PG_HBA}" <<EOF

# === OTA HBA START ===
local   all             ota                                     md5
host    all             ota             127.0.0.1/32            md5
host    all             ota             ::1/128                 md5
# === OTA HBA END ===
EOF
fi

# ─────────────────────────────────────────────────────────────────────────────
# 4. Restart Postgres + verify
# ─────────────────────────────────────────────────────────────────────────────
systemctl restart postgresql
sleep 2
systemctl status postgresql --no-pager | head -5

# Test connection
PGPASSWORD="${OTA_PG_PW}" psql -h 127.0.0.1 -U ota -d ota -c "SELECT version();" || {
    echo "ERROR: Không kết nối được DB ota. Check pg_hba và Postgres logs." >&2
    exit 1
}

# ─────────────────────────────────────────────────────────────────────────────
# 5. Backup cron daily
# ─────────────────────────────────────────────────────────────────────────────
cat > /etc/cron.daily/ota-pg-backup <<'EOF'
#!/usr/bin/env bash
# Daily Postgres backup — giữ 14 ngày local
set -euo pipefail
TS=$(date +%Y%m%d)
BACKUP_FILE="/var/backups/ota/ota-${TS}.sql.gz"
sudo -u postgres pg_dump --no-owner --no-privileges ota | gzip > "${BACKUP_FILE}"
chmod 600 "${BACKUP_FILE}"
find /var/backups/ota -name "ota-*.sql.gz" -mtime +14 -delete
EOF
chmod +x /etc/cron.daily/ota-pg-backup

echo
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Postgres tuning DONE.                                          ║"
echo "║                                                                 ║"
echo "║  DATABASE_URL=postgresql://ota:<password>@127.0.0.1:5432/ota    ║"
echo "║                                                                 ║"
echo "║  Backups: /var/backups/ota/ (daily, 14-day retention)           ║"
echo "║  Restart: systemctl restart postgresql                          ║"
echo "║  Logs:    journalctl -u postgresql -f                           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
