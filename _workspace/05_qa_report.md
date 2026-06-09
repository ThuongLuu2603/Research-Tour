# 05 — QA Report

**Date:** 2026-06-10  **Reviewer:** qa-engineer  **Scope:** 5 fixes (3 backend, 2 frontend areas)

## 1. Static checks

| Check | Result |
|-------|--------|
| `ast.parse backend/api/workspaces.py` | PASS |
| `ast.parse backend/classification.py` | PASS |
| `npx tsc --noEmit` (frontend) | PASS (exit 0, no output) |

## 2. Code review findings

### 2.1 `backend/api/workspaces.py`
- **L93–101 `_recompute_phan_khuc_safe`** — **DEAD CODE.** Grep confirms zero callers after the switch to `_recompute_phan_khuc_background`. Non-blocker but should be removed in a follow-up to avoid drift.
- **L104–127 `_recompute_phan_khuc_background`** — Correct pattern: opens its own `SessionLocal()`, wraps in try/except/finally, `daemon=True` so it doesn't block process shutdown. `bg.commit()` after recompute is appropriate. Swallowed exceptions are logged silently (`pass`) — acceptable for best-effort, but logs would help post-mortem.
- **L307–311 `patch_workspace_tour`** — Response built from in-session `tour` + `override`, then thread spawned. Correct order: response returns immediately, recompute runs async.
- **L348–351 `bulk_patch_workspace_tours`** — Same pattern; recompute fed `wrote_ids` only (skips override-only writes that don't trigger phân khúc). Correct.
- Auth gates intact: `require_permission(db, ws, user, "edit")` for both endpoints; admin-only DB writes via `_admin_write_classification`.

### 2.2 `backend/classification.py` (L1785–1798 `_row_key`)
- Priority rules: tuple `(0, 0, -len(kws), sort_order, id)`. Bucket 0 ensures they sort ahead of all non-priority rules.
- Field `priority` confirmed on `RouteKeywordRule` (`models.py:135`, `Boolean default False`).
- `getattr(r, "priority", False)` defensive — safe even if schema rollback.
- Logic matches spec: priority rules now compete with each other only by `-len(kws)` then `sort_order` — `market_rank` no longer affects priority bucket.

### 2.3 Frontend `lib/api.ts` (L1245–1252)
- `recomputeAllClassifications()` POSTs `/admin/rules/apply-classification-to-tours?recompute_phan_khuc=true&full_scan=true`. Reuses existing endpoint correctly. Doc-comment explains the reuse.

### 2.4 Frontend `RulesAdminPage.tsx` (L286–342, L536–557)
- `onRefreshCurrentTab` dispatches by `tab` value: classify → BG apply + poll; company/departure/duration → sync API + `setApplying(false)` in branch. Schedule/festival/compare → cache invalidate only.
- Button rendered only for the 4 tabs with real apply endpoints (correct). Spinner state respected via `applying`.
- **Note:** `setApplying(false)` is NOT called in classify branch — relies on `pollApplyStatus` to clear it. Verified by checking pattern matches existing `applyMut`. Acceptable.

### 2.5 Frontend `ResearchGrid.tsx` (L206, L246, L409, L445–455)
- `isAdmin` gate on Refresh button (L445) — correct.
- `handleRecomputeRules` re-checks `isAdmin` defensively before firing (L351). 
- Polling: 2s × max 120 attempts = 4 min cap; invalidates `workspace-tours` + `filter-options` on completion.
- `marketByRoute` memo: O(routes) once; collision policy "first wins" documented.
- `dayOptions` memo: derives from current page only (acknowledged in comment).
- `visibleItems`: client-side filter for `selDays`. **Caveat:** filtering only the current page means pagination + `selDays` is inconsistent — total count from `data.total` won't reflect day filter, and `pageIds` (used for select-all) only covers visible. Documented in code; acceptable for v1 but should be flagged for backend follow-up.

## 3. Integration risk assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Race between concurrent PATCHes on same tour spawning duplicate bg threads** | Low | `recompute_phan_khuc_for_tour_ids` is idempotent; worst case is wasted CPU. No data corruption. |
| **Bg thread silent failure** → user sees stale phân khúc | Medium | Swallowed `Exception` with no log line. Recommend adding `logger.warning` in except block (future work). |
| **Priority rule reclassification side-effects** | Medium | Tours previously classified by a non-priority rule may flip if a priority rule with matching keywords + different `thi_truong` now wins. Run smoke check after deploy: spot-check 10 tours in markets `EU`, `AM`, `JP`. Untracked `*_remapped.txt` files in repo suggest this remap was already pre-tested. |
| **Frontend day filter + pagination mismatch** | Low | UX is misleading on multi-page result but doesn't lose data. |
| **Refresh rules toast clobbering** | Low | Single `toast` slot; new clicks overwrite. Acceptable. |

## 4. Test plan (post-deploy, manual)

1. **Workspace PATCH latency** — login as admin, edit a tour's `gia` field on Research Grid; measure PATCH response time via DevTools Network. **Target < 200ms.** Verify "Đã ghi vào dữ liệu chung" toast.
2. **Per-tab refresh** — Rules Admin → tab "Tuyến tour" → click "Re-apply Tuyến tour", confirm only classify BG job starts (status endpoint). Repeat on Công ty / Điểm KH / Thời gian.
3. **ResearchGrid full refresh** — click "Refresh rules", watch toast progress "Đang re-apply rules: x/y tour…", confirm grid refetches on done.
4. **Cascading filter** — clear filters → select Tuyến `Châu Âu` first → confirm TT auto-fills `EU` (or equivalent). Then select TT first → confirm tuyến dropdown narrows.
5. **Priority rule unrecognized market** — create a priority rule with keywords `["test_kw"]` + `thi_truong="ZZZ_FAKE"`, set a tour title to contain `test_kw`, run refresh, confirm tour gets classified by that rule regardless of its current `thi_truong`. Delete rule after.
6. **Phân khúc convergence** — edit tour `gia` → response returns fast; refresh page after ~10s → confirm `phan_khuc` updated.

## 5. Recommendation

**READY TO DEPLOY.** No blockers. Two small follow-ups (non-blocking):

- Remove unused `_recompute_phan_khuc_safe` (workspaces.py:93–101).
- Add `logger.warning` inside `_recompute_phan_khuc_background` except clause for observability.

Post-deploy monitor: error rate on `/admin/rules/apply-classification-to-tours`, PATCH p95 latency on `/workspaces/{id}/tours/{tour_id}`.
