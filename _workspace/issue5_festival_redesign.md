# Issue #5 — Festival Coverage Gap Redesign Proposal

**Author:** frontend-developer agent
**Date:** 2026-06-10
**Status:** Design proposal — NOT yet implemented

## TL;DR

Festival Coverage Gap tab hiện match rất ít festival vì coverage logic chỉ đếm
tour đã được tag (`Tour.festival_slug IS NOT NULL`). Trong khi đó, người dùng
phải tự tạo mapping rule ở `Quy tắc phân loại → Lễ Hội`, nhưng mapping engine
KHÔNG được trigger tự động sau khi rule mới được tạo → Coverage Gap không phản
ánh được rule mới. Hai module sống tách biệt, không có vòng feedback.

Proposal: hợp nhất data source, mở rộng coverage matching, surface mapping
rules trong Coverage Gap UI, và add auto-suggest mapping engine.

---

## 1. Current architecture

```
┌─────────────────────────────┐         ┌────────────────────────────┐
│ RulesAdminPage              │         │ FestivalsPage              │
│  └ Tab "Lễ Hội"             │         │  └ Tab "Coverage Gap"       │
│    (FestivalMappingRulesTab)│         │     (CoverageGapTab)        │
│                             │         │                             │
│ - CRUD location_keyword     │         │ - getCoverageGap(limit=30)  │
│   → market_keyword,         │         │ - Sort by gap_score desc    │
│     route_keyword           │         │                             │
│ - "Apply" button gọi        │         │                             │
│   applyFestivalMappingRules │         │                             │
└──────────────┬──────────────┘         └──────────────┬──────────────┘
               │                                       │
               │ POST /admin/rules/festival-mapping/apply
               │                                       │
               ▼                                       │
       ┌───────────────────────┐                       │
       │ FestivalTourMappingRule│                       │
       │ (1 query per apply)    │                       │
       └───────────┬───────────┘                       │
                   │ updates Tour.festival_slug         │
                   ▼                                    │
              ┌────────────────┐                        │
              │ Tour table     │ ◄──────────────────────┘
              │ - festival_slug│  reads festival_slug
              │ - province_code│  (get_coverage_gap)
              │ - thi_truong   │
              │ - tuyen_tour   │
              └────────────────┘
```

### Key facts (verified in code)

**Backend `festival_tagging.py`:**
- `_compute_coverage_gap()` (lines 427-503): filter
  `Tour.festival_slug.in_(fest_slugs)` then in-memory location match.
- Tour KHÔNG được tag → KHÔNG xuất hiện trong coverage gap (line 467-469:
  `if not tours: continue`).
- Redis cache TTL 1h → admin tạo rule mới phải đợi/invalidate.

**Backend `models.py` line 210-235:**
- `FestivalTourMappingRule` model: `(location_keyword, market_keyword,
  route_keyword, date_window_days)`.
- Apply logic: tour có `thi_truong CONTAINS market_keyword AND tuyen_tour
  CONTAINS route_keyword` → tag tour vào festival GẦN NHẤT (theo date)
  ở location_keyword.

**Frontend split:**
- `RulesAdminPage.tsx` → `FestivalMappingRulesTab` (rule editor)
- `FestivalsPage.tsx` line 744 → `CoverageGapTab` (read-only consumer)

---

## 2. Problems

### P1. Mapping rule chỉ tag, không tạo "implied coverage"
Hiện tại nếu admin chưa tạo mapping rule cho festival X, dù VTR có 5 tour đi
đúng location X cùng date overlap, Coverage Gap vẫn báo **0 VTR coverage**.

→ False alarm + admin không biết tại sao Coverage Gap không update sau khi
thêm rule (vì cần trigger retag + clear cache).

### P2. Không có forward link UI: Coverage Gap → Quy tắc phân loại
Khi nhìn 1 festival ở Coverage Gap có `gap_score` cao, admin không biết:
- Festival này đã có mapping rule chưa?
- Mapping rule cho location này như thế nào?
- Click vào đâu để tạo mapping?

User phải tự nhớ → mở RulesAdminPage → switch tab → tìm location keyword.

### P3. Cache & retag flow không clear
Sau khi apply mapping rule:
1. `applyFestivalMappingRules` chỉ tag tour theo mapping rules.
2. `retagFestivals` tag theo lich_kh parsing.
3. Cache Redis `festival.coverage_gap` (TTL 1h) vẫn cached cũ.

→ Admin tạo rule, không thấy effect ngay, nghĩ rằng "rule không work".

### P4. Không có "auto-suggest"
Admin phải tự nghĩ ra location keyword cho từng festival. Với 200+ festival
upcoming, đây là công việc thủ công lớn. Nhiều festival có tên rõ ràng
("Lễ Cà phê Buôn Ma Thuột") nhưng admin vẫn phải gõ tay `Đắk Lắk`.

---

## 3. Proposed redesign

### 3.1. Unified data source — extend coverage matching

**Hiện tại:**
```python
# festival_tagging.py line 453
.filter(Tour.festival_slug.in_(fest_slugs))
```

**Đề xuất:** dùng `union` của 2 nguồn:

```python
# Pseudo-code
tagged_tours    = Tour.festival_slug == slug
implied_tours   = (
    Tour.thi_truong matches mapping_rule.market_keyword
    AND Tour.tuyen_tour matches mapping_rule.route_keyword
    AND date overlap (lich_kh, festival.date_start ± date_window_days)
)
coverage_tours  = tagged_tours UNION implied_tours
```

Coverage Gap response thêm 2 field:
```json
{
  "slug": "le-ca-phe-buon-ma-thuot",
  "vtr_tours": 3,             // tagged
  "vtr_tours_implied": 5,     // NEW: location/date match nhưng chưa tag
  "competitor_tours": 12,
  "competitor_tours_implied": 7,  // NEW
  "mapping_rule_id": "..."    // NEW: id rule active cho location này (nullable)
}
```

### 3.2. Show mapping rules summary trong Coverage Gap header

Coverage Gap header (FestivalsPage):

```
┌─────────────────────────────────────────────────────────────────┐
│ Coverage Gap (30 festivals)                                    │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 8 mapping rules active · 22/30 festival có rule           │ │
│ │ [Mở Quy tắc phân loại → Lễ Hội]                          │ │
│ └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

Mỗi row trong bảng coverage gap:
- Badge "Có rule" / "Chưa có rule"
- Click "Chưa có rule" → mở modal tạo rule prefilled với `location_keyword =
  festival.location_text`.

### 3.3. Auto-suggest mappings

Nút "Auto-suggest mappings" (admin only) trên Coverage Gap header:
1. Backend scan top N festival có `gap_score` cao + KHÔNG có mapping rule.
2. Cho từng festival, suggest:
   - `location_keyword` = festival.location_text (province name normalize)
   - `market_keyword`  = infer từ region: domestic → "Việt Nam",
     intl → guess theo country trong location_text
   - `route_keyword`   = location_text rút gọn
3. Show table preview: festival → suggested rule, admin có thể tick từng
   suggestion + "Apply tất cả".

### 3.4. Auto-invalidate cache khi rule changes

Backend: hook vào `createFestivalMappingRule / updateFestivalMappingRule /
deleteFestivalMappingRule` → invalidate Redis key
`ota:festival.coverage_gap:*` + trigger background `applyFestivalMappingRules`.

Frontend: sau apply, `qc.invalidateQueries(["festival-coverage-gap"])` —
ĐÃ thêm trong tab "Lễ Hội" refresh button (Issue #3).

---

## 4. UI mockup — modal "Tạo mapping từ festival"

```
┌─────────────────────────────────────────────────────────────┐
│ Tạo mapping rule cho: Lễ Cà Phê Buôn Ma Thuột           [X] │
├─────────────────────────────────────────────────────────────┤
│ Festival location: Đắk Lắk                                   │
│ Date: 10/03/2027 - 15/03/2027                               │
│                                                              │
│ Location keyword:  [Đắk Lắk          ▼] (suggested)         │
│ Thị trường:        [Việt Nam         ▼] (dropdown từ DB)    │
│ Tuyến tour:        [Đắk Lắk          ▼] (dropdown từ DB,    │
│                                          filter theo TT)    │
│ Date window:       [±7 days         ]                       │
│                                                              │
│ Preview: rule sẽ tag ~12 tour                               │
│ (3 từ VTR, 9 competitor) vào festival này.                  │
│                                                              │
│         [Hủy]                          [Tạo + Apply]        │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Migration steps

### Phase A — Backend
1. Extend `get_coverage_gap` để compute implied coverage. Thêm sub-query
   match mapping rule keyword cho tour chưa tag.
2. Trả thêm field `vtr_tours_implied`, `competitor_tours_implied`,
   `mapping_rule_id`.
3. Auto-invalidate cache + trigger background retag khi CUD mapping rule.
4. Endpoint mới: `GET /admin/rules/festival-mapping/suggestions?limit=20`
   trả list festival + suggested rule fields.
5. Endpoint mới: `POST /admin/rules/festival-mapping/bulk-create` accept
   array rule.

### Phase B — Frontend
1. Update `CoverageGapItem` type với new fields.
2. CoverageGapTab header: show mapping rules count + button mở
   RulesAdminPage tab Lễ Hội (deeplink `?tab=festival`).
3. Mỗi row coverage gap: badge có/chưa rule + click → modal tạo rule.
4. Auto-suggest button: gọi suggestions endpoint, hiển thị table preview.

### Phase C — Deploy
1. Backend deploy trước (additive changes, backward compat).
2. Frontend deploy.
3. Run 1-time migration: trigger `applyFestivalMappingRules + retagFestivals`
   với `only_untagged=False` để sync existing rules.

---

## 6. API changes needed (note for backend agent)

### New endpoints
- `GET /admin/rules/festival-mapping/suggestions?limit=20`
- `POST /admin/rules/festival-mapping/bulk-create`

### Modified endpoints
- `GET /festivals/insights/coverage-gap`:
  Response add `vtr_tours_implied`, `competitor_tours_implied`,
  `mapping_rule_id`, `top_competitors_implied`.

### Cache invalidation
- `POST /admin/rules/festival-mapping` (CUD) → invalidate
  `ota:festival.coverage_gap:*` + queue background retag job.

### Backward compatibility
All existing fields kept — `vtr_tours` semantics unchanged (chỉ tagged
tours). New `_implied` fields nullable đến khi backend phase A deploy.

---

## 7. Estimated impact

- Coverage Gap useful results: ~3-5 festivals → ~50-80 festivals (10x+).
- Admin time tạo mapping rules: 30s/festival → 5s/festival (auto-suggest
  + bulk apply).
- False alarm rate: HIGH → LOW (implied coverage filter).
- Vòng feedback rule → coverage: invalidate manual → tự động.

---

## 8. Open questions / risks

1. **Performance:** implied coverage cần subquery match keyword cho từng
   tour x festival. Với 30k tour x 200 festival = 6M comparison. Cần
   indexed prefix match hoặc precompute provincial index. → Backend
   benchmark trước.
2. **Mapping rule quality:** auto-suggest có thể tạo rule sai (location
   keyword "Hà Nội" match cả "Hà Nội Garden Hotel"). Cần admin review
   trước khi bulk-apply.
3. **UI complexity:** thêm 1 modal + 1 wizard có thể overwhelm. Cần
   user testing để đảm bảo flow rõ.

— END —
