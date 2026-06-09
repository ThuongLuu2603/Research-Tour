#!/usr/bin/env bash
# Vietnix CHEAP 1 (2vCPU/2GB/40GB Ubuntu 22.04) — provision script
# Chạy với quyền root sau khi SSH lần đầu vào VPS mới.
# Usage: bash setup-vps.sh
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# 0. Pre-flight
# ─────────────────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "Phải chạy với root: sudo bash setup-vps.sh" >&2
    exit 1
fi

if ! grep -qi "ubuntu 22" /etc/os-release; then
    echo "WARN: Script test trên Ubuntu 22.04. OS hiện tại có thể khác." >&2
fi

# ─────────────────────────────────────────────────────────────────────────────
# 1. Swap 4GB (CRITICAL cho 2GB RAM khi sync Vietravel)
# ─────────────────────────────────────────────────────────────────────────────
if [[ ! -f /swapfile ]]; then
    echo "▸ Tạo swap 4GB…"
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    cat > /etc/sysctl.d/99-ota-swap.conf <<EOF
vm.swappiness=10
vm.vfs_cache_pressure=50
EOF
    sysctl -p /etc/sysctl.d/99-ota-swap.conf
fi
free -h

# ─────────────────────────────────────────────────────────────────────────────
# 2. OS update + base tools
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Update OS + install base tools…"
export DEBIAN_FRONTEND=noninteractive
apt update -y
apt upgrade -y
apt install -y \
    ca-certificates curl gnupg lsb-release software-properties-common \
    ufw fail2ban unattended-upgrades \
    build-essential git tmux htop iotop ncdu vim

# ─────────────────────────────────────────────────────────────────────────────
# 3. Firewall (ufw) + fail2ban
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Setup firewall…"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw --force enable
ufw status

systemctl enable --now fail2ban

# ─────────────────────────────────────────────────────────────────────────────
# 4. Python 3.11
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Install Python 3.11…"
add-apt-repository -y ppa:deadsnakes/ppa
apt update -y
apt install -y python3.11 python3.11-venv python3.11-dev python3-pip
python3.11 --version

# ─────────────────────────────────────────────────────────────────────────────
# 5. Node 20
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Install Node 20…"
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
node --version && npm --version

# ─────────────────────────────────────────────────────────────────────────────
# 6. Nginx
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Install Nginx…"
apt install -y nginx
systemctl enable --now nginx

# Giảm worker processes (1 worker đủ cho ~10k req/s)
sed -i 's/^worker_processes auto;/worker_processes 1;/' /etc/nginx/nginx.conf

# ─────────────────────────────────────────────────────────────────────────────
# 7. Postgres 16
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Install Postgres 16…"
install -d /usr/share/postgresql-common/pgdg
curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc
sh -c 'echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
apt update -y
apt install -y postgresql-16 postgresql-contrib-16
systemctl enable --now postgresql

# ─────────────────────────────────────────────────────────────────────────────
# 8. Certbot (Let's Encrypt)
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Install Certbot…"
apt install -y certbot python3-certbot-nginx

# ─────────────────────────────────────────────────────────────────────────────
# 9. Auto OS updates
# ─────────────────────────────────────────────────────────────────────────────
echo "▸ Enable unattended-upgrades…"
dpkg-reconfigure -fnoninteractive unattended-upgrades || true

# ─────────────────────────────────────────────────────────────────────────────
# 10. journald limit (tránh log ăn disk)
# ─────────────────────────────────────────────────────────────────────────────
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/size.conf <<EOF
[Journal]
SystemMaxUse=500M
SystemMaxFileSize=50M
EOF
systemctl restart systemd-journald

# ─────────────────────────────────────────────────────────────────────────────
# 11. Tạo user app `ota`
# ─────────────────────────────────────────────────────────────────────────────
if ! id ota &>/dev/null; then
    echo "▸ Tạo user 'ota'…"
    useradd -m -s /bin/bash ota
    mkdir -p /var/www/ota
    chown ota:ota /var/www/ota
fi

# ─────────────────────────────────────────────────────────────────────────────
# 12. Backup dir
# ─────────────────────────────────────────────────────────────────────────────
mkdir -p /var/backups/ota
chown postgres:postgres /var/backups/ota

# ─────────────────────────────────────────────────────────────────────────────
# DONE
# ─────────────────────────────────────────────────────────────────────────────
echo
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Provision DONE.                                                ║"
echo "║                                                                 ║"
echo "║  Next steps:                                                    ║"
echo "║    1. bash postgres-tune.sh           # Tune Postgres            ║"
echo "║    2. bash deploy-app.sh              # Clone + build + deploy   ║"
echo "║    3. bash setup-nginx.sh <domain>    # Nginx + SSL              ║"
echo "║    4. python3 migrate-from-crdb.py    # Migrate data             ║"
echo "║                                                                 ║"
echo "║  Status:                                                        ║"
echo "║    swap     : $(free -h | awk '/Swap/{print $2}')                                       ║"
echo "║    Python   : $(python3.11 --version 2>&1)                                ║"
echo "║    Node     : $(node --version)                                       ║"
echo "║    Nginx    : $(systemctl is-active nginx)                                       ║"
echo "║    Postgres : $(systemctl is-active postgresql)                                       ║"
echo "╚════════════════════════════════════════════════════════════════╝"
