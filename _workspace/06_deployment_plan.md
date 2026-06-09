# Deployment Plan: Render → Vietnix VPS CHEAP 1 + Self-host Postgres

**Date:** 2026-06-09
**Owner:** thuon
**Status:** Ready to execute

---

## 1. Why

Render free tier issues (đã document trong `~/.claude/.../project_cockroach_perf.md`):
- Cold start 30-60s sau 15min idle
- US-region → ~200ms RTT từ Việt Nam
- CockroachDB Serverless cũng ở US → backend↔DB latency cao

Target sau migration:
- TTFB từ VN: **~50-100ms** (vs ~500ms-60s hiện tại)
- Speedup ước tính **5-10×** cho request thường, **vô hạn** cho cold-start
- Self-host Postgres trên cùng VPS → app↔DB **≈ 0ms latency**

## 2. Target Architecture

```
Internet ──→ Vietnix Cloud VPS CHEAP 1 (HCM, 2vCPU/2GB/40GB)
              │
              ├─ Nginx 1.24 (TLS 443, redirect 80)
              │   ├─ /         → /var/www/ota/frontend/dist (static)
              │   └─ /api/*    → unix:/var/www/ota/backend/ota.sock
              │
              ├─ systemd: ota-backend (1 uvicorn worker)
              │   └─ FastAPI :8000 (unix socket)
              │
              ├─ systemd: postgresql-16
              │   └─ Postgres minimal config (~400MB RAM cap)
              │
              └─ /swapfile (4GB) — đệm khi Vietravel sync peak
```

## 3. VPS Spec & Tuning

**Gói: Vietnix Cloud VPS CHEAP 1**
- 2 vCPU Intel Xeon E5 v2
- 2 GB RAM
- 40 GB SSD
- Linux (Ubuntu 22.04 LTS khuyến nghị)
- HCM datacenter

**RAM budget (2GB):**

| Component | RAM cap | Note |
|---|---|---|
| Ubuntu OS + buffer | 350 MB | systemd, sshd, journald |
| Nginx | 50 MB | worker_processes 1 |
| **Postgres 16** | **400 MB** | shared_buffers=128MB, work_mem=8MB |
| FastAPI backend | 250 MB | 1 uvicorn worker |
| APScheduler + cache | 150 MB | Reduce TTL, no aggressive prefetch |
| Free headroom | 250 MB | |
| Tour scraper peak | +600 MB | Goes into swap when active |
| **Total normal** | **~1.4 GB** | |
| **Total peak (sync)** | **~2.0 GB + swap** | OOM risk if no swap |

**Disk budget (40GB):**

| Mục | Size |
|---|---|
| Ubuntu OS + apt cache + logs | 5 GB |
| Backend venv + node_modules | 800 MB |
| Frontend dist | 50 MB |
| Swap file | 4 GB |
| Postgres data dir | ~2 GB (Tour 8k + Festival 3k + History snapshots) |
| Postgres WAL | 1 GB |
| App logs (rotated) | 500 MB |
| **Free** | **~26 GB** |

## 4. Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Web server | Nginx | Industry standard, gzip/brotli/HTTP2 builtin |
| WSGI runner | gunicorn + uvicorn worker | Better process management than bare uvicorn |
| Workers | **1** | RAM cap (vs 2-4 normal). CPU 2vCPU vẫn xử lý OK |
| Socket | Unix socket | Faster than TCP localhost ~10%, no port conflict |
| Service manager | systemd | Built-in Ubuntu, journald logging |
| DB | **Postgres 16** | User chose Option B; minimal RAM footprint vs CRDB |
| DB Pool | size=3, overflow=2 | Tight để không vượt Postgres `max_connections=20` |
| SSL | Let's Encrypt + certbot | Free, auto-renew |
| Firewall | ufw + fail2ban | Block brute-force SSH |

## 5. Code Refactor (~30 phút effort)

Audit code result: **KHÔNG có CRDB-specific feature đang dùng**. Chỉ cần:

### 5.1. `backend/database.py` — tune pool cho low-RAM
```python
elif _is_postgres:
    # Vietnix CHEAP 1: 2GB RAM total, Postgres cap 400MB → max_connections=20
    # → SQLAlchemy pool 3+2=5 (1 worker × 5 conn = an toàn)
    engine_kwargs = {
        "pool_pre_ping": True,
        "pool_size": 3,
        "max_overflow": 2,
        "pool_recycle": 300,
    }
```

### 5.2. Data migration CRDB → Postgres
- Export: `cockroach sql --url=$CRDB_URL --execute="COPY ... TO STDOUT"` per table
- Import: `psql $PG_URL -c "COPY ... FROM STDIN"`
- Sync sequences sau import: `SELECT setval(pg_get_serial_sequence(t, 'id'), (SELECT COALESCE(MAX(id),0)+1 FROM t))` cho mọi table
- Script: `deploy/vietnix/migrate-from-crdb.py`

### 5.3. Không cần đổi
- `models.py` — `Integer, primary_key=True` → Postgres SERIAL auto
- `db_job_lock.py` — row-based lease lock đã Postgres-compat
- `api/*.py` — `_serialize_id` patterns vẫn an toàn (Postgres bigserial cũng có thể vượt 2^53 sau nhiều năm)

## 6. Migration Phases (~3.5h total)

### Phase A — Chuẩn bị (offline, không downtime)
- A1. Order VPS Vietnix CHEAP 1, OS Ubuntu 22.04, HCM
- A2. Generate SSH key pair, add public key vào VPS
- A3. Export env vars hiện tại từ Render
- A4. Backup CRDB: `cockroach dump --url=$CRDB_URL --dump-mode=data > crdb-data.sql`

### Phase B — Provision VPS (30 phút)
- B1. SSH harden: disable root, key-only, fail2ban
- B2. Install stack: Python 3.11, Node 20, Nginx, Postgres 16, certbot
- B3. Tạo swap 4GB
- B4. ufw enable, allow 22/80/443

### Phase C — Setup Postgres (20 phút)
- C1. Tạo user/db: `CREATE USER ota WITH PASSWORD '...'; CREATE DATABASE ota OWNER ota;`
- C2. Tune `postgresql.conf`: shared_buffers=128MB, effective_cache_size=512MB, max_connections=20, work_mem=8MB
- C3. Restart Postgres

### Phase D — Deploy app (30 phút)
- D1. `git clone` → /var/www/ota
- D2. Backend venv + pip install
- D3. Frontend `npm ci && npm run build`
- D4. Tạo `/var/www/ota/backend/.env` (copy từ Render env, override DATABASE_URL)
- D5. Setup systemd service `ota-backend`

### Phase E — Nginx + SSL (15 phút)
- E1. Copy `nginx.conf` template → `/etc/nginx/sites-available/ota`
- E2. `nginx -t && systemctl reload nginx`
- E3. `certbot --nginx -d ota.example.com`

### Phase F — Migrate data (30 phút)
- F1. Run `migrate-from-crdb.py` để dump+restore từ CRDB Serverless
- F2. Verify row counts match
- F3. Re-sync sequences
- F4. Smoke test: login + load tours + sync test

### Phase G — DNS cutover (5 phút active)
- G1. Lower TTL hiện tại → 300s (T-1h)
- G2. Update A record → IP Vietnix
- G3. Monitor `dig` từ nhiều region
- G4. Sau 24h stable → TTL về 3600s

### Phase H — CI/CD (30 phút)
- H1. GitHub Actions workflow `.github/workflows/deploy-vietnix.yml`
- H2. SSH deploy key trong repo Secrets
- H3. Test push trigger

## 7. Rollback Plan

**T+48h giữ Render chạy song song** — không tắt vội.

| Trigger | Action | Recovery time |
|---|---|---|
| App lỗi sau cutover | DNS đổi A record về Render | ~5 phút (TTL 300s) |
| Data mismatch | Re-export CRDB → re-import Postgres | ~30 phút |
| VPS crash | Vietnix snapshot restore | ~10 phút (snapshot trước mỗi deploy) |
| Sau 1 tuần ổn | Shutdown Render service | — |

## 8. Operational Concerns

| Vấn đề | Trên Render | Trên Vietnix cần tự lo |
|---|---|---|
| OS patches | Auto | `unattended-upgrades` (configured Phase B) |
| SSL renewal | Auto | `certbot.timer` (auto) |
| Log rotation | Auto | journald cap 500MB (configured Phase B) |
| App backup | N/A (stateless) | VPS snapshot weekly |
| **DB backup** | CRDB Serverless auto-backup | **`pg_dump` cron daily → upload tới external storage** |
| Monitoring | Render dashboard | uptime-kuma self-host (port 3001) |
| Alert | Render email | Telegram bot via uptime-kuma |

**DB backup cron:**
```bash
# /etc/cron.daily/ota-pg-backup
0 3 * * * sudo -u postgres pg_dump ota | gzip > /var/backups/ota-$(date +\%Y\%m\%d).sql.gz
find /var/backups -name "ota-*.sql.gz" -mtime +14 -delete
```

## 9. Cost Comparison

| Item | Render Free | Render Starter | Vietnix CHEAP 1 |
|---|---|---|---|
| Backend hosting | $0 (cold start) | $7/mo | — |
| Frontend hosting | $0 | $0 | — |
| VPS | — | — | ~250k VNĐ/mo (~$10) |
| DB | $0 (CRDB Free) | $0 | $0 (self-host) |
| **Monthly** | **$0** | **$7** | **~$10** |
| **Yearly** | **$0** | **$84** | **~$120** |

## 10. Files to Create

In repo:
- `deploy/vietnix/setup-vps.sh` — Phase B+C provision script
- `deploy/vietnix/postgres-init.sql` — Phase C database setup
- `deploy/vietnix/postgresql.conf` — Tuning template
- `deploy/vietnix/nginx.conf` — Production Nginx config
- `deploy/vietnix/ota-backend.service` — systemd unit
- `deploy/vietnix/migrate-from-crdb.py` — Data migration script
- `deploy/vietnix/env.template` — env vars checklist
- `deploy/vietnix/README.md` — Step-by-step runbook
- `.github/workflows/deploy-vietnix.yml` — Auto deploy
- `backend/database.py` — Update pool config (1 file edit)

## 11. Pre-flight Checklist

- [ ] VPS Vietnix CHEAP 1 đã active, có IP
- [ ] SSH key đã add vào `/root/.ssh/authorized_keys`
- [ ] Domain (vd `ota.example.com`) đã có, kiểm soát DNS
- [ ] Env vars từ Render đã export ra file `.env.production` local
- [ ] CRDB Serverless connection string sẵn cho dump
- [ ] Snapshot Render service ID, deploy hook URL (cho rollback)
- [ ] GitHub repo deploy key đã tạo

## 12. Success Criteria

Sau deploy:
- `curl https://ota.example.com/api/health` < 100ms TTFB từ VN
- Sync Vietravel full hoàn tất không OOM (peak RAM < 1.9GB)
- Đăng nhập + load 1000 tours < 1s
- Festival module load < 500ms
- `systemctl status ota-backend` green > 24h
- Certbot auto-renew test pass

## 13. Open Risks

1. **2GB RAM tight cho Vietravel sync** — mitigation: 4GB swap, scraper batch nhỏ. Nếu hit OOM > 3 lần/tuần → upgrade NVMe 2 (4GB RAM, 500k/mo)
2. **40GB SSD đầy sau 12-18 tháng** nếu daily snapshots tích lũy → cron cleanup `find -mtime +14 -delete`
3. **Single point of failure** — VPS down = toàn bộ app down. Mitigation: Vietnix SLA + weekly snapshot
4. **Postgres major upgrade** — cần manual (vs CRDB auto). Tài liệu hóa trong runbook
