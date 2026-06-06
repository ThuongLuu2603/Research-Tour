# OTA Platform Development Harness

## 목표
End-to-end phát triển OTA platform - từ phân tích requirements → database design → backend/frontend development → QA testing → deployment.

## 트리거
OTA platform development, feature development, bug fixes, optimization requests → use `orchestrate-ota-build` skill hoặc trigger individual agents.

**Examples:**
- "Xây dựng OTA platform từ đầu" → `/orchestrate-ota-build` (full workflow)
- "Thêm feature tour recommendations" → `/orchestrate-ota-build` (Phase 1-2 for new feature)
- "Sửa lỗi booking confirmation" → Trigger `qa-engineer` + `devops-engineer`
- "Tối ưu database queries" → Trigger `db-designer` + `backend-developer`

## Agents & Roles

| Agent | Type | Skill | Trách nhiệm |
|-------|------|-------|-----------|
| requirements-analyst | general-purpose | analyze-requirements | Phân tích yêu cầu, tạo requirements document |
| db-designer | general-purpose | design-database | Thiết kế schema database, migrations |
| backend-developer | general-purpose | develop-backend | Phát triển APIs, models, business logic |
| frontend-developer | general-purpose | develop-frontend | Phát triển UI components, pages, integrations |
| qa-engineer | general-purpose | test-qa | Testing, bug verification, quality assurance |
| devops-engineer | general-purpose | deploy-release | Deployment planning, CI/CD, monitoring |

**Execution Mode:** Agent Team (TeamCreate + SendMessage + TaskCreate)

## Architecture Pattern

```
Requirements Analyst
     ↓ (sequential)
DB Designer
     ↓ (sequential)
Backend Dev + Frontend Dev (parallel)
     ↓ (sequential, after both complete)
QA Engineer
     ↓ (sequential)
DevOps Engineer
```

## Artifacts

### _workspace/ Directory
Generated during orchestration:
- `01_requirements.md` — Requirements document
- `02_db_schema.md` — Database schema & migrations
- `03_backend_changes.md` — Backend implementation guide
- `04_frontend_changes.md` — Frontend implementation guide
- `05_qa_report.md` — Test results & bug list
- `06_deployment_plan.md` — Deployment strategy

### Agent Definitions
Located in `.claude/agents/`:
- `requirements-analyst.md`
- `db-designer.md`
- `backend-developer.md`
- `frontend-developer.md`
- `qa-engineer.md`
- `devops-engineer.md`

### Skills
Located in `.claude/skills/`:
- `analyze-requirements/SKILL.md`
- `design-database/SKILL.md`
- `develop-backend/SKILL.md`
- `develop-frontend/SKILL.md`
- `test-qa/SKILL.md`
- `deploy-release/SKILL.md`
- `orchestrate-ota-build/SKILL.md`

## Change History

| Date | Change | Target | Reason |
|------|--------|--------|--------|
| 2026-06-06 | Initial harness setup | Full (6 agents, 7 skills) | OTA platform development automation |

