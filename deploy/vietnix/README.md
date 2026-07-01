# Vietnix VPS Deployment — Runbook

Step-by-step để deploy OTA platform lên Vietnix Cloud VPS CHEAP 1 (2vCPU/2GB/40GB) với self-host Postgres.

Đầy đủ context kiến trúc + quyết định: xem `_workspace/06_deployment_plan.md`.

---

## Pre-flight

- [ ] VPS Vietnix CHEAP 1 đã active, có IP public
- [ ] OS Ubuntu 22.04 LTS đã cài
- [ ] SSH key của bạn đã add vào `/root/.ssh/authorized_keys`
- [ ] Domain (vd `ota.example.com`) đã trỏ A record về IP VPS — HOẶC giữ DNS hiện tại cho đến Phase G (cutover)
- [ ] Sao lưu env vars hiện tại trên Render (chụp Environment tab)
- [ ] CockroachDB Serverless connection string sẵn để dump

---

## Sequence

### Phase A — Chuẩn bị local (10 phút)

1. SSH thử kết nối VPS:
   ```bash
   ssh root@<vps-ip>
   ```

2. Export env vars Render → file local:
   ```bash
   # Render Dashboard → Environment → "Show value" tất cả → paste vào env.production.local
   ```

3. Dump CRDB (local hoặc server có psql):
   ```bash
   # Optional — không cần nếu dùng migrate-from-crdb.py (script live-copy)
   ```

### Phase B — Provision VPS (30 phút)

Copy repo lên VPS (tạm thời để chạy script):
```bash
ssh root@<vps-ip>
git clone https://github.com/<user>/ota-platform.git /tmp/ota-bootstrap
cd /tmp/ota-bootstrap/deploy/vietnix
bash setup-vps.sh
```

Script sẽ:
- Tạo swap 4GB
- Cài Python 3.11, Node 20, Nginx, Postgres 16, certbot, ufw, fail2ban
- Setup firewall + auto OS updates
- Tạo user `ota` + thư mục `/var/www/ota`

### Phase C — Setup Postgres (10 phút)

```bash
cd /tmp/ota-bootstrap/deploy/vietnix
bash postgres-tune.sh
```

Script sẽ hỏi password cho user `ota` Postgres. Note lại để điền vào `.env`.

Output: `DATABASE_URL=postgresql://ota:<password>@127.0.0.1:5432/ota`

### Phase D — Deploy app (30 phút)

```bash
cd /tmp/ota-bootstrap/deploy/vietnix
bash deploy-app.sh https://github.com/<user>/ota-platform.git
```

Lần đầu chạy script sẽ:
- Clone repo vào `/var/www/ota`
- Tạo venv + cài deps
- Copy `env.template` → `/var/www/ota/backend/.env`
- **DỪNG** và yêu cầu bạn edit `.env`

Edit env vars:
```bash
sudo -u ota nano /var/www/ota/backend/.env
# Điền:
#   DATABASE_URL (từ Phase C)
#   JWT_SECRET, SESSION_SECRET (copy từ Render)
#   GOOGLE_SHEETS_CREDENTIALS_JSON, etc. (copy từ Render)
#   CORS_ORIGINS=https://<domain>
```

Rerun script:
```bash
bash deploy-app.sh https://github.com/<user>/ota-platform.git
```

Lần này script sẽ:
- Build frontend
- Cài systemd unit `ota-backend`
- Start service
- Smoke test `/health` qua unix socket

### Phase E — Nginx + SSL (15 phút)

⚠ **Đảm bảo DNS đã trỏ về IP VPS trước khi chạy** (cần để Let's Encrypt verify domain).

```bash
cd /tmp/ota-bootstrap/deploy/vietnix
bash setup-nginx.sh ota.example.com admin@example.com
```

Script sẽ:
- Render `nginx.conf` template
- Tạm comment HTTPS block (Nginx start được trước cert)
- Chạy certbot lấy SSL cert
- Uncomment HTTPS block + reload
- Test auto-renew dry-run

Sau bước này site đã live ở `https://ota.example.com`.

### Phase F — Migrate data từ CRDB (30 phút)

⚠ **App đang chạy trên Postgres trống**. Migration giữ Render online, copy data sang Vietnix.

```bash
cd /var/www/ota/deploy/vietnix
sudo -u ota /var/www/ota/backend/venv/bin/python migrate-from-crdb.py \
    --source 'cockroachdb+psycopg2://<user>:<pass>@<crdb-host>:26257/defaultdb?sslmode=verify-full' \
    --target 'postgresql://ota:<password>@127.0.0.1:5432/ota'
```

Script sẽ:
1. Init schema trên Postgres (qua `database.init_db()`)
2. Copy từng bảng theo thứ tự FK (defer constraints khi insert)
3. Resync sequences
4. Verify row counts

Nếu fail → check log + fix → rerun với `--skip-schema` (schema đã có).

### Phase G — DNS cutover (5 phút + 1-24h propagation)

1. **T-1h trước cutover** (nếu DNS chưa trỏ Vietnix):
   - Vào DNS provider → hạ TTL record `ota.example.com` xuống **300s**
   - Chờ ít nhất = TTL cũ (vd nếu cũ là 3600s thì chờ 1h)

2. **Cutover**:
   - Đổi A record `ota.example.com` từ Render IP/CNAME sang IP Vietnix
   - Save

3. **Verify**:
   ```bash
   dig +short ota.example.com
   curl -I https://ota.example.com/healthz
   ```
   Check propagation: https://www.whatsmydns.net

4. **Sau 24h ổn định** → nâng TTL về **3600s**

### Phase H — CI/CD (30 phút, optional)

1. **Tạo deploy user** trên VPS (không dùng root cho deploy):
   ```bash
   ssh root@<vps-ip>
   adduser deploy
   usermod -aG sudo deploy
   # Sửa sudoers cho phép restart service không cần password
   echo 'deploy ALL=(ALL) NOPASSWD: /bin/systemctl reload-or-restart ota-backend, /bin/systemctl reload nginx' \
       > /etc/sudoers.d/deploy-ota
   # Add SSH key của GitHub Actions
   mkdir -p /home/deploy/.ssh
   chmod 700 /home/deploy/.ssh
   # Paste public key của ed25519 cặp khóa CI/CD
   nano /home/deploy/.ssh/authorized_keys
   chmod 600 /home/deploy/.ssh/authorized_keys
   chown -R deploy:deploy /home/deploy/.ssh
   # Cho deploy quyền edit /var/www/ota
   usermod -aG ota deploy
   chmod -R g+w /var/www/ota
   ```

2. **GitHub Secrets** (Repo Settings → Secrets and variables → Actions):
   - `VIETNIX_HOST`: IP hoặc domain VPS
   - `VIETNIX_SSH_KEY`: private key (cặp khóa ed25519, public key đã add vào VPS)

3. **Test push**:
   ```bash
   git commit --allow-empty -m "Test Vietnix deploy"
   git push origin main
   ```
   Xem progress ở GitHub Actions tab.

---

## Post-deploy

### Monitoring

Setup uptime-kuma trên VPS:
```bash
docker run -d --restart=always -p 127.0.0.1:3001:3001 \
    -v uptime-kuma:/app/data \
    --name uptime-kuma louislam/uptime-kuma:1
```

Add Nginx location:
```nginx
location /uptime/ {
    auth_basic "Monitoring";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://127.0.0.1:3001/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

### Daily check (manual hoặc cron)

```bash
# RAM + swap
free -h

# Disk
df -h /

# Service health
systemctl status ota-backend nginx postgresql

# Backend logs (last 100)
journalctl -u ota-backend -n 100 --no-pager

# Postgres slow queries (> 1s, đã set trong tune)
sudo -u postgres tail -50 /var/log/postgresql/postgresql-16-main.log

# Active DB connections
sudo -u postgres psql -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"
```

### Backup verify (weekly)

```bash
ls -lh /var/backups/ota/
# Test restore vào DB tạm:
sudo -u postgres createdb ota_test
gunzip < /var/backups/ota/ota-20260601.sql.gz | sudo -u postgres psql -d ota_test
sudo -u postgres psql -d ota_test -c "SELECT COUNT(*) FROM tours;"
sudo -u postgres dropdb ota_test
```

---

## Rollback

### App-level: revert sang commit cũ

```bash
ssh deploy@<vps-ip>
cd /var/www/ota
git log --oneline -10
git reset --hard <commit-sha-cũ>
backend/venv/bin/pip install -r backend/requirements.txt --quiet
sudo systemctl restart ota-backend
```

### DNS: rollback sang Render

DNS provider → đổi A record về Render IP/CNAME → propagate ~5 phút (TTL 300s).

### Data: restore Postgres backup

```bash
sudo systemctl stop ota-backend
sudo -u postgres dropdb ota
sudo -u postgres createdb -O ota ota
gunzip < /var/backups/ota/ota-<date>.sql.gz | sudo -u postgres psql -d ota
sudo systemctl start ota-backend
```

### VPS-level: Vietnix snapshot restore

Trong Vietnix panel → Snapshots → Restore (mất khoảng 5-10 phút).

---

## Troubleshooting

| Triệu chứng | Nguyên nhân khả dĩ | Fix |
|---|---|---|
| Backend `502 Bad Gateway` | uvicorn crash / chưa start | `journalctl -u ota-backend -n 50`, `systemctl restart ota-backend` |
| `OOM killer` giết process | Vietravel sync peak > 2GB | Check `dmesg \| grep -i oom`, giảm batch scraper, hoặc upgrade NVMe 2 |
| `FATAL: too many connections` Postgres | App pool tràn | Check `pg_stat_activity`, giảm `OTA_DB_POOL_SIZE` |
| Site chậm sau cutover | DNS chưa propagate hết | Chờ TTL hết, kiểm tra `dig` từ nhiều nguồn |
| SSL cert expired | certbot.timer disabled | `systemctl status certbot.timer`, `certbot renew` |
| Disk full | Logs/backups không rotate | `du -sh /var/log/* /var/backups/*`, cleanup cũ |

---

## Files reference

| File | Mục đích |
|---|---|
| `setup-vps.sh` | Provision Ubuntu (Phase B) |
| `postgres-tune.sh` | Tune Postgres + tạo DB (Phase C) |
| `deploy-app.sh` | Deploy app + service (Phase D) |
| `setup-nginx.sh` | Nginx + SSL (Phase E) |
| `migrate-from-crdb.py` | Data migration CRDB→PG (Phase F) |
| `nginx.conf` | Nginx config template |
| `ota-backend.service` | systemd unit |
| `env.template` | Env vars template |
| `../.github/workflows/deploy-vietnix.yml` | CI/CD (Phase H) |
