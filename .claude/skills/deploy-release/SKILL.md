---
name: deploy-release
description: Chuẩn bị deployment & release pipeline - design CI/CD, environment management, database migrations, monitoring. Dùng khi cần deployment strategy, infrastructure setup, release procedures.
---

# Deploy Release Skill

## Mục đích
Design comprehensive deployment architecture, CI/CD pipeline, environment management, database migration strategy.

## 1. Deployment Architecture

### Staging Environment
- Identical to production (same config, same dependencies)
- Used for pre-production testing
- Separate database (backup from production daily)
- Performance testing ground

### Production Environment
- Render hosting (or similar)
- CockroachDB Cloud
- CDN for static assets
- Monitoring & alerting enabled

## 2. CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      
      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements.txt
      
      - name: Run tests
        run: |
          cd backend
          pytest tests/ --cov=app
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3

  build-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Node
        uses: actions/setup-node@v3
        with:
          node-version: "18"
      
      - name: Install dependencies
        run: cd frontend && npm ci
      
      - name: Build
        run: cd frontend && npm run build
      
      - name: Upload artifact
        uses: actions/upload-artifact@v3
        with:
          name: frontend-build
          path: frontend/dist

  deploy-staging:
    needs: [test, build-frontend]
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment:
      name: staging
    steps:
      - uses: actions/checkout@v3
      
      - name: Deploy to Render (staging)
        run: |
          curl -X POST ${{ secrets.RENDER_DEPLOY_HOOK_STAGING }}

  deploy-production:
    needs: deploy-staging
    runs-on: ubuntu-latest
    environment:
      name: production
    steps:
      - name: Deploy to Render (production)
        run: |
          curl -X POST ${{ secrets.RENDER_DEPLOY_HOOK_PRODUCTION }}
```

## 3. Environment Management

### Environment Variables
```bash
# .env.production
DATABASE_URL=postgresql://user:pass@db.cockroachdb.cloud:26257/otadb
DEBUG=false
LOG_LEVEL=info
CORS_ORIGINS=https://ota-platform.com
JWT_SECRET_KEY=${SECURE_JWT_KEY}
PAYMENT_API_KEY=${SECURE_PAYMENT_KEY}
```

### Secrets Management
- Store in GitHub Secrets
- Rotate JWT keys regularly
- Use environment-specific keys (staging ≠ production)
- Never commit `.env.local`

## 4. Database Migrations

### Migration Strategy
```sql
-- migrations/versions/001_initial_schema.py
"""Initial schema creation"""

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        'tours',
        sa.Column('id', sa.UUID(), server_default=sa.func.gen_random_uuid()),
        sa.Column('title', sa.String(255), nullable=False),
        # ... more columns
    )

def downgrade():
    op.drop_table('tours')
```

### Migration Execution
```bash
# Before deployment
alembic upgrade head

# Rollback if needed
alembic downgrade -1
```

### Data Backfill (for new columns)
```python
def upgrade():
    # Add new column with default
    op.add_column('bookings', 
        sa.Column('reference_code', sa.String(20), nullable=False, default='TEMP')
    )
    
    # Backfill existing data
    conn = op.get_bind()
    conn.execute("UPDATE bookings SET reference_code = 'BOOK-' || id LIMIT 1000")
```

## 5. Deployment Checklist

### Pre-deployment
- [ ] All tests passing (unit + integration)
- [ ] Code review approved
- [ ] No breaking changes in API
- [ ] Database migration tested in staging
- [ ] Secrets configured in target environment
- [ ] Monitoring alerts configured
- [ ] Rollback plan documented

### Deployment (Staging)
- [ ] Deploy backend & frontend to staging
- [ ] Run smoke tests against staging
- [ ] Verify database migrations applied
- [ ] Check logs for errors
- [ ] Test critical flows manually

### Deployment (Production)
- [ ] Backup production database
- [ ] Deploy during low-traffic window
- [ ] Run smoke tests against production
- [ ] Monitor error rates & performance
- [ ] Check payment processing
- [ ] Monitor user activity

### Post-deployment
- [ ] Verify features working as expected
- [ ] Check performance metrics (API latency, DB queries)
- [ ] Monitor error logs for anomalies
- [ ] Keep ready for rollback (within 1 hour)

## 6. Rollback Strategy

### Blue-Green Deployment
```
Blue (current)  ← Traffic → Green (new)
                              ↓
                           Deploy new
                              ↓
                           Test in Green
                              ↓
                           Switch traffic
                              ↓
                   (if error: switch back)
```

### Database Rollback
```bash
# If migrations fail, rollback
alembic downgrade -1

# Restore from backup if data corruption
pg_restore production_backup.sql
```

## 7. Monitoring & Alerting

### Key Metrics
- API response time (target < 500ms)
- Error rate (target < 1%)
- Database connection pool usage
- Payment success rate

### Alert Rules
```yaml
# Example: High error rate
alert: HighErrorRate
condition: error_rate > 0.05
duration: 5m
annotations:
  summary: "Error rate {{ $value }} exceeds threshold"
  action: "Check logs, rollback if critical"
```

## 8. Release Notes Template

```markdown
# Release v1.0.0

## Features
- Added tour search with filters
- Implemented booking system
- Added payment processing

## Improvements
- Optimized database queries (-40% latency)
- Improved mobile UI responsiveness
- Enhanced error messages

## Fixes
- Fixed price calculation bug
- Fixed mobile layout issue
- Fixed authentication timeout

## Breaking Changes
- Deprecated /api/v1/tours (use /api/v2/tours)
- Auth endpoint now requires user-agent header

## Deployment Notes
- Database migration required (run alembic upgrade)
- No downtime expected
- Rollback possible within 1 hour
```

## 9. Monitoring Dashboard

Setup monitoring for:
- API endpoint latency (by endpoint)
- Database query performance
- Error rates (by error type)
- User activity (logins, bookings, payments)
- System resources (CPU, memory, disk)

## 10. Troubleshooting Guide

| Issue | Symptom | Resolution |
|-------|---------|-----------|
| Database connection pool exhausted | 502 errors | Increase pool size, check for connection leaks |
| Slow API responses | Timeout errors | Check database queries, add indexes |
| Failed migrations | Deployment blocked | Rollback, fix migration, test in staging |
| Payment processing down | Bookings fail | Check payment API status, enable fallback |

## Key Principles
1. **Staging always matches production** — catch issues before production
2. **Automated testing before deployment** — reduce manual testing
3. **Database migrations must be reversible** — enable safe rollback
4. **Monitor immediately after deployment** — catch errors quickly
5. **Keep runbooks for common issues** — speed up troubleshooting

