---
name: orchestrate-ota-build
description: Orchestrate OTA platform development - xây dựng requirements → database design → backend/frontend development → testing → deployment. Dùng khi xây dựng hoặc phát triển OTA platform features, phân loại features thành phases, hay cần overview toàn bộ workflow.
---

# Orchestrate OTA Platform Build

## Mục đích
Điều phối toàn bộ quy trình phát triển OTA platform: từ phân tích yêu cầu → thiết kế database → phát triển backend & frontend → QA testing → deployment.

**Thực thi mode:** Agent Team (6 agents phối hợp)

## Workflow

Harness này thực hiện **Pipeline + Parallel** architecture:

```
Requirements Analyst (Phase 1)
         ↓
DB Designer (Phase 2)
         ↓
Backend Dev + Frontend Dev (Phase 3, parallel)
         ↓
QA Engineer (Phase 4)
         ↓
DevOps Engineer (Phase 5)
```

### Phase 0: Context Confirmation

Xác định execution mode:

1. **Initial Build:** Xây dựng từ đầu
   - Tạo `_workspace/` directory mới
   - Tạo requirements, schema, implementations mới
   - Full workflow Phase 1-5

2. **Existing Expansion:** Mở rộng tính năng hiện có
   - Sử dụng `_workspace/` cũ (nếu có)
   - Cập nhật requirements / schema / implementations
   - Phase tùy theo loại changes

3. **Bug Fix / Maintenance:** Sửa lỗi hoặc bảo trì
   - Xác định component cần fix
   - QA cập nhật test suite
   - DevOps deploy fix

**Hỏi user:** "Bạn muốn xây dựng OTA platform từ đầu hay mở rộng tính năng hiện có?"

---

### Phase 1: Requirements Analysis

**Agent:** `requirements-analyst` (general-purpose)  
**Skill:** `analyze-requirements`  
**Duration:** 15-30 phút

**Input:**
- Project scope & feature description
- Existing API endpoints (nếu có)
- User personas & use cases

**Output:**
- `_workspace/01_requirements.md` chứa:
  - Executive summary
  - Functional requirements (phân loại by feature)
  - Non-functional requirements
  - Constraints & assumptions
  - External dependencies
  - Success criteria

**Checkpoint:** Requirements document hoàn chỉnh, rõ ràng, sẵn sàng cho phase tiếp theo

---

### Phase 2: Database Design

**Agent:** `db-designer` (general-purpose)  
**Skill:** `design-database`  
**Duration:** 20-30 phút

**Input:**
- `_workspace/01_requirements.md` từ Phase 1
- Existing models.py (reference CockroachDB compatibility)

**Output:**
- `_workspace/02_db_schema.md` chứa:
  - Entity-Relationship Diagram (description)
  - SQL CREATE TABLE statements
  - Indexes strategy
  - Migration plan (alembic)
  - CockroachDB specific notes

**Checkpoint:** Schema hoàn chỉnh, tested với CockroachDB SQL, sẵn sàng migrate

---

### Phase 3A: Backend Development (Parallel)

**Agent:** `backend-developer` (general-purpose)  
**Skill:** `develop-backend`  
**Duration:** 30-60 phút

**Input:**
- `_workspace/01_requirements.md`
- `_workspace/02_db_schema.md`
- Existing backend code (api/, models.py, database.py)

**Output:**
- `_workspace/03_backend_changes.md` chứa:
  - New/modified API endpoints
  - SQLAlchemy models
  - Business logic implementation
  - Integration points
  - Test cases
  - Code examples (for copy-paste into actual repo)

**Parallel with Phase 3B**

---

### Phase 3B: Frontend Development (Parallel)

**Agent:** `frontend-developer` (general-purpose)  
**Skill:** `develop-frontend`  
**Duration:** 30-60 phút

**Input:**
- `_workspace/01_requirements.md`
- `_workspace/02_db_schema.md` (for data model understanding)
- `_workspace/03_backend_changes.md` (receive after backend completes)
- Existing frontend code (src/components, src/pages, etc.)

**Output:**
- `_workspace/04_frontend_changes.md` chứa:
  - New/modified components
  - New/modified pages & routes
  - State management changes
  - API integration points
  - UI/UX implementation notes
  - Test cases
  - Code examples (for copy-paste into actual repo)

**Parallel with Phase 3A, receives from Backend when available**

---

### Phase 4: QA Testing

**Agent:** `qa-engineer` (general-purpose)  
**Skill:** `test-qa`  
**Duration:** 30-45 phút

**Input:**
- `_workspace/01_requirements.md`
- `_workspace/02_db_schema.md`
- `_workspace/03_backend_changes.md`
- `_workspace/04_frontend_changes.md`
- Full codebase (for test writing)

**Output:**
- `_workspace/05_qa_report.md` chứa:
  - Requirements coverage matrix
  - API test cases (request/response contracts)
  - Database integrity tests
  - Frontend functional tests
  - Integration tests (API ↔ Frontend)
  - Bug list (if any)
  - Recommendations

**Checkpoint:** All requirements verified, bugs documented, ready for deployment OR blocked if critical bugs

---

### Phase 5: Deployment Planning

**Agent:** `devops-engineer` (general-purpose)  
**Skill:** `deploy-release`  
**Duration:** 15-20 phút

**Input:**
- `_workspace/01_requirements.md`
- `_workspace/02_db_schema.md`
- `_workspace/03_backend_changes.md`
- `_workspace/04_frontend_changes.md`
- `_workspace/05_qa_report.md`
- Existing infrastructure (Render, CockroachDB Cloud)

**Output:**
- `_workspace/06_deployment_plan.md` chứa:
  - Deployment architecture
  - CI/CD pipeline configuration
  - Database migration plan
  - Rollback procedure
  - Monitoring setup
  - Deployment checklist
  - Troubleshooting guide

**Checkpoint:** Deployment plan approved, ready to execute

---

## Data Flow

| Phase | Input Files | Output Files | Comments |
|-------|------------|--------------|----------|
| 1 | - | 01_requirements.md | Sequential start |
| 2 | 01_requirements.md | 02_db_schema.md | Sequential |
| 3A | 01_requirements.md, 02_db_schema.md | 03_backend_changes.md | Parallel with 3B |
| 3B | 01_requirements.md, 02_db_schema.md, 03_backend_changes.md | 04_frontend_changes.md | Parallel with 3A |
| 4 | 01_requirements.md, 02_db_schema.md, 03_backend_changes.md, 04_frontend_changes.md | 05_qa_report.md | Sequential |
| 5 | All previous | 06_deployment_plan.md | Sequential final |

---

## Error Handling

| Scenario | Impact | Resolution |
|----------|--------|-----------|
| Unclear requirements | Phase 1 blocked | Ask user for clarification |
| Schema too complex | Phase 2 blocked | Propose simplified version, discuss |
| Implementation conflicts | Phase 3 blocked | Backend & Frontend discuss via SendMessage |
| Critical QA bugs | Phase 4 blocked | Ask developers fix, re-test |
| Deployment issues | Phase 5 blocked | Escalate to DevOps team |

**Policy:** 1x retry on error. If retries fail, escalate to user with recommendation.

---

## Success Criteria

✅ **Phase 1:** Requirements document is clear, complete, approved  
✅ **Phase 2:** Database schema is valid CockroachDB SQL, migrations planned  
✅ **Phase 3:** Backend & Frontend code examples provided, testable in isolation  
✅ **Phase 4:** All requirements tested, bugs documented (if any)  
✅ **Phase 5:** Deployment plan approved, ready for production rollout  

---

## Team Communication Protocol

### Requirements Analyst → DB Designer
- **Via:** Message (requirements questions), File (`_workspace/01_requirements.md`)
- **Decision:** "Requirements clear enough to design schema?"

### DB Designer → Backend Dev + Frontend Dev
- **Via:** Message (schema questions), File (`_workspace/02_db_schema.md`)
- **Broadcast:** "Schema ready, proceed with implementation"

### Backend Dev ↔ Frontend Dev (Parallel)
- **Via:** Message (API contract discussion), File (`_workspace/03_backend_changes.md`)
- **Backend → Frontend:** "API endpoints ready, here's contract"
- **Frontend → Backend:** "Need this additional field, request/response change"

### Implementation Phase → QA Engineer
- **Via:** Message (test cases), File (`_workspace/03_backend_changes.md`, `_workspace/04_frontend_changes.md`)
- **QA:** "Ready to test?"

### QA Engineer → DevOps Engineer
- **Via:** Message (deployment approval/concerns), File (`_workspace/05_qa_report.md`)
- **Decision:** "All tests pass, proceed with deployment OR blocks deployment until fixes"

---

## Follow-up Work

Harness này hỗ trợ follow-up requests:
- "Thêm feature mới vào OTA platform" → Phase 1-2 lại
- "Fix bug trong booking" → Phase 3 → 4 → 5 lại
- "Tối ưu performance" → Phase 3 (backend/frontend specific areas)
- "Update deployment strategy" → Phase 5 lại

**Description keywords:** "xây dựng harness", "phát triển feature", "sửa lỗi", "cập nhật", "tối ưu", "deploy"

---

## Workspace Cleanup

Sau deployment, `_workspace/` files có thể archive:
- `_workspace_deployed_{date}/` — lưu lại history
- `_workspace/` — xóa hoặc reset cho phase tiếp theo

---

## References

- Harness concept: `.claude/skills/harness/SKILL.md`
- Agent definitions: `.claude/agents/` directory
- Individual skills: `.claude/skills/{skill_name}/SKILL.md`

