# Deploy OTA Platform lên VPS (Docker)

Stack: **app** (FastAPI + React) + **Postgres 16** + **Redis 7**.

## Lần đầu (VPS Ubuntu 22.04+)

```bash
ssh root@<IP-VPS>
git clone https://github.com/ThuongLuu2603/Research-Tour.git /opt/ota-platform
cd /opt/ota-platform
sudo bash deploy/docker/vps-setup.sh
```

Script cài Docker (nếu chưa có), copy `deploy/docker/env.production.example` → `.env`.

Sửa `.env`:

- `POSTGRES_PASSWORD` — mật khẩu DB
- `SECRET_KEY` — `openssl rand -hex 32`
- `GOOGLE_CREDENTIALS_JSON` — service account Sheets
- `FRONTEND_URL` — `https://domain` hoặc `http://IP:8000`

Chạy:

```bash
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

Mở UI: `http://<IP-VPS>:8000`

## Cập nhật sau này

```bash
cd /opt/ota-platform
bash deploy/docker/vps-deploy.sh
```

## Nginx + SSL (tùy chọn)

Trỏ domain về IP VPS, rồi dùng runbook đầy đủ: `deploy/vietnix/README.md` (Phase E).

Hoặc reverse proxy đơn giản:

```nginx
server {
    listen 443 ssl http2;
    server_name ota.example.com;
    # ssl_certificate ... (certbot)

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
    }
}
```

Đặt `FRONTEND_URL=https://ota.example.com` trong `.env` rồi `docker compose up -d`.

## Vietnix (systemd, không Docker)

Runbook chi tiết hơn (Postgres host, Nginx, migrate CRDB): `deploy/vietnix/README.md`
