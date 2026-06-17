import { Navigate } from "react-router-dom";
import { useCallback, useMemo, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listRouteRules, deleteRouteRule, updateRouteRule, setRouteRulePriority,
  listCompanyRules, createCompanyRule, deleteCompanyRule, updateCompanyRule,
  listDepartureRules, createDepartureRule, deleteDepartureRule, updateDepartureRule,
  listDurationRules, createDurationRule, deleteDurationRule, updateDurationRule,
  // Schedule alias rules (bảng schedule_alias_rules) — giữ model + API backward
  // compat, nhưng tab UI cũ đã thay bằng DateFormatRulesTab. Các hàm này chỉ còn
  // dùng trong AliasTable type union để tránh phải refactor component shared.
  seedCompanyDefaults, seedDepartureDefaults, seedDurationDefaults,
  listDateFormatRules, createDateFormatRule, updateDateFormatRule,
  deleteDateFormatRule, seedDateFormatDefaults, testDateFormat,
  applyClassificationToTours,
  applyCompanyRulesToTours,
  applyDepartureRulesToTours,
  applyDurationRulesToTours,
  getApplyClassificationStatus,
  getRulesUnmatched,
  getRulesUnmatchedSummary,
  getRuleRouteStats,
  getDataQuality,
  RouteRule, CompanyRule, DepartureRule, DurationRule, UnmatchedItem,
  DateFormatRule, DateFormatOutputType, DateFormatTestResult,
  // Festival mapping rules (tab Lễ hội)
  listFestivalMappingRules, createFestivalMappingRule, updateFestivalMappingRule,
  deleteFestivalMappingRule, applyFestivalMappingRules,
  retagFestivals,
  listFestivals, getFilterOptions,
  FestivalMappingRule, Festival,
  // Compare segment rule (tab So sánh VTR ↔ Thị trường)
  getCompareSegmentRule, updateCompareSegmentRule, CompareSegmentRule,
} from "@/lib/api";
import { COL } from "@/lib/glossary";
import { InfoTip } from "@/components/InfoTip";
import { cn } from "@/lib/utils";
import { formatDurationLabel, parseDurationInput } from "@/lib/durationFormat";
import { buildRouteKeywordConflicts, mergeRouteKeywordLists, parseRouteKeywordList } from "@/lib/rulesUnmatched";
import { dropHandlers, dragAliasProps, keepInputKeys, keywordForRouteDrop, matchRulesSearch } from "@/lib/rulesAdminUi";
import { ClassificationRulesTab } from "@/components/ClassificationRulesTab";
import { UnmatchedMembers } from "@/components/UnmatchedMembers";
import { Plus, Trash2, RefreshCw, Database, Search, Pencil, Check, X, GripVertical } from "lucide-react";

type Tab = "classify" | "company" | "departure" | "duration" | "schedule" | "festival" | "compare";
const matchSearch = matchRulesSearch;

function RuleSearchBar({ value, onChange, total, filtered }: { value: string; onChange: (v: string) => void; total: number; filtered: number }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="relative flex-1 min-w-[220px] max-w-md">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          className="input pl-9 text-sm w-full"
          placeholder="Tìm thị trường, tuyến, keyword, tên tour..."
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={keepInputKeys}
        />
      </div>
      <span className="text-xs text-gray-500">{filtered}/{total} dòng</span>
    </div>
  );
}

export default function RulesAdminPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [tab, setTab] = useState<Tab>(() => {
    // Issue #5: cho phép deep-link từ Festival CoverageGapTab (/rules#festival).
    const hash = typeof window !== "undefined" ? window.location.hash.replace("#", "") : "";
    const validTabs: Tab[] = ["classify", "company", "departure", "duration", "schedule", "festival", "compare"];
    return (validTabs as string[]).includes(hash) ? (hash as Tab) : "classify";
  });
  const [search, setSearch] = useState("");
  const [syncMsg, setSyncMsg] = useState("");
  const [applying, setApplying] = useState(false);
  const [fullScanApply, setFullScanApply] = useState(false);
  // id rule giờ là string (CockroachDB unique_rowid() > 2^53)
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<Record<string, string>>({});

  const [cCanonical, setCCanonical] = useState("");
  const [cAlias, setCAlias] = useState("");
  const [dCanonical, setDCanonical] = useState("");
  const [dAlias, setDAlias] = useState("");
  const [durDays, setDurDays] = useState("");
  const [durAlias, setDurAlias] = useState("");
  // Tab "Định dạng Ngày KH" (schedule): DateFormatRulesTab tự quản lý state riêng,
  // không dùng các state s* phía trên nữa.
  const [dropTarget, setDropTarget] = useState<string | null>(null);

  const { data: routeRules } = useQuery({ queryKey: ["route-rules"], queryFn: listRouteRules, enabled: isAdmin });
  const { data: companyRules } = useQuery({ queryKey: ["company-rules"], queryFn: listCompanyRules, enabled: isAdmin });
  const { data: departureRules } = useQuery({ queryKey: ["departure-rules"], queryFn: listDepartureRules, enabled: isAdmin });
  const { data: durationRules } = useQuery({ queryKey: ["duration-rules"], queryFn: listDurationRules, enabled: isAdmin });
  const { data: unmatchedSummary } = useQuery({ queryKey: ["rules-unmatched-summary"], queryFn: getRulesUnmatchedSummary, enabled: isAdmin, staleTime: 120_000 });
  const { data: routeStats } = useQuery({ queryKey: ["rules-route-stats"], queryFn: getRuleRouteStats, enabled: isAdmin && tab === "classify", staleTime: 120_000 });
  const { data: quality } = useQuery({ queryKey: ["data-quality"], queryFn: getDataQuality, enabled: isAdmin, staleTime: 120_000 });
  // Tab "schedule" = Định dạng Ngày KH (DSL pattern). Vẫn fetch unmatched scope=schedule
  // để hiện text chưa khớp rule nào → admin biết cần viết thêm rule.
  // (Backend đã sửa: gate bằng match_text DSL thay parse_departure_dates hardcoded.)
  const unmatchedScope = (
    tab === "classify" || tab === "company" || tab === "departure"
    || tab === "duration" || tab === "schedule"
  ) ? tab : null;
  const [hiddenGapValues, setHiddenGapValues] = useState<Set<string>>(() => new Set());
  const { data: unmatched, isLoading: unmatchedLoading } = useQuery({
    queryKey: ["rules-unmatched", unmatchedScope],
    queryFn: () => getRulesUnmatched(unmatchedScope!, false),
    enabled: isAdmin && !!unmatchedScope,
    staleTime: 120_000,
  });

  const refreshUnmatchedList = useCallback(async () => {
    if (!unmatchedScope) return;
    const data = await getRulesUnmatched(unmatchedScope, true);
    qc.setQueryData(["rules-unmatched", unmatchedScope], data);
    setHiddenGapValues((prev) => {
      if (!prev.size) return prev;
      const remaining = new Set(data.items.map((i) => i.value));
      const next = new Set<string>();
      for (const v of prev) {
        if (remaining.has(v)) next.add(v);
      }
      return next;
    });
  }, [unmatchedScope, qc]);

  const markGapsHandled = useCallback((values: string[]) => {
    if (!values.length) return;
    setHiddenGapValues((prev) => new Set([...prev, ...values]));
    void refreshUnmatchedList();
  }, [refreshUnmatchedList]);

  const unmarkGapsHandled = useCallback((values: string[]) => {
    if (!values.length) return;
    setHiddenGapValues((prev) => {
      const next = new Set(prev);
      for (const v of values) next.delete(v);
      return next;
    });
  }, []);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["market-rules"] });
    qc.invalidateQueries({ queryKey: ["route-rules"] });
    qc.invalidateQueries({ queryKey: ["company-rules"] });
    qc.invalidateQueries({ queryKey: ["departure-rules"] });
    qc.invalidateQueries({ queryKey: ["duration-rules"] });
    qc.invalidateQueries({ queryKey: ["date-format-rules"] });
    qc.invalidateQueries({ queryKey: ["rules-unmatched"] });
    qc.invalidateQueries({ queryKey: ["rules-unmatched-summary"] });
    qc.invalidateQueries({ queryKey: ["rules-route-stats"] });
    qc.invalidateQueries({ queryKey: ["data-quality"] });
    qc.invalidateQueries({ queryKey: ["compare-class-gaps"] });
    qc.invalidateQueries({ queryKey: ["workspace-tours"] });
    qc.invalidateQueries({ queryKey: ["filter-options"] });
  };

  /**
   * Optimistic remove 1 dòng khỏi panel "Chưa khớp" (react-query cache) ngay
   * khi user bấm Gán — không chờ backend recompute. Trả về hàm rollback
   * (re-insert đúng vị trí cũ) để gọi khi mutation lỗi.
   */
  const removeUnmatchedFromCache = (value: string) => {
    if (!unmatchedScope) return () => {};
    const key = ["rules-unmatched", unmatchedScope];
    let removed: UnmatchedItem | undefined;
    let removedIdx = 0;
    qc.setQueryData<{ scope: string; items: UnmatchedItem[] }>(key, (old) => {
      if (!old) return old;
      const idx = old.items.findIndex((i) => i.value === value);
      if (idx < 0) return old;
      removed = old.items[idx];
      removedIdx = idx;
      return { ...old, items: old.items.filter((_, i) => i !== idx) };
    });
    return () => {
      if (!removed) return;
      qc.setQueryData<{ scope: string; items: UnmatchedItem[] }>(key, (old) => {
        if (!old || old.items.some((i) => i.value === value)) return old;
        const items = [...old.items];
        items.splice(Math.min(removedIdx, items.length), 0, removed!);
        return { ...old, items };
      });
    };
  };

  const errDetail = (e: unknown) =>
    String((e as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail || (e as Error)?.message || e);

  /**
   * Gán alias từ panel "Chưa khớp" — pattern chung cho company/departure/duration:
   * 1. Optimistic: xóa dòng khỏi cache unmatched ngay + ẩn (hiddenGapValues) để
   *    refetch nền (backend recompute chậm) không trả dòng về panel.
   * 2. Lỗi → rollback (trả dòng về) + toast lỗi rõ ràng.
   * 3. Thành công → toast kèm số tour đã cập nhật (backend mới trả {applied: N};
   *    backend cũ không có field này → toast thường).
   * 4. Invalidate queries liên quan chạy nền, không block UI.
   * Trả về true/false để caller (per-row button) biết có nên clear input không.
   */
  const assignAliasFromUnmatched = async (
    alias: string,
    create: () => Promise<{ applied?: number } | undefined>,
    okLabel: string,
  ): Promise<boolean> => {
    const restore = removeUnmatchedFromCache(alias);
    setHiddenGapValues((prev) => new Set([...prev, alias]));
    try {
      const res = await create();
      const applied = typeof res?.applied === "number" ? res.applied : null;
      setSyncMsg(applied != null ? `${okLabel} + cập nhật ${applied} tour` : okLabel);
      invalidate();
      void refreshUnmatchedList();
      return true;
    } catch (e) {
      restore();
      unmarkGapsHandled([alias]);
      setSyncMsg(`Gán alias "${alias}" thất bại: ${errDetail(e)}`);
      return false;
    }
  };

  const assignCompanyAlias = (canonical: string, alias: string) =>
    assignAliasFromUnmatched(
      alias,
      () => createCompanyRule({ canonical_name: canonical, alias }),
      `Đã gán alias "${alias}" → ${canonical}`,
    );
  const assignDepartureAlias = (canonical: string, alias: string) =>
    assignAliasFromUnmatched(
      alias,
      () => createDepartureRule({ canonical_name: canonical, alias }),
      `Đã gán alias "${alias}" → ${canonical}`,
    );
  const assignDurationAlias = (days: number, alias: string) =>
    assignAliasFromUnmatched(
      alias,
      () => createDurationRule({ canonical_days: days, alias }),
      `Đã gán "${alias}" → ${days}N`,
    );
  const appendKeywordToRouteRule = async (rule: RouteRule, raw: string) => {
    const add = parseRouteKeywordList(keywordForRouteDrop(raw) || raw);
    if (!add.length) {
      setSyncMsg("Nhập keyword ngắn (vd: mexico) hoặc nhiều từ cách nhau dấu phẩy (canada, cuba, mexico).");
      return;
    }
    const merged = mergeRouteKeywordLists(rule.keywords, add.join(", "));
    await updateRouteRule(rule.id, {
      thi_truong: rule.thi_truong,
      tuyen_tour: rule.tuyen_tour,
      keywords: merged,
    });
    afterRuleSaved(`Đã thêm vào rule — tour phải chứa đủ: ${merged}`);
  };

  const toggleRoutePriority = async (rule: RouteRule) => {
    // Optimistic update: flip priority trong cache ngay → ngôi sao đổi màu instant.
    // Trước đây user phải chờ API (~1s) + refetch (~1-2s) mới thấy UI cập nhật,
    // dễ tưởng click không ăn → click lại nhiều lần.
    const newPriority = !rule.priority;
    qc.setQueryData<RouteRule[]>(["route-rules"], (old) =>
      old?.map((r) => (r.id === rule.id ? { ...r, priority: newPriority } : r)) ?? old,
    );
    try {
      await setRouteRulePriority(rule.id, newPriority);
    } catch (e) {
      // Rollback optimistic update — refetch để đồng bộ với server.
      qc.invalidateQueries({ queryKey: ["route-rules"] });
      // id cũ (danh sách rule đã thay đổi) → làm mới rồi báo người dùng thử lại.
      if ((e as { response?: { status?: number } })?.response?.status === 404) {
        throw new Error("Danh sách rule vừa thay đổi — đã làm mới, vui lòng bấm lại.");
      }
      throw e;
    }
    // Background refetch để pick up sort_order mới (priority ảnh hưởng thứ tự).
    qc.invalidateQueries({ queryKey: ["route-rules"] });
  };

  const editRouteKeywords = async (rule: RouteRule, newKeywords: string) => {
    await updateRouteRule(rule.id, {
      thi_truong: rule.thi_truong,
      tuyen_tour: rule.tuyen_tour,
      keywords: newKeywords,
    });
    qc.invalidateQueries({ queryKey: ["route-rules"] });
  };

  const showErr = (e: unknown) => setSyncMsg(errDetail(e));

  const finishApplyPoll = (st: { running?: boolean; error?: string; message?: string; stale?: boolean; last_result?: unknown }) => {
    setApplying(false);
    if (st.stale) {
      setSyncMsg(st.message || "Job trước có thể đã treo — thử bấm lại.");
      return;
    }
    if (st.error) {
      setSyncMsg(st.error);
      return;
    }
    const msg =
      st.message
      || (st.last_result && typeof (st.last_result as { message?: string }).message === "string"
        ? (st.last_result as { message: string }).message
        : "");
    if (msg) setSyncMsg(msg);
    invalidate();
    void refreshUnmatchedList();
  };

  const pollApplyStatus = (attempt = 0) => {
    getApplyClassificationStatus()
      .then((st) => {
        if (st.running && attempt < 120) {
          const prog = st.progress != null && st.total
            ? `Đang quét ${st.progress}/${st.total} tour…`
            : st.message || "Đang áp dụng quy tắc…";
          setSyncMsg(prog);
          window.setTimeout(() => pollApplyStatus(attempt + 1), 2000);
          return;
        }
        finishApplyPoll(st);
      })
      .catch(() => setApplying(false));
  };

  const pollAfterRuleSave = (attempt = 0) => {
    getApplyClassificationStatus()
      .then((st) => {
        if (st.running && attempt < 60) {
          setSyncMsg(st.message || "Đang áp dụng quy tắc lên tour…");
          window.setTimeout(() => pollAfterRuleSave(attempt + 1), 2000);
          return;
        }
        invalidate();
        if (st.message && !st.running) setSyncMsg(st.message);
        void refreshUnmatchedList();
      })
      .catch(() => {
        invalidate();
        void refreshUnmatchedList();
      });
  };

  const onApplyTours = () => {
    setApplying(true);
    setSyncMsg(fullScanApply ? "Đang quét toàn bộ tour…" : "Đang quét tour mới / cần cập nhật…");
    applyClassificationToTours({ fullScan: fullScanApply })
      .then((r) => {
        setSyncMsg(r.message || "Đang áp dụng quy tắc (chạy nền)…");
        pollApplyStatus();
      })
      .catch((e) => { showErr(e); setApplying(false); });
  };

  /**
   * Per-tab refresh — chỉ re-apply rules của tab hiện tại.
   * - classify (Tuyến tour): re-apply market + route → BG job, có polling
   * - company / departure / duration: chạy đồng bộ, trả ngay
   * - schedule / festival / compare: invalidate cache, không có endpoint apply riêng
   */
  const onRefreshCurrentTab = async () => {
    setApplying(true);
    try {
      if (tab === "classify") {
        setSyncMsg(fullScanApply
          ? "Đang quét lại toàn bộ tour (TT + Tuyến tour)…"
          : "Đang quét tour cần cập nhật (TT + Tuyến tour)…");
        const r = await applyClassificationToTours({ fullScan: fullScanApply });
        setSyncMsg(r.message || "Đang áp dụng quy tắc tuyến (chạy nền)…");
        pollApplyStatus();
      } else if (tab === "company") {
        setSyncMsg("Đang re-apply alias công ty…");
        const r = await applyCompanyRulesToTours();
        setSyncMsg(r.message || `Đã cập nhật ${r.updated ?? "?"} tour (công ty)`);
        invalidate();
        void refreshUnmatchedList();
        setApplying(false);
      } else if (tab === "departure") {
        setSyncMsg("Đang re-apply alias điểm KH…");
        const r = await applyDepartureRulesToTours();
        setSyncMsg(r.message || `Đã cập nhật ${r.updated ?? "?"} tour (điểm KH)`);
        invalidate();
        void refreshUnmatchedList();
        setApplying(false);
      } else if (tab === "duration") {
        setSyncMsg("Đang re-apply alias thời gian…");
        const r = await applyDurationRulesToTours();
        setSyncMsg(r.message || `Đã cập nhật ${r.updated ?? "?"} tour (thời gian)`);
        invalidate();
        void refreshUnmatchedList();
        setApplying(false);
      } else if (tab === "schedule") {
        // Định dạng Ngày KH (DSL pattern): không có apply-to-tours (lich_kh giữ
        // text gốc; alias chỉ ảnh hưởng collect_unmatched). Chỉ invalidate cache
        // + refetch unmatched list để admin thấy ngay rule mới khớp được text nào.
        setSyncMsg("Đang invalidate cache + tính lại text chưa khớp…");
        invalidate();
        await refreshUnmatchedList();
        setSyncMsg("Đã refresh cache & danh sách text chưa khớp (Định dạng Ngày KH).");
        setApplying(false);
      } else if (tab === "festival") {
        // Lễ hội: re-apply mapping rules (location → market+route) → trigger
        // festival_tagging.tag_tours_with_festivals để gán Tour.festival_slug.
        setSyncMsg("Đang re-apply mapping Lễ hội + retag toàn bộ tour…");
        const applyRes = await applyFestivalMappingRules();
        const tagRes = await retagFestivals(false);
        setSyncMsg(
          `Đã apply ${applyRes.rules_applied} rules (${applyRes.tours_tagged} tour qua mapping) `
          + `+ retag toàn bộ (${tagRes.tours_tagged} tour, ${tagRes.tours_scanned} quét).`,
        );
        invalidate();
        qc.invalidateQueries({ queryKey: ["festivals"] });
        qc.invalidateQueries({ queryKey: ["festival-coverage-gap"] });
        setApplying(false);
      } else if (tab === "compare") {
        // So sánh VTR ↔ Thị trường: rule là single-row config (vtr_tiers +
        // market_phan_khuc). Không có "apply to tours" — chỉ invalidate compare
        // cache để trang So sánh dùng rule mới ngay.
        setSyncMsg("Đang invalidate cache So sánh…");
        qc.invalidateQueries({ queryKey: ["compare"] });
        qc.invalidateQueries({ queryKey: ["compare-class-gaps"] });
        qc.invalidateQueries({ queryKey: ["compare-segment-rule"] });
        setSyncMsg("Đã refresh cache So sánh — mở trang So sánh để xem kết quả mới.");
        setApplying(false);
      } else {
        setSyncMsg("Tab này không có rule áp dụng trực tiếp lên tour (chỉ invalidate cache).");
        invalidate();
        setApplying(false);
      }
    } catch (e) {
      showErr(e);
      setApplying(false);
    }
  };

  const refreshTabLabel = useMemo(() => {
    if (tab === "classify") return "Re-apply Tuyến tour";
    if (tab === "company") return "Re-apply Công ty";
    if (tab === "departure") return "Re-apply Điểm KH";
    if (tab === "duration") return "Re-apply Thời gian";
    if (tab === "schedule") return "Refresh Định dạng KH";
    if (tab === "festival") return "Re-tag Lễ Hội";
    if (tab === "compare") return "Refresh cache So sánh";
    return "Refresh cache";
  }, [tab]);

  const refreshTabTitle = useMemo(() => {
    if (tab === "classify") return "Re-apply chỉ rules tuyến tour cho tab này (không động đến công ty / điểm KH / thời gian)";
    if (tab === "company") return "Re-apply chỉ alias công ty (không động đến tuyến tour / điểm KH / thời gian)";
    if (tab === "departure") return "Re-apply chỉ alias điểm khởi hành (không động đến tuyến tour / công ty / thời gian)";
    if (tab === "duration") return "Re-apply chỉ alias thời gian (không động đến tuyến tour / công ty / điểm KH)";
    if (tab === "schedule") return "Invalidate cache + refetch danh sách text chưa khớp Định dạng Ngày KH (Tour.lich_kh giữ nguyên text gốc — rule chỉ ảnh hưởng parse/match)";
    if (tab === "festival") return "Re-apply mapping rules Lễ Hội (location → market+route) + retag toàn bộ tour với festival hiện có";
    return "Invalidate cache trang So sánh VTR ↔ Thị trường (để compare engine dùng rule mới ngay)";
  }, [tab]);

  const afterRuleSaved = (label: string, opts?: { gapValues?: string[]; skipPoll?: boolean }) => {
    if (opts?.gapValues?.length) markGapsHandled(opts.gapValues);
    invalidate();
    setSyncMsg(label);
    void refreshUnmatchedList();
    if (!opts?.skipPoll) pollAfterRuleSave();
  };

  const startEdit = (id: string, draft: Record<string, string>) => {
    setEditingId(id);
    setEditDraft(draft);
  };
  const cancelEdit = () => { setEditingId(null); setEditDraft({}); };

  const filteredCompany = useMemo(
    () => (companyRules ?? []).filter((r) => matchSearch(search, r.canonical_name, r.alias)),
    [companyRules, search],
  );
  const filteredDeparture = useMemo(
    () => (departureRules ?? []).filter((r) => matchSearch(search, r.canonical_name, r.alias)),
    [departureRules, search],
  );
  const filteredDuration = useMemo(
    () => (durationRules ?? []).filter((r) =>
      matchSearch(search, r.canonical_days, r.alias, formatDurationLabel(r.canonical_days)),
    ),
    [durationRules, search],
  );
  const routeKeywordConflicts = useMemo(
    () => buildRouteKeywordConflicts(routeRules ?? []),
    [routeRules],
  );

  const filteredUnmatched = useMemo(() => {
    const base = (unmatched?.items ?? []).filter((x) => matchSearch(
      search,
      x.value,
      x.count,
      x.thi_truong,
      x.keyword,
      x.suggested_market,
      x.suggested_thi_truong,
      x.suggested_route,
      x.market_keyword,
      x.route_keywords,
      x.sample,
      x.needs_market ? "thiếu tt" : "",
      x.needs_route ? "thiếu tuyến" : "",
      ...(x.members ?? []).flatMap((m) => [m.title, m.count]),
    ));
    return base.filter((x) => !hiddenGapValues.has(x.value));
  }, [unmatched, search, hiddenGapValues]);

  const classifySearchCounts = useMemo(() => {
    const routes = (routeRules ?? []).filter((r) =>
      matchSearch(search, r.thi_truong, r.tuyen_tour, r.keywords),
    );
    return {
      filtered: routes.length + filteredUnmatched.length,
      total: (routeRules?.length ?? 0) + (unmatched?.items?.length ?? 0),
    };
  }, [routeRules, unmatched, search, filteredUnmatched.length]);

  const canonicalOptions = useMemo(() => {
    if (tab === "company") return [...new Set((companyRules ?? []).map((r) => r.canonical_name))];
    if (tab === "departure") return [...new Set((departureRules ?? []).map((r) => r.canonical_name))];
    return [];
  }, [tab, companyRules, departureRules]);
  const marketOptions = useMemo(
    () => [...new Set((routeRules ?? []).map((r) => r.thi_truong))].sort(),
    [routeRules],
  );
  const addCompany = useMutation({
    mutationFn: () => createCompanyRule({ canonical_name: cCanonical, alias: cAlias }),
    onSuccess: () => { setCAlias(""); afterRuleSaved("Đã thêm alias công ty"); },
  });
  const addDeparture = useMutation({
    mutationFn: () => createDepartureRule({ canonical_name: dCanonical, alias: dAlias }),
    onSuccess: () => { setDAlias(""); afterRuleSaved("Đã thêm alias điểm khởi hành"); },
  });
  const parsedDurDays = parseDurationInput(durDays);
  const addDuration = useMutation({
    mutationFn: () => createDurationRule({ canonical_days: parsedDurDays!, alias: durAlias }),
    onSuccess: () => { setDurDays(""); setDurAlias(""); afterRuleSaved("Đã thêm alias thời gian"); },
  });
  if (!isAdmin) return <Navigate to="/" replace />;

  const actionBtns = (onDelete: () => void, onSave?: () => void) => (
    <td className="px-3 py-2 whitespace-nowrap">
      {editingId !== null && onSave ? (
        <span className="flex gap-1">
          <button type="button" className="text-green-600 p-1" onClick={onSave} title="Lưu"><Check size={14} /></button>
          <button type="button" className="text-gray-400 p-1" onClick={cancelEdit} title="Huỷ"><X size={14} /></button>
        </span>
      ) : (
        <span className="flex gap-1">
          <button type="button" className="text-red-500 p-1" onClick={onDelete} title="Xóa"><Trash2 size={14} /></button>
        </span>
      )}
    </td>
  );

  return (
    <div className="p-6 space-y-6 pb-24">
      <div>
        <h1 className="text-xl font-bold">Quy tắc phân loại & Key matching</h1>
        <p className="text-sm text-gray-500">
          Quy tắc lưu trong Supabase và áp dụng <strong>toàn hệ thống</strong>: Research Grid, So sánh VTR, Market Lab, báo cáo…
          Sau khi sửa, bấm «Áp dụng» để cập nhật tour.
        </p>
      </div>

      {/* ─── Status bar ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="card p-3">
          <p className="text-xs text-gray-500">Phân loại OK</p>
          <p className={cn("text-xl font-bold", (quality?.classified_pct ?? 100) >= 90 ? "text-green-700" : "text-amber-700")}>
            {quality?.classified_pct ?? "—"}%
          </p>
          <div className="w-full bg-gray-100 rounded-full h-1 mt-1">
            <div className="h-1 rounded-full bg-green-500 transition-all" style={{ width: `${quality?.classified_pct ?? 0}%` }} />
          </div>
        </div>
        <div className="card p-3">
          <p className="text-xs text-gray-500">Chưa phân loại</p>
          <p className={cn("text-xl font-bold", (quality?.unclassified_count ?? 0) > 50 ? "text-red-700" : "text-gray-800")}>
            {quality?.unclassified_count ?? "—"}
          </p>
          <p className="text-[10px] text-gray-400 mt-0.5">tour chưa có tuyến</p>
        </div>
        <div className="card p-3">
          <p className="text-xs text-gray-500">Rule tuyến</p>
          <p className="text-xl font-bold text-primary-700">{routeRules?.length ?? "—"}</p>
          <p className="text-[10px] text-gray-400 mt-0.5">
            {companyRules?.length ?? 0} alias CT · {departureRules?.length ?? 0} alias ĐKH
          </p>
        </div>
        <div className="card p-3">
          <p className="text-xs text-gray-500">Chưa khớp (tổng)</p>
          <p className={cn("text-xl font-bold", Object.values(unmatchedSummary ?? {}).some(v => v > 0) ? "text-amber-700" : "text-gray-800")}>
            {unmatchedSummary ? Object.values(unmatchedSummary).reduce((a, b) => a + b, 0) : "—"}
          </p>
          <p className="text-[10px] text-gray-400 mt-0.5">tuyến + công ty + KH + thời gian</p>
        </div>
      </div>

      {/* ─── Tabs + Search cùng 1 hàng ────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1 flex-wrap">
          {([
            ["classify", "Tuyến tour", unmatchedSummary?.classify],
            ["company", COL.congTy, unmatchedSummary?.company],
            ["departure", COL.diemKhoiHanh, unmatchedSummary?.departure],
            ["duration", COL.thoiGian, unmatchedSummary?.duration],
            ["schedule", "Định dạng Ngày KH", unmatchedSummary?.schedule],
            ["festival", "Lễ hội", undefined as number | undefined],
            ["compare", "So sánh VTR ↔ Thị trường", undefined as number | undefined],
          ] as const).map(([t, label, badgeCount]) => (
            <button key={t} onClick={() => { setTab(t); setSearch(""); cancelEdit(); }}
              className={cn("px-3 py-1.5 rounded-lg text-sm font-medium flex items-center gap-1.5", tab === t ? "bg-primary-600 text-white" : "bg-gray-100 hover:bg-gray-200")}>
              {label}
              {(badgeCount ?? 0) > 0 && (
                <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded-full",
                  tab === t ? "bg-white/30 text-white" : "bg-amber-100 text-amber-800")}>
                  {badgeCount}
                </span>
              )}
            </button>
          ))}
        </div>
        <div className="flex-1 min-w-[200px] max-w-md">
          <RuleSearchBar
            value={search}
            onChange={setSearch}
            total={
              tab === "classify" ? classifySearchCounts.total
                : tab === "company" ? (companyRules?.length ?? 0) + (unmatched?.items?.length ?? 0)
                : tab === "departure" ? (departureRules?.length ?? 0) + (unmatched?.items?.length ?? 0)
                : tab === "duration" ? (durationRules?.length ?? 0) + (unmatched?.items?.length ?? 0)
                : tab === "schedule" ? (unmatched?.items?.length ?? 0)
                : (durationRules?.length ?? 0)
            }
            filtered={
              tab === "classify" ? classifySearchCounts.filtered
                : tab === "company" ? filteredCompany.length + filteredUnmatched.length
                : tab === "departure" ? filteredDeparture.length + filteredUnmatched.length
                : tab === "duration" ? filteredDuration.length + filteredUnmatched.length
                : tab === "schedule" ? filteredUnmatched.length
                : filteredDuration.length
            }
          />
        </div>
        {/* Per-tab refresh button — Issue #3: mỗi tab (cả schedule/festival/compare)
            có nút Refresh riêng. Sticky bar global vẫn giữ cho "Áp dụng tất cả". */}
        <button
          type="button"
          onClick={onRefreshCurrentTab}
          disabled={applying}
          className="btn-secondary text-sm flex items-center gap-1.5 shrink-0 disabled:opacity-60"
          title={refreshTabTitle}
        >
          <RefreshCw size={14} className={applying ? "animate-spin" : ""} />
          {refreshTabLabel}
        </button>
      </div>

      {tab === "classify" && (
        <ClassificationRulesTab
          routeRules={routeRules}
          searchQuery={search}
          gapItems={filteredUnmatched}
          gapLoading={unmatchedLoading}
          marketOptions={marketOptions}
          routeKeywordConflicts={routeKeywordConflicts}
          routeStats={routeStats}
          dropTarget={dropTarget}
          setDropTarget={setDropTarget}
          onAfterSaved={afterRuleSaved}
          onMarkGapsHandled={markGapsHandled}
          onGapAssignFailed={unmarkGapsHandled}
          onError={showErr}
          appendKeywordToRouteRule={appendKeywordToRouteRule}
          deleteRouteRule={deleteRouteRule}
          toggleRoutePriority={toggleRoutePriority}
          editRouteKeywords={editRouteKeywords}
          actionBtns={actionBtns}
        />
      )}

      {tab === "company" && (
        <div className="grid lg:grid-cols-[3fr_2fr] gap-4 items-start">
          {/* LEFT: Form thêm + bảng rules */}
          <div className="space-y-3">
            <div className="card p-4 flex flex-wrap gap-2 items-end">
              <div><label className="text-xs text-gray-500">Tên chính thức</label>
                <input className="input text-sm" value={cCanonical} onChange={(e) => setCCanonical(e.target.value)} placeholder="Vietravel" /></div>
              <div className="flex-1 min-w-[180px]"><label className="text-xs text-gray-500">Alias</label>
                <input className="input text-sm" value={cAlias} onChange={(e) => setCAlias(e.target.value)} placeholder="vietravel, vtr..."
                  onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); setCAlias(e.dataTransfer.getData("text/plain")); }} /></div>
              <div className="flex gap-2">
                <button onClick={() => addCompany.mutate()} disabled={!cCanonical || !cAlias} className="btn-primary text-sm"><Plus size={14} /> Thêm</button>
                <button onClick={() => seedCompanyDefaults().then(() => afterRuleSaved("Đã import alias mặc định"))} className="btn-secondary text-sm"><Database size={14} /> Mặc định</button>
              </div>
            </div>
            <AliasTable
              rows={filteredCompany} unmatched={filteredUnmatched} hideUnmatched
              canonicalOptions={canonicalOptions} editingId={editingId} editDraft={editDraft}
              dropTarget={dropTarget} setDropTarget={setDropTarget}
              onDropAssign={(canonical, alias) => assignCompanyAlias(canonical, alias)}
              onStartEdit={(r) => startEdit(r.id, { canonical_name: r.canonical_name, alias: r.alias })}
              onDraftChange={setEditDraft} onCancel={cancelEdit}
              onSave={(r) => updateCompanyRule(r.id, { canonical_name: editDraft.canonical_name, alias: editDraft.alias }).then(() => { cancelEdit(); afterRuleSaved("Đã cập nhật alias công ty"); })}
              onDelete={(r) => deleteCompanyRule(r.id).then(() => afterRuleSaved("Đã xóa alias"))}
              canonicalLabel="Tên chính thức"
            />
          </div>
          {/* RIGHT: Chưa khớp */}
          <SideUnmatchedAlias
            items={filteredUnmatched}
            canonicalOptions={canonicalOptions}
            onAssign={(canonical, alias) => assignCompanyAlias(canonical, alias)}
            label="Tên chính thức"
          />
        </div>
      )}

      {tab === "departure" && (
        <div className="grid lg:grid-cols-[3fr_2fr] gap-4 items-start">
          {/* LEFT: Form thêm + bảng rules */}
          <div className="space-y-3">
            <div className="card p-4 flex flex-wrap gap-2 items-end">
              <div><label className="text-xs text-gray-500">Tên chính thức</label>
                <input className="input text-sm" value={dCanonical} onChange={(e) => setDCanonical(e.target.value)} placeholder="TP.HCM" /></div>
              <div className="flex-1 min-w-[180px]"><label className="text-xs text-gray-500">Alias</label>
                <input className="input text-sm" value={dAlias} onChange={(e) => setDAlias(e.target.value)} placeholder="sài gòn, hcm..."
                  onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); setDAlias(e.dataTransfer.getData("text/plain")); }} /></div>
              <div className="flex gap-2">
                <button onClick={() => addDeparture.mutate()} disabled={!dCanonical || !dAlias} className="btn-primary text-sm"><Plus size={14} /> Thêm</button>
                <button onClick={() => seedDepartureDefaults().then(() => afterRuleSaved("Đã import alias mặc định"))} className="btn-secondary text-sm"><Database size={14} /> Mặc định</button>
              </div>
            </div>
            <p className="text-xs text-gray-500 inline-flex items-center gap-1">
              Chuẩn hóa {COL.diemKhoiHanh}.<InfoTip text="Sài Gòn / HCM / TPHCM → TP.HCM. Bấm bút chì để sửa từng dòng." />
            </p>
            <AliasTable
              rows={filteredDeparture} unmatched={filteredUnmatched} hideUnmatched
              canonicalOptions={canonicalOptions} editingId={editingId} editDraft={editDraft}
              dropTarget={dropTarget} setDropTarget={setDropTarget}
              onDropAssign={(canonical, alias) => assignDepartureAlias(canonical, alias)}
              onStartEdit={(r) => startEdit(r.id, { canonical_name: r.canonical_name, alias: r.alias })}
              onDraftChange={setEditDraft} onCancel={cancelEdit}
              onSave={(r) => updateDepartureRule(r.id, { canonical_name: editDraft.canonical_name, alias: editDraft.alias }).then(() => { cancelEdit(); afterRuleSaved("Đã cập nhật alias điểm KH"); })}
              onDelete={(r) => deleteDepartureRule(r.id).then(() => afterRuleSaved("Đã xóa alias"))}
              canonicalLabel="Tên chính thức"
            />
          </div>
          {/* RIGHT: Chưa khớp */}
          <SideUnmatchedAlias
            items={filteredUnmatched}
            canonicalOptions={canonicalOptions}
            onAssign={(canonical, alias) => assignDepartureAlias(canonical, alias)}
            label="Tên chính thức"
          />
        </div>
      )}

      {tab === "duration" && (
        <div className="grid lg:grid-cols-[3fr_2fr] gap-4 items-start">
          {/* LEFT: Form thêm + bảng rules */}
          <div className="space-y-3">
            <div className="card p-4 flex flex-wrap gap-2 items-end">
              <div>
                <label className="text-xs text-gray-500">Chuẩn (NĐ)</label>
                <input className="input text-sm w-28" value={durDays} onChange={(e) => setDurDays(e.target.value)} placeholder="5N4Đ" />
                {parsedDurDays != null && durDays.trim() && <span className="text-[10px] text-gray-500 block mt-0.5">= {parsedDurDays} ngày</span>}
              </div>
              <div className="flex-1 min-w-[160px]">
                <label className="text-xs text-gray-500">Alias (text gốc)</label>
                <input className="input text-sm" value={durAlias} onChange={(e) => setDurAlias(e.target.value)} placeholder="5n4d, 5 ngày 4 đêm..."
                  onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); setDurAlias(e.dataTransfer.getData("text/plain")); }} />
              </div>
              <div className="flex gap-2">
                <button onClick={() => addDuration.mutate()} disabled={parsedDurDays == null || !durAlias} className="btn-primary text-sm"><Plus size={14} /> Thêm</button>
                <button onClick={() => seedDurationDefaults().then(() => afterRuleSaved("Đã import alias mặc định"))} className="btn-secondary text-sm"><Database size={14} /> Mặc định</button>
              </div>
            </div>
            <p className="text-xs text-gray-500 inline-flex items-center gap-1">
              Chuẩn dạng NĐ: 5N4Đ→5, 5N5Đ→5.5, 1N→1, 0.5N→0.5 (1 buổi).<InfoTip text="Alias khớp không phân biệt hoa thường." />
            </p>
            <div className="card overflow-auto" style={{ maxHeight: "calc(100vh - 280px)" }}>
              <table className="w-full text-sm">
                <thead className="bg-gray-50 sticky top-0"><tr>
                  <th className="px-3 py-2 text-left">Chuẩn (NĐ) <span className="text-[10px] font-normal text-gray-400">(thả alias)</span></th>
                  <th className="px-3 py-2 text-left">Alias</th>
                  <th className="w-24" />
                </tr></thead>
                <tbody>
                  {filteredDuration.map((r: DurationRule) => {
                    const key = `dur-${r.canonical_days}`;
                    const { dropClassName, ...drop } = dropHandlers(key, dropTarget, setDropTarget, (alias) => assignDurationAlias(r.canonical_days, alias));
                    return (
                    <tr key={r.id} className={cn("border-t", editingId === r.id && "bg-blue-50")}>
                      <td className={cn("px-3 py-2 font-medium", dropClassName)} {...drop}>
                        {editingId === r.id ? (
                          <input className="input text-sm py-1 w-24" value={editDraft.canonical_label ?? formatDurationLabel(r.canonical_days)} onChange={(e) => setEditDraft({ ...editDraft, canonical_label: e.target.value })} />
                        ) : (
                          <span className="flex items-center gap-1">{formatDurationLabel(r.canonical_days)}
                            <span className="text-[10px] text-gray-400">({r.canonical_days})</span>
                            <button type="button" className="text-gray-400 hover:text-primary-600" onClick={() => startEdit(r.id, { canonical_label: formatDurationLabel(r.canonical_days), alias: r.alias })}><Pencil size={12} /></button>
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {editingId === r.id ? <input className="input text-sm py-1 font-mono" value={editDraft.alias ?? ""} onChange={(e) => setEditDraft({ ...editDraft, alias: e.target.value })} /> : r.alias}
                      </td>
                      <td className="px-3 py-2">
                        {editingId === r.id ? (
                          <span className="flex gap-1">
                            <button type="button" className="text-green-600" onClick={() => {
                              const days = parseDurationInput(editDraft.canonical_label ?? "");
                              if (days == null) { setSyncMsg("Chuẩn NĐ không hợp lệ (VD: 5N4Đ, 0.5N)"); return; }
                              updateDurationRule(r.id, { canonical_days: days, alias: editDraft.alias }).then(() => { afterRuleSaved("Đã cập nhật alias thời gian"); cancelEdit(); }).catch(showErr);
                            }}><Check size={14} /></button>
                            <button type="button" className="text-gray-400" onClick={cancelEdit}><X size={14} /></button>
                          </span>
                        ) : (
                          <button type="button" className="text-red-500" onClick={() => deleteDurationRule(r.id).then(() => { invalidate(); setSyncMsg("Đã xóa alias"); })}><Trash2 size={14} /></button>
                        )}
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="text-xs text-gray-400 p-3">{filteredDuration.length} rules</p>
            </div>
          </div>
          {/* RIGHT: Chưa khớp */}
          <SideUnmatchedDuration items={filteredUnmatched} onAssign={(days, alias) => assignDurationAlias(days, alias)} />
        </div>
      )}

      {tab === "schedule" && (
        <DateFormatRulesTab
          search={search}
          onMessage={setSyncMsg}
          unmatched={filteredUnmatched}
          unmatchedLoading={unmatchedLoading}
          onMarkHandled={markGapsHandled}
        />
      )}

      {tab === "festival" && (
        <FestivalMappingRulesTab search={search} onMessage={setSyncMsg} />
      )}

      {tab === "compare" && (
        <CompareSegmentRuleTab isAdmin={isAdmin} onMessage={setSyncMsg} />
      )}

      {/* ─── Sticky Apply Bar (fixed bottom) ─────────────────────────────── */}
      <div className="fixed bottom-0 left-0 right-0 z-50 border-t border-gray-200 bg-white/95 backdrop-blur-sm shadow-lg px-6 py-3 flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-0">
          {syncMsg ? (
            <p className={cn(
              "text-xs px-3 py-1.5 rounded border max-w-xl truncate",
              applying || syncMsg.includes("Đang") ? "text-amber-900 bg-amber-50 border-amber-200"
                : syncMsg.includes("thất bại") || syncMsg.includes("Lỗi") ? "text-red-800 bg-red-50 border-red-200"
                : "text-green-800 bg-green-50 border-green-200"
            )}>{syncMsg}</p>
          ) : (
            <p className="text-xs text-gray-400">
              Sau khi thêm / sửa rule, bấm «Áp dụng» để cập nhật phân loại tour.
            </p>
          )}
        </div>
        <label className="text-xs text-gray-700 flex items-center gap-2 cursor-pointer shrink-0">
          <input type="checkbox" checked={fullScanApply} onChange={(e) => setFullScanApply(e.target.checked)} />
          <span>Quét toàn bộ</span>
          <span className="text-gray-400">(khi đổi rule lớn)</span>
        </label>
        <button
          type="button"
          onClick={onApplyTours}
          disabled={applying}
          className="btn-primary text-sm flex items-center gap-1.5 shrink-0 disabled:opacity-60"
        >
          <RefreshCw size={14} className={applying ? "animate-spin" : ""} />
          {applying ? "Đang áp dụng…" : "Áp dụng lên tour"}
        </button>
      </div>
    </div>
  );
}

// ── Side panel "Chưa khớp" cho tab Công ty / Điểm KH ─────────────────────────
function SideUnmatchedAlias({
  items, canonicalOptions, onAssign, label,
}: {
  items: UnmatchedItem[];
  canonicalOptions: string[];
  onAssign: (canonical: string, alias: string) => Promise<boolean>;
  label: string;
}) {
  const [pending, setPending] = useState<Record<string, string>>({});
  // Per-row pending: user gán liên tiếp nhiều dòng → mỗi dòng tự quản spinner riêng
  const [busy, setBusy] = useState<Set<string>>(() => new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const runAssign = async (item: UnmatchedItem) => {
    const c = (pending[item.value] ?? "").trim();
    if (!c || busy.has(item.value)) return;
    setBusy((prev) => new Set(prev).add(item.value));
    try {
      const ok = await onAssign(c, item.value);
      // Lỗi → giữ input để user sửa / thử lại (dòng đã được rollback về panel)
      if (ok) setPending((p) => { const n = { ...p }; delete n[item.value]; return n; });
    } finally {
      setBusy((prev) => { const n = new Set(prev); n.delete(item.value); return n; });
    }
  };

  if (!items.length) return (
    <div className="card p-6 flex flex-col items-center justify-center text-center text-gray-400 min-h-[160px]">
      <Check size={24} className="text-green-500 mb-2" />
      <p className="text-sm font-medium text-green-700">Tất cả alias đã khớp</p>
      <p className="text-xs mt-1">Không có giá trị nào cần gán thêm</p>
    </div>
  );

  return (
    <div className="card overflow-auto" style={{ maxHeight: "calc(100vh - 280px)" }}>
      <div className="px-3 py-2 border-b bg-amber-50 sticky top-0 z-10">
        <p className="text-xs font-semibold text-amber-900 flex items-center gap-1.5">
          <GripVertical size={13} />
          Chưa khớp alias ({items.length}) — nhập {label} rồi bấm Gán
        </p>
      </div>
      <table className="w-full text-xs">
        <thead className="bg-amber-50/60">
          <tr>
            <th className="px-2 py-1.5 text-left text-amber-800">{label}</th>
            <th className="px-2 py-1.5 text-left text-amber-800">Alias chưa khớp</th>
            <th className="w-14" />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.value} className="border-t border-amber-100 bg-amber-50/30 align-top">
              <td className="px-2 py-1.5">
                <input
                  className="input text-xs py-1 w-full border-amber-300 bg-white"
                  placeholder={`${label}...`}
                  list="side-canonical-suggestions"
                  value={pending[item.value] ?? ""}
                  onChange={(e) => setPending({ ...pending, [item.value]: e.target.value })}
                />
              </td>
              <td className="px-2 py-1.5">
                <span {...dragAliasProps(item.value)} className="flex items-center gap-1 text-amber-900 font-mono cursor-grab">
                  <GripVertical size={9} className="text-amber-500 shrink-0" />
                  <span className="truncate">{item.value || "—"}</span>
                  <span className="text-gray-400 shrink-0">×{item.count}</span>
                </span>
                {(item.members ?? []).length > 0 && (
                  <>
                    <button type="button" className="text-[10px] text-amber-600 hover:underline mt-0.5 block"
                      onClick={() => setExpanded((p) => { const n = new Set(p); n.has(item.value) ? n.delete(item.value) : n.add(item.value); return n; })}>
                      {expanded.has(item.value) ? "▲ Ẩn" : `▼ ${(item.members ?? []).length} mẫu`}
                    </button>
                    {expanded.has(item.value) && (
                      <ul className="mt-1 space-y-0.5">
                        {(item.members ?? []).slice(0, 15).map((m: any, i: number) => (
                          <li key={i} className="text-[10px] text-gray-600 bg-white rounded px-1 py-0.5 leading-snug">
                            {m.link_url ? (
                              <a href={m.link_url} target="_blank" rel="noopener noreferrer"
                                className="text-primary-600 hover:underline break-words" title={m.title}>
                                {m.title || "(không tên)"}
                              </a>
                            ) : (
                              <span className="break-words" title={m.title}>{m.title || "(không tên)"}</span>
                            )}
                            {m.cong_ty && <span className="text-gray-400"> · {m.cong_ty}</span>}
                            {m.count > 1 && <span className="text-gray-400"> ×{m.count}</span>}
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
              </td>
              <td className="px-2 py-1.5">
                <button type="button"
                  className="btn-primary text-[10px] py-1 px-2 whitespace-nowrap disabled:opacity-60"
                  disabled={!(pending[item.value] ?? "").trim() || busy.has(item.value)}
                  onClick={() => void runAssign(item)}>
                  {busy.has(item.value) ? <RefreshCw size={10} className="animate-spin" /> : "Gán"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <datalist id="side-canonical-suggestions">
        {canonicalOptions.map((c) => <option key={c} value={c} />)}
      </datalist>
    </div>
  );
}

// ── Side panel "Chưa khớp" cho tab Thời gian ────────────────────────────────
function SideUnmatchedDuration({ items, onAssign }: { items: UnmatchedItem[]; onAssign: (days: number, alias: string) => Promise<boolean> }) {
  if (!items.length) return (
    <div className="card p-6 flex flex-col items-center justify-center text-center text-gray-400 min-h-[160px]">
      <Check size={24} className="text-green-500 mb-2" />
      <p className="text-sm font-medium text-green-700">Tất cả alias thời gian đã khớp</p>
    </div>
  );
  return (
    <div className="card overflow-auto" style={{ maxHeight: "calc(100vh - 280px)" }}>
      <div className="px-3 py-2 border-b bg-amber-50 sticky top-0 z-10">
        <p className="text-xs font-semibold text-amber-900">Chưa khớp thời gian ({items.length})</p>
        <p className="text-[10px] text-amber-700 mt-0.5">Nhập số ngày → bấm Gán</p>
      </div>
      <table className="w-full text-xs">
        <thead className="bg-amber-50/60">
          <tr>
            <th className="px-2 py-1.5 text-left text-amber-800">Số ngày</th>
            <th className="px-2 py-1.5 text-left text-amber-800">Alias chưa khớp</th>
            <th className="w-14" />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => <SideUnmatchedDurationRow key={item.value} item={item} onAssign={onAssign} />)}
        </tbody>
      </table>
    </div>
  );
}

function SideUnmatchedDurationRow({ item, onAssign }: { item: UnmatchedItem; onAssign: (days: number, alias: string) => Promise<boolean> }) {
  const [days, setDays] = useState("");
  // Per-row pending — không disable cả panel khi đang gán 1 dòng
  const [busy, setBusy] = useState(false);
  const runAssign = async () => {
    const d = parseFloat(days);
    if (Number.isNaN(d) || busy) return;
    setBusy(true);
    try {
      const ok = await onAssign(d, item.value);
      if (ok) setDays(""); // lỗi → giữ input để thử lại (dòng đã rollback về panel)
    } finally {
      setBusy(false);
    }
  };
  return (
    <tr className="border-t border-amber-100 bg-amber-50/30">
      <td className="px-2 py-1.5">
        <input className="input text-xs py-1 w-20 border-amber-300 bg-white" type="number" min={1} max={45} placeholder="5" value={days} onChange={(e) => setDays(e.target.value)} />
      </td>
      <td className="px-2 py-1.5 font-mono text-amber-900">
        <span {...dragAliasProps(item.value)} className="flex items-center gap-1 cursor-grab">
          <GripVertical size={9} className="text-amber-500 shrink-0" />
          <span className="truncate">{item.value || "—"}</span>
          <span className="text-gray-400">×{item.count}</span>
        </span>
        <UnmatchedMembers members={item.members} itemKey={item.value} />
      </td>
      <td className="px-2 py-1.5">
        <button type="button" className="btn-primary text-[10px] py-1 px-2 disabled:opacity-60"
          disabled={!days || Number.isNaN(parseFloat(days)) || busy}
          onClick={() => void runAssign()}>
          {busy ? <RefreshCw size={10} className="animate-spin" /> : "Gán"}
        </button>
      </td>
    </tr>
  );
}

function AliasTable({
  rows, unmatched, canonicalOptions, editingId, editDraft, dropTarget, setDropTarget, onDropAssign,
  onStartEdit, onDraftChange, onCancel, onSave, onDelete, canonicalLabel, hideUnmatched = false,
}: {
  rows: Array<CompanyRule | DepartureRule>;
  unmatched: UnmatchedItem[];
  canonicalOptions: string[];
  editingId: string | null;
  editDraft: Record<string, string>;
  dropTarget: string | null;
  setDropTarget: (k: string | null) => void;
  onDropAssign: (canonical: string, alias: string) => Promise<boolean>;
  onStartEdit: (r: CompanyRule | DepartureRule) => void;
  onDraftChange: (d: Record<string, string>) => void;
  onCancel: () => void;
  onSave: (r: CompanyRule | DepartureRule) => void;
  onDelete: (r: CompanyRule | DepartureRule) => void;
  canonicalLabel: string;
  hideUnmatched?: boolean;
}) {
  const [pending, setPending] = useState<Record<string, string>>({});
  // Per-row pending khi gán alias từ section "Chưa khớp"
  const [busyAssign, setBusyAssign] = useState<Set<string>>(() => new Set());
  // id rule giờ là string (CockroachDB unique_rowid() > 2^53)
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [expandedUnmatched, setExpandedUnmatched] = useState<Set<string>>(() => new Set());

  const runAssign = async (item: UnmatchedItem) => {
    const c = (pending[item.value] ?? "").trim();
    if (!c || busyAssign.has(item.value)) return;
    setBusyAssign((prev) => new Set(prev).add(item.value));
    try {
      const ok = await onDropAssign(c, item.value);
      if (ok) setPending((p) => { const n = { ...p }; delete n[item.value]; return n; });
    } finally {
      setBusyAssign((prev) => { const n = new Set(prev); n.delete(item.value); return n; });
    }
  };

  return (
    <div className="card overflow-auto max-h-[560px]">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 sticky top-0 z-10"><tr>
          <th className="px-3 py-2 text-left">{canonicalLabel} <span className="text-[10px] font-normal text-gray-400">(thả alias vào đây)</span></th>
          <th className="px-3 py-2 text-left">Alias</th>
          <th className="w-32"></th>
        </tr></thead>
        <tbody>
          {rows.map((r) => {
            const key = `alias-${r.canonical_name}`;
            const { dropClassName, ...drop } = dropHandlers(key, dropTarget, setDropTarget, (alias) => onDropAssign(r.canonical_name, alias));
            return (
            <tr key={r.id} className={cn("border-t", editingId === r.id && "bg-blue-50")}>
              <td className={cn("px-3 py-2 font-medium", dropClassName)} {...drop}>
                {editingId === r.id ? (
                  <input className="input text-sm py-1" value={editDraft.canonical_name ?? ""} onChange={(e) => onDraftChange({ ...editDraft, canonical_name: e.target.value })} />
                ) : (
                  <span className="flex items-center gap-1">{r.canonical_name}
                    <button type="button" className="text-gray-400 hover:text-primary-600" onClick={() => onStartEdit(r)}><Pencil size={12} /></button>
                  </span>
                )}
              </td>
              <td className="px-3 py-2 font-mono text-xs">
                {editingId === r.id ? (
                  <input className="input text-sm py-1 font-mono" value={editDraft.alias ?? ""} onChange={(e) => onDraftChange({ ...editDraft, alias: e.target.value })} />
                ) : r.alias}
              </td>
              <td className="px-3 py-2">
                {editingId === r.id ? (
                  <span className="flex gap-1">
                    <button type="button" className="text-green-600" onClick={() => onSave(r)}><Check size={14} /></button>
                    <button type="button" className="text-gray-400" onClick={onCancel}><X size={14} /></button>
                  </span>
                ) : confirmId === r.id ? (
                  // Confirm xóa 2-bước
                  <span className="flex gap-1 items-center">
                    <span className="text-xs text-red-700 font-medium">Xóa?</span>
                    <button type="button" className="text-[10px] bg-red-600 text-white px-1.5 py-0.5 rounded hover:bg-red-700" onClick={() => { setConfirmId(null); onDelete(r); }}>Có</button>
                    <button type="button" className="text-[10px] bg-gray-100 px-1.5 py-0.5 rounded" onClick={() => setConfirmId(null)}>Không</button>
                  </span>
                ) : (
                  <button type="button" className="text-red-400 hover:text-red-600 p-1" onClick={() => setConfirmId(r.id)} title="Xóa alias này"><Trash2 size={13} /></button>
                )}
              </td>
            </tr>
            );
          })}

          {!hideUnmatched && unmatched.length > 0 && (
            <>
              <tr className="bg-amber-100 border-t-2 border-amber-400">
                <td colSpan={3} className="px-3 py-2 text-xs font-semibold text-amber-900">
                  <span className="inline-flex items-center gap-1">
                    <GripVertical size={12} /> Chưa khớp ({unmatched.length}) — kéo cột Alias lên {canonicalLabel} phía trên, hoặc nhập tên chuẩn rồi bấm Gán
                  </span>
                </td>
              </tr>
              {unmatched.map((item) => (
                <tr key={item.value} className="bg-amber-50/70 border-t border-amber-200">
                  <td className="px-3 py-2">
                    <input
                      className="input text-xs py-1 w-full border-amber-300 bg-white"
                      placeholder={`${canonicalLabel}...`}
                      list="canonical-suggestions"
                      value={pending[item.value] ?? ""}
                      onChange={(e) => setPending({ ...pending, [item.value]: e.target.value })}
                    />
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-amber-950">
                    <div>
                      <span {...dragAliasProps(item.value)} title={`${item.count} tour · kéo lên dòng phía trên`} className="flex items-center gap-1">
                        <GripVertical size={10} className="text-amber-600 shrink-0" />
                        {item.value || "—"}
                        <span className="text-gray-500">({item.count})</span>
                      </span>
                      {/* Expand để xem sample tours */}
                      {(item.members ?? []).length > 0 && (
                        <button
                          type="button"
                          className="text-[10px] text-amber-700 hover:underline mt-0.5 block"
                          onClick={() => setExpandedUnmatched((prev) => {
                            const next = new Set(prev);
                            next.has(item.value) ? next.delete(item.value) : next.add(item.value);
                            return next;
                          })}
                        >
                          {expandedUnmatched.has(item.value) ? "▲ Ẩn mẫu" : `▼ Xem ${(item.members ?? []).length} tour mẫu`}
                        </button>
                      )}
                      {expandedUnmatched.has(item.value) && (item.members ?? []).length > 0 && (
                        <ul className="mt-1 space-y-0.5 text-[10px] text-gray-600 font-sans">
                          {(item.members ?? []).slice(0, 15).map((m: any, i: number) => (
                            <li key={i} className="flex items-start gap-1 bg-amber-100 rounded px-1 py-0.5">
                              <span className="text-amber-600 shrink-0">·</span>
                              {m.link_url ? (
                                <a href={m.link_url} target="_blank" rel="noopener noreferrer"
                                  className="text-primary-600 hover:underline break-words" title={m.title}>
                                  {m.title || "(không tên)"}
                                </a>
                              ) : (
                                <span className="break-words" title={m.title}>{m.title || "(không tên)"}</span>
                              )}
                              {m.cong_ty && <span className="text-gray-400 shrink-0">· {m.cong_ty}</span>}
                              {m.count > 1 && <span className="text-gray-400 shrink-0">×{m.count}</span>}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      className="btn-primary text-[10px] py-1 px-2 disabled:opacity-60"
                      disabled={!(pending[item.value] ?? "").trim() || busyAssign.has(item.value)}
                      onClick={() => void runAssign(item)}
                    >
                      {busyAssign.has(item.value) ? <RefreshCw size={10} className="animate-spin" /> : "Gán"}
                    </button>
                  </td>
                </tr>
              ))}
            </>
          )}
        </tbody>
      </table>
      <datalist id="canonical-suggestions">
        {canonicalOptions.map((c) => <option key={c} value={c} />)}
      </datalist>
      <p className="text-xs text-gray-400 p-3">{rows.length} rules · {unmatched.length} chưa khớp</p>
    </div>
  );
}

// UnmatchedDurationRow đã được thay thế bởi SideUnmatchedDurationRow trong SideUnmatchedDuration


// ── Định dạng Ngày KH (pattern-based date format rules) ─────────────────────
// Admin tự định nghĩa pattern parse lich_kh (vd "Tháng {mm}: {dd}, {dd}") qua UI
// thay vì hardcode trong code. Mỗi rule có:
//   - pattern: DSL với {dd} {mm} {yyyy} {yy} {weekday} {...} + literal text
//   - output_type: dates | weekly | monthly_recurring | skip | verbatim
//   - priority asc: rule có priority nhỏ thử trước
const OUTPUT_TYPE_LABELS: Record<DateFormatOutputType, string> = {
  dates: "Danh sách ngày",
  weekly: "Hàng tuần (recurring)",
  monthly_recurring: "Hàng tháng (recurring)",
  skip: "Bỏ qua tour",
  verbatim: "Text cố định (bỏ qua)",
  explicit_dates: "Gán chính xác ngày",
};

function DateFormatRulesTab({
  search,
  onMessage,
  unmatched,
  unmatchedLoading,
  onMarkHandled,
}: {
  search: string;
  onMessage: (msg: string) => void;
  unmatched: UnmatchedItem[];
  unmatchedLoading: boolean;
  onMarkHandled: (values: string[]) => void;
}) {
  const qc = useQueryClient();
  const { data: rules, isLoading } = useQuery({
    queryKey: ["date-format-rules"],
    queryFn: listDateFormatRules,
  });

  // Form thêm rule
  const [pattern, setPattern] = useState("");
  const [outputType, setOutputType] = useState<DateFormatOutputType>("dates");
  const [outputValue, setOutputValue] = useState<string>("");
  const [priority, setPriority] = useState<string>("100");
  const [description, setDescription] = useState("");

  // Edit state — id string (CockroachDB unique_rowid())
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<{
    pattern: string;
    output_type: DateFormatOutputType;
    output_value: string;
    priority: string;
    description: string;
    active: boolean;
  } | null>(null);

  // Test widget
  const [testText, setTestText] = useState("");
  const [testResult, setTestResult] = useState<DateFormatTestResult | null>(null);
  const [testError, setTestError] = useState("");

  const filtered = useMemo(() => {
    return (rules ?? []).filter((r) =>
      matchSearch(search, r.pattern, r.output_type, r.description, r.priority),
    );
  }, [rules, search]);

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["date-format-rules"] });
    qc.invalidateQueries({ queryKey: ["rules-unmatched-summary"] });
  }, [qc]);

  const showErr = (e: unknown) => {
    const msg =
      (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      || (e as Error)?.message
      || String(e);
    onMessage(msg);
  };

  const addMut = useMutation({
    mutationFn: () =>
      createDateFormatRule({
        pattern: pattern.trim(),
        output_type: outputType,
        output_value: outputType === "explicit_dates" ? outputValue.trim() : null,
        priority: parseInt(priority, 10) || 100,
        description: description.trim(),
        active: true,
      }),
    onSuccess: () => {
      setPattern("");
      setDescription("");
      setOutputValue("");
      setPriority("100");
      invalidate();
      onMessage("Đã thêm rule mới");
    },
    onError: showErr,
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteDateFormatRule(id),
    onSuccess: () => {
      invalidate();
      onMessage("Đã xóa rule");
    },
    onError: showErr,
  });

  const startEdit = (r: DateFormatRule) => {
    setEditingId(r.id);
    setEditDraft({
      pattern: r.pattern,
      output_type: r.output_type,
      output_value: r.output_value || "",
      priority: String(r.priority),
      description: r.description,
      active: r.active,
    });
  };
  const cancelEdit = () => {
    setEditingId(null);
    setEditDraft(null);
  };
  const saveEdit = async () => {
    if (!editingId || !editDraft) return;
    try {
      await updateDateFormatRule(editingId, {
        pattern: editDraft.pattern.trim(),
        output_type: editDraft.output_type,
        output_value:
          editDraft.output_type === "explicit_dates" ? editDraft.output_value.trim() : null,
        priority: parseInt(editDraft.priority, 10) || 100,
        description: editDraft.description.trim(),
        active: editDraft.active,
      });
      cancelEdit();
      invalidate();
      onMessage("Đã lưu rule");
    } catch (e) {
      showErr(e);
    }
  };

  const onSeedDefaults = async () => {
    try {
      const res = await seedDateFormatDefaults();
      invalidate();
      onMessage(res.message || "Đã import rule mặc định");
    } catch (e) {
      showErr(e);
    }
  };

  const onTest = async () => {
    setTestError("");
    setTestResult(null);
    if (!testText.trim()) return;
    try {
      const res = await testDateFormat(testText);
      setTestResult(res);
    } catch (e) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e as Error)?.message
        || String(e);
      setTestError(msg);
    }
  };

  return (
    <div className="grid lg:grid-cols-[3fr_2fr] gap-4 items-start">
      {/* LEFT: Form + bảng rules */}
      <div className="space-y-3">
        {/* Banner */}
        <div className="rounded-md bg-primary-50/70 border border-primary-100 px-3 py-2 text-[11px] text-primary-800 space-y-1">
          <p className="font-semibold">
            Hệ thống parse ngày KH theo các rule dưới đây. Bạn có thể thêm/sửa pattern.
          </p>
          <p>
            Pattern dùng placeholder:
            <code className="bg-white px-1 rounded mx-0.5">{"{dd}"}</code>
            <code className="bg-white px-1 rounded mx-0.5">{"{mm}"}</code>
            <code className="bg-white px-1 rounded mx-0.5">{"{yyyy}"}</code>
            <code className="bg-white px-1 rounded mx-0.5">{"{yy}"}</code>
            <code className="bg-white px-1 rounded mx-0.5">{"{weekday}"}</code>
            <code className="bg-white px-1 rounded mx-0.5">{"{...}"}</code> (wildcard).
            Rule có priority nhỏ thử trước.
          </p>
        </div>

        {/* Form thêm */}
        <div className="card p-4 grid grid-cols-12 gap-2 items-end">
          <div className="col-span-12 sm:col-span-5">
            <label className="text-xs text-gray-500">Pattern</label>
            <input
              className="input text-sm font-mono"
              value={pattern}
              onChange={(e) => setPattern(e.target.value)}
              placeholder="Tháng {mm}: {dd}, {dd}"
              onKeyDown={keepInputKeys}
            />
          </div>
          <div className="col-span-6 sm:col-span-3">
            <label className="text-xs text-gray-500">Output type</label>
            <select
              className="input text-sm"
              value={outputType}
              onChange={(e) => setOutputType(e.target.value as DateFormatOutputType)}
            >
              {Object.entries(OUTPUT_TYPE_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </div>
          <div className="col-span-6 sm:col-span-2">
            <label className="text-xs text-gray-500">Priority</label>
            <input
              className="input text-sm"
              type="number"
              min={1}
              max={10000}
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            />
          </div>
          {outputType === "explicit_dates" && (
            <div className="col-span-12">
              <label className="text-xs text-gray-500">
                Giá trị gán (DD/MM/YYYY, ngăn cách bằng <code>,</code> hoặc <code>;</code>)
              </label>
              <input
                className="input text-sm font-mono"
                value={outputValue}
                onChange={(e) => setOutputValue(e.target.value)}
                placeholder="25/06/2026, 28/07/2026"
                onKeyDown={keepInputKeys}
              />
              <p className="text-[10px] text-gray-500 mt-1">
                Khi text gốc match pattern, hệ thống bỏ qua nội dung và gán list ngày này.
                Vd: pattern <code>25/06; 28-07</code> → output <code>25/06/2026, 28/07/2026</code>.
              </p>
            </div>
          )}
          <div className="col-span-12 sm:col-span-9">
            <label className="text-xs text-gray-500">Mô tả (tùy chọn)</label>
            <input
              className="input text-sm"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Liệt kê ngày trong tháng…"
              onKeyDown={keepInputKeys}
            />
          </div>
          <div className="col-span-12 sm:col-span-3 flex gap-2">
            <button
              type="button"
              className="btn-primary text-sm"
              disabled={
                !pattern.trim()
                || (outputType === "explicit_dates" && !outputValue.trim())
                || addMut.isPending
              }
              onClick={() => addMut.mutate()}
            >
              <Plus size={14} /> Thêm rule
            </button>
            <button
              type="button"
              className="btn-secondary text-sm"
              onClick={onSeedDefaults}
            >
              <Database size={14} /> Mặc định
            </button>
          </div>
        </div>

        {/* Bảng rules */}
        <div className="card overflow-auto" style={{ maxHeight: "calc(100vh - 360px)" }}>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="px-3 py-2 text-left w-16">Prio</th>
                <th className="px-3 py-2 text-left">Pattern</th>
                <th className="px-3 py-2 text-left w-44">Type</th>
                <th className="px-3 py-2 text-left">Mô tả</th>
                <th className="w-20" />
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr><td colSpan={5} className="px-3 py-4 text-center text-gray-400">Đang tải…</td></tr>
              )}
              {!isLoading && filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-gray-400">
                    Chưa có rule. Bấm "Mặc định" để import 14 rule chuẩn.
                  </td>
                </tr>
              )}
              {filtered.map((r) => {
                const isEditing = editingId === r.id;
                return (
                  <tr key={r.id} className={cn("border-t", isEditing && "bg-blue-50", !r.active && "opacity-60")}>
                    <td className="px-3 py-2">
                      {isEditing ? (
                        <input
                          className="input text-sm py-1 w-16"
                          type="number"
                          value={editDraft?.priority ?? ""}
                          onChange={(e) => setEditDraft((p) => p ? { ...p, priority: e.target.value } : p)}
                        />
                      ) : (
                        <span className="text-xs text-gray-600">{r.priority}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {isEditing ? (
                        <input
                          className="input text-sm py-1 font-mono w-full"
                          value={editDraft?.pattern ?? ""}
                          onChange={(e) => setEditDraft((p) => p ? { ...p, pattern: e.target.value } : p)}
                        />
                      ) : (
                        <span className="break-all">{r.pattern}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {isEditing ? (
                        <select
                          className="input text-sm py-1"
                          value={editDraft?.output_type ?? "dates"}
                          onChange={(e) => setEditDraft((p) => p ? { ...p, output_type: e.target.value as DateFormatOutputType } : p)}
                        >
                          {Object.entries(OUTPUT_TYPE_LABELS).map(([k, v]) => (
                            <option key={k} value={k}>{v}</option>
                          ))}
                        </select>
                      ) : (
                        <span className={cn(
                          "inline-block px-1.5 py-0.5 rounded text-[10px] font-medium",
                          r.output_type === "dates" ? "bg-blue-100 text-blue-800"
                            : r.output_type === "weekly" ? "bg-emerald-100 text-emerald-800"
                            : r.output_type === "monthly_recurring" ? "bg-purple-100 text-purple-800"
                            : r.output_type === "explicit_dates" ? "bg-amber-100 text-amber-800"
                            : "bg-gray-200 text-gray-700"
                        )}>
                          {OUTPUT_TYPE_LABELS[r.output_type] ?? r.output_type}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600">
                      {isEditing ? (
                        <div className="space-y-1">
                          <input
                            className="input text-sm py-1 w-full"
                            value={editDraft?.description ?? ""}
                            onChange={(e) => setEditDraft((p) => p ? { ...p, description: e.target.value } : p)}
                            placeholder="Mô tả"
                          />
                          {editDraft?.output_type === "explicit_dates" && (
                            <input
                              className="input text-sm py-1 w-full font-mono"
                              value={editDraft?.output_value ?? ""}
                              onChange={(e) => setEditDraft((p) => p ? { ...p, output_value: e.target.value } : p)}
                              placeholder="25/06/2026, 28/07/2026"
                            />
                          )}
                        </div>
                      ) : (
                        <div>
                          {r.description || <span className="text-gray-400">—</span>}
                          {r.output_type === "explicit_dates" && r.output_value && (
                            <div className="text-[10px] text-amber-700 font-mono mt-0.5">
                              → {r.output_value}
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {isEditing ? (
                        <span className="flex gap-1">
                          <button type="button" className="text-green-600 p-1" onClick={saveEdit} title="Lưu">
                            <Check size={14} />
                          </button>
                          <button type="button" className="text-gray-400 p-1" onClick={cancelEdit} title="Huỷ">
                            <X size={14} />
                          </button>
                        </span>
                      ) : (
                        <span className="flex gap-1">
                          <button
                            type="button"
                            className="text-gray-500 hover:text-primary-600 p-1"
                            onClick={() => startEdit(r)}
                            title="Sửa"
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            type="button"
                            className="text-red-500 p-1"
                            onClick={() => {
                              if (confirm(`Xóa rule "${r.pattern}"?`)) deleteMut.mutate(r.id);
                            }}
                            title="Xóa"
                          >
                            <Trash2 size={14} />
                          </button>
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="text-xs text-gray-400 p-3">{filtered.length} rules</p>
        </div>
      </div>

      {/* RIGHT: Test widget */}
      <div className="card p-4 space-y-3 sticky top-4">
        <div>
          <p className="text-sm font-semibold text-gray-800">Test pattern</p>
          <p className="text-[11px] text-gray-500 mt-0.5">
            Nhập text mẫu từ <code className="bg-gray-100 px-1 rounded">lich_kh</code> để xem rule nào match + ngày parse ra.
          </p>
        </div>
        <textarea
          className="input text-sm font-mono w-full"
          rows={4}
          value={testText}
          onChange={(e) => setTestText(e.target.value)}
          placeholder="Tháng 6: 13, 20, 27"
        />
        <button
          type="button"
          className="btn-primary text-sm w-full"
          disabled={!testText.trim()}
          onClick={onTest}
        >
          Test
        </button>
        {testError && (
          <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2">
            {testError}
          </p>
        )}
        {testResult && (
          <div className="text-xs space-y-2 bg-gray-50 border border-gray-200 rounded p-2">
            {testResult.matched_rule_id ? (
              <>
                <p>
                  <span className="text-gray-500">Rule:</span>{" "}
                  <span className="font-mono">#{testResult.matched_rule_id}</span>{" "}
                  <span className={cn(
                    "ml-1 inline-block px-1.5 py-0.5 rounded text-[10px] font-medium",
                    testResult.output_type === "dates" ? "bg-blue-100 text-blue-800"
                      : testResult.output_type === "weekly" ? "bg-emerald-100 text-emerald-800"
                      : testResult.output_type === "monthly_recurring" ? "bg-purple-100 text-purple-800"
                      : testResult.output_type === "explicit_dates" ? "bg-amber-100 text-amber-800"
                      : "bg-gray-200 text-gray-700"
                  )}>
                    {OUTPUT_TYPE_LABELS[(testResult.output_type ?? "dates") as DateFormatOutputType]}
                  </span>
                </p>
                <p>
                  <span className="text-gray-500">Số ngày:</span>{" "}
                  <span className="font-bold">{testResult.count}</span>
                </p>
                {testResult.dates.length > 0 && (
                  <div>
                    <p className="text-gray-500 mb-1">Ngày parse:</p>
                    <ul className="space-y-0.5 max-h-48 overflow-auto">
                      {testResult.dates.slice(0, 30).map((d) => (
                        <li key={d} className="font-mono text-[11px] bg-white rounded px-1.5 py-0.5">
                          {d.slice(0, 10)}
                        </li>
                      ))}
                      {testResult.dates.length > 30 && (
                        <li className="text-gray-400 text-[10px]">… +{testResult.dates.length - 30} ngày</li>
                      )}
                    </ul>
                  </div>
                )}
                {testResult.dates.length === 0 && (
                  <p className="text-amber-700">Match nhưng không có ngày — output_type là "{testResult.output_type}" (bỏ qua tour).</p>
                )}
              </>
            ) : (
              <p className="text-gray-600">Không có rule nào match — bạn có thể thêm rule mới ở bên trái.</p>
            )}
          </div>
        )}
      </div>

      {/* RIGHT: Panel "Chưa khớp rule" */}
      <div className="card sticky top-4 max-h-[calc(100vh-120px)] overflow-hidden flex flex-col">
        <div className="bg-amber-50 border-b border-amber-200 px-3 py-2">
          <p className="text-xs font-semibold text-amber-900">
            Chưa khớp rule ({unmatched.length}) — click để Test
          </p>
          <p className="text-[10px] text-amber-700 mt-0.5">
            Giá trị <code>lich_kh</code> trong DB chưa có rule nào match. Click 1 item → load vào Test → thêm rule phù hợp.
          </p>
        </div>
        <div className="overflow-y-auto flex-1 divide-y divide-gray-100">
          {unmatchedLoading && (
            <p className="px-3 py-4 text-xs text-gray-400 text-center">Đang tải…</p>
          )}
          {!unmatchedLoading && unmatched.length === 0 && (
            <p className="px-3 py-6 text-xs text-gray-400 text-center">
              Tuyệt vời! Không còn giá trị chưa khớp 🎉
            </p>
          )}
          {unmatched.slice(0, 100).map((item) => (
            <div key={item.value} className="px-3 py-2 hover:bg-amber-50 transition-colors group">
              <button
                type="button"
                onClick={() => {
                  setTestText(item.value);
                  setTestResult(null);
                  setTestError("");
                  // Scroll test widget vào view
                  setTimeout(() => {
                    document.querySelector("textarea[placeholder*='Test']")?.scrollIntoView({ behavior: "smooth", block: "center" });
                  }, 50);
                }}
                className="w-full text-left"
                title="Click để load vào Test widget"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[11px] font-mono text-gray-800 break-all flex-1 line-clamp-2 group-hover:line-clamp-none">
                    {item.value}
                  </span>
                  <span className="text-[10px] text-amber-700 font-semibold shrink-0">
                    ×{item.count}
                  </span>
                </div>
              </button>
              <UnmatchedMembers members={item.members} itemKey={item.value} />
            </div>
          ))}
          {unmatched.length > 100 && (
            <p className="px-3 py-2 text-[10px] text-gray-400 text-center bg-gray-50">
              ... còn {unmatched.length - 100} giá trị khác (lọc bằng Search ở trên)
            </p>
          )}
        </div>
        {unmatched.length > 0 && (
          <div className="border-t border-gray-200 p-2">
            <button
              type="button"
              onClick={() => onMarkHandled(unmatched.map((u) => u.value))}
              className="w-full text-[10px] btn-secondary py-1"
              title="Đánh dấu đã xử lý — ẩn khỏi panel cho đến lần refresh tới"
            >
              ✓ Đánh dấu tất cả đã xử lý
            </button>
          </div>
        )}
      </div>
    </div>
  );
}


// ── Tab Lễ hội: Manual mapping festival → tour (qua keyword TT/Tuyến) ────────
function FestivalMappingRulesTab({ search, onMessage }: { search: string; onMessage: (msg: string) => void }) {
  const qc = useQueryClient();
  const { data: rules } = useQuery({ queryKey: ["festival-mapping-rules"], queryFn: listFestivalMappingRules });
  const { data: festivals } = useQuery({
    queryKey: ["festivals-all"],
    queryFn: () => listFestivals({ limit: 2000 }),
    staleTime: 6 * 60 * 60 * 1000,
  });
  // Filter options: list thi_truong + tuyen_tour có sẵn trong DB tour
  const { data: filterOpts } = useQuery({
    queryKey: ["tour-filter-options"],
    queryFn: getFilterOptions,
    staleTime: 5 * 60 * 1000,
  });

  // Form thêm
  const [location, setLocation] = useState("");
  const [market, setMarket] = useState("");
  const [route, setRoute] = useState("");
  const [note, setNote] = useState("");

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<{ location_keyword: string; market_keyword: string; route_keyword: string; note: string; active: boolean } | null>(null);

  // Distinct festival locations (parse từ location_text, lấy part cuối = tỉnh/nước)
  const locationOptions = useMemo(() => {
    const set = new Set<string>();
    (festivals ?? []).forEach((f) => {
      const text = f.location_text || "";
      if (!text) return;
      const parts = text.split(",").map(s => s.trim()).filter(Boolean);
      const last = parts[parts.length - 1] || "";
      const cleaned = last.replace(/^(T\.|TP\.|P\.|X\.|H\.|Q\.)\s*/i, "").trim();
      if (cleaned.length >= 2) set.add(cleaned);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b, "vi"));
  }, [festivals]);

  // Festival matching the current location (preview)
  const matchedFestivals = useMemo(() => {
    if (!location || !festivals) return [];
    const lk = location.toLowerCase();
    return festivals.filter(f => (f.location_text || "").toLowerCase().includes(lk));
  }, [festivals, location]);

  // Chọn địa điểm + auto-suggest thị trường (dùng cho select & nút "Map" panel chưa map)
  const applyLocation = useCallback((loc: string) => {
    setLocation(loc);
    if (loc && filterOpts) {
      const lowerLoc = loc.toLowerCase();
      const tt = filterOpts.thi_truong.find(t => t.toLowerCase() === lowerLoc)
        || filterOpts.thi_truong.find(t => t.toLowerCase().includes(lowerLoc) || lowerLoc.includes(t.toLowerCase()))
        || "";
      setMarket(tt);
      setRoute("");
    }
  }, [filterOpts]);

  // Địa điểm CÓ lễ hội nhưng CHƯA có rule map nào phủ → admin biết cái nào cần map.
  // "Phủ" = có 1 rule active mà location_keyword là chuỗi con của tên địa điểm.
  const unmappedLocations = useMemo(() => {
    const cleanLoc = (text: string) => {
      const parts = (text || "").split(",").map(s => s.trim()).filter(Boolean);
      const last = parts[parts.length - 1] || "";
      return last.replace(/^(T\.|TP\.|P\.|X\.|H\.|Q\.)\s*/i, "").trim();
    };
    const byLoc = new Map<string, string[]>();
    (festivals ?? []).forEach((f) => {
      const loc = cleanLoc(f.location_text || "");
      if (loc.length < 2) return;
      if (!byLoc.has(loc)) byLoc.set(loc, []);
      byLoc.get(loc)!.push(f.name_vi);
    });
    const activeRules = (rules ?? []).filter(r => r.active && r.location_keyword.trim());
    const covered = (loc: string) => {
      const low = loc.toLowerCase();
      return activeRules.some(r => low.includes(r.location_keyword.trim().toLowerCase()));
    };
    return Array.from(byLoc.entries())
      .filter(([loc]) => !covered(loc))
      .map(([loc, names]) => ({ loc, count: names.length, names }))
      .sort((a, b) => b.count - a.count);
  }, [festivals, rules]);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["festival-mapping-rules"] });

  const showErr = (e: unknown) => {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      || (e as Error)?.message || String(e);
    onMessage("Lỗi: " + msg);
  };

  const addMut = useMutation({
    mutationFn: () => createFestivalMappingRule({
      location_keyword: location.trim(),
      market_keyword: market.trim(),
      route_keyword: route.trim(),
      note: note.trim(),
      active: true,
    }),
    onSuccess: () => {
      setLocation(""); setMarket(""); setRoute(""); setNote("");
      invalidate();
      onMessage("Đã thêm rule");
    },
    onError: showErr,
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteFestivalMappingRule(id),
    onSuccess: () => { invalidate(); onMessage("Đã xóa rule"); },
    onError: showErr,
  });
  const applyMut = useMutation({
    mutationFn: applyFestivalMappingRules,
    onSuccess: (r) => {
      onMessage(r.message + " — chi tiết: " + r.details.map(d => `${d.festival_name || d.festival_slug}: +${d.tagged}`).join(", "));
      qc.invalidateQueries({ queryKey: ["festivals"] });
    },
    onError: showErr,
  });
  const startEdit = (r: FestivalMappingRule) => {
    setEditingId(r.id);
    setEditDraft({
      location_keyword: r.location_keyword,
      market_keyword: r.market_keyword,
      route_keyword: r.route_keyword,
      note: r.note,
      active: r.active,
    });
  };
  const saveEdit = async () => {
    if (!editingId || !editDraft) return;
    try {
      await updateFestivalMappingRule(editingId, editDraft);
      setEditingId(null); setEditDraft(null);
      invalidate();
      onMessage("Đã lưu");
    } catch (e) { showErr(e); }
  };

  const filtered = useMemo(() => {
    if (!rules) return [];
    if (!search.trim()) return rules;
    const kw = search.toLowerCase();
    return rules.filter((r) =>
      r.location_keyword.toLowerCase().includes(kw)
      || r.market_keyword.toLowerCase().includes(kw)
      || r.route_keyword.toLowerCase().includes(kw)
      || r.note.toLowerCase().includes(kw)
    );
  }, [rules, search]);

  return (
    <div className="space-y-3">
      <div className="rounded-md bg-primary-50/70 border border-primary-100 px-3 py-2 text-[11px] text-primary-800 space-y-1">
        <p className="font-semibold">
          Map <span className="underline">địa điểm tổ chức lễ</span> ↔ <span className="underline">Thị trường / Tuyến tour</span>
        </p>
        <p>
          1. Chọn <strong>Địa điểm tổ chức</strong> (vd "Đắk Lắk") — rule sẽ áp dụng cho TẤT CẢ lễ hội tổ chức ở đó. <br />
          2. Chọn <strong>Thị trường</strong> và/hoặc <strong>Tuyến tour</strong> từ dropdown DB tour. <br />
          3. Bấm <strong>Áp dụng mapping</strong> → mỗi tour TT/Tuyến khớp được tag vào lễ GẦN NHẤT ở location đó.
             Tour đã có festival_slug khác sẽ KHÔNG bị ghi đè.
        </p>
      </div>

      {/* Form thêm */}
      <div className="card p-4 space-y-3">
        <div className="grid grid-cols-12 gap-2 items-end">
          <div className="col-span-12 lg:col-span-6">
            <label className="text-xs text-gray-500">Địa điểm tổ chức lễ hội</label>
            <select className="input text-sm" value={location}
              onChange={(e) => applyLocation(e.target.value)}>
              <option value="">-- Chọn địa điểm --</option>
              {locationOptions.map((loc) => (
                <option key={loc} value={loc}>{loc}</option>
              ))}
            </select>
          </div>
          <div className="col-span-12 lg:col-span-6">
            {location && (
              <div className="rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-[11px] text-amber-900">
                <p><strong>{matchedFestivals.length}</strong> lễ hội ở "{location}":
                  {matchedFestivals.length > 0 ? (
                    <span className="ml-1">{matchedFestivals.slice(0, 3).map(f => f.name_vi).join(", ")}
                      {matchedFestivals.length > 3 ? ` +${matchedFestivals.length - 3} khác` : ""}
                    </span>
                  ) : <span className="ml-1 text-amber-700">(chưa có lễ nào — rule sẽ chạy khi crawl thêm)</span>}
                </p>
              </div>
            )}
          </div>
        </div>
        <div className="grid grid-cols-12 gap-2 items-end">
          <div className="col-span-12 lg:col-span-5">
            <label className="text-xs text-gray-500">Thị trường</label>
            <select className="input text-sm" value={market}
              onChange={(e) => { setMarket(e.target.value); setRoute(""); }}>
              <option value="">-- Tất cả thị trường --</option>
              {(filterOpts?.thi_truong ?? []).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
          <div className="col-span-12 lg:col-span-5">
            <label className="text-xs text-gray-500">
              Tuyến tour {market ? "(theo thị trường đã chọn)" : "(chọn thị trường trước hoặc tự nhập)"}
            </label>
            <select className="input text-sm" value={route}
              onChange={(e) => setRoute(e.target.value)}>
              <option value="">-- Tùy chọn / để trống --</option>
              {(market
                ? (filterOpts?.routes_by_market?.[market] ?? [])
                : (filterOpts?.tuyen_tour ?? [])
              ).map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
          <div className="col-span-12 lg:col-span-2 flex gap-1">
            <button type="button" className="btn-primary text-sm w-full"
              disabled={!location.trim() || (!market.trim() && !route.trim()) || addMut.isPending}
              onClick={() => addMut.mutate()}>
              <Plus size={14} /> Thêm rule
            </button>
          </div>
        </div>
        <div>
          <label className="text-xs text-gray-500">Ghi chú (tùy chọn)</label>
          <input className="input text-sm w-full" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Mô tả..." onKeyDown={keepInputKeys} />
        </div>
      </div>

      {/* Địa điểm có lễ hội nhưng chưa có rule map */}
      <div className="card overflow-hidden">
        <div className="bg-amber-50 border-b border-amber-200 px-3 py-2">
          <p className="text-xs font-semibold text-amber-900">
            Địa điểm chưa map ({unmappedLocations.length}) — có lễ hội nhưng chưa có rule
          </p>
          <p className="text-[10px] text-amber-700 mt-0.5">
            Bấm <strong>Map</strong> để nạp địa điểm vào form bên trên → chọn Thị trường/Tuyến → Thêm rule.
          </p>
        </div>
        {unmappedLocations.length === 0 ? (
          <p className="px-3 py-4 text-xs text-gray-400 text-center">
            <Check size={16} className="inline text-green-500 mr-1" />
            Mọi địa điểm có lễ hội đều đã có rule map 🎉
          </p>
        ) : (
          <ul className="divide-y divide-gray-100 max-h-72 overflow-y-auto">
            {unmappedLocations.map((u) => (
              <li key={u.loc} className="flex items-start gap-2 px-3 py-2 hover:bg-amber-50/50">
                <div className="flex-1 min-w-0">
                  <span className="text-xs font-medium text-gray-800">{u.loc}</span>
                  <span className="text-[10px] text-amber-700 ml-1">· {u.count} lễ hội</span>
                  <span className="block text-[10px] text-gray-500 truncate" title={u.names.join(", ")}>
                    {u.names.slice(0, 3).join(", ")}{u.names.length > 3 ? ` +${u.names.length - 3} khác` : ""}
                  </span>
                </div>
                <button type="button" className="btn-secondary text-[10px] py-1 px-2 shrink-0"
                  onClick={() => {
                    applyLocation(u.loc);
                    window.scrollTo({ top: 0, behavior: "smooth" });
                  }}>
                  Map →
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Apply bar */}
      <div className="card p-3 flex items-center justify-between bg-amber-50 border-amber-200">
        <p className="text-xs text-amber-900">
          Đã có <strong>{rules?.length ?? 0}</strong> rule. Bấm bên phải để chạy mapping cho TẤT CẢ tour matching.
        </p>
        <button type="button" className="btn-primary text-sm"
          disabled={applyMut.isPending || !rules?.length}
          onClick={() => applyMut.mutate()}>
          {applyMut.isPending ? <RefreshCw size={14} className="animate-spin" /> : <Check size={14} />}
          Áp dụng mapping
        </button>
      </div>

      {/* Table */}
      <div className="card overflow-auto" style={{ maxHeight: "calc(100vh - 460px)" }}>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              <th className="px-3 py-2 text-left">Địa điểm tổ chức</th>
              <th className="px-3 py-2 text-left">Thị trường</th>
              <th className="px-3 py-2 text-left">Tuyến tour</th>
              <th className="px-3 py-2 text-left">Ghi chú</th>
              <th className="px-3 py-2 w-24">Active</th>
              <th className="px-3 py-2 w-20" />
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-gray-400">
                Chưa có rule mapping. Thêm rule ở form trên.
              </td></tr>
            )}
            {filtered.map((r) => {
              const isEditing = editingId === r.id;
              return (
                <tr key={r.id} className={cn("border-t", isEditing && "bg-blue-50", !r.active && "opacity-60")}>
                  <td className="px-3 py-2">
                    {isEditing ? (
                      <select className="input text-sm py-1 w-full"
                        value={editDraft?.location_keyword ?? ""}
                        onChange={(e) => setEditDraft((p) => p ? { ...p, location_keyword: e.target.value } : p)}>
                        {locationOptions.map((loc) => (
                          <option key={loc} value={loc}>{loc}</option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-gray-900 text-xs">{r.location_keyword}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {isEditing ? (
                      <select className="input text-sm py-1 w-full"
                        value={editDraft?.market_keyword ?? ""}
                        onChange={(e) => setEditDraft((p) => p ? { ...p, market_keyword: e.target.value, route_keyword: "" } : p)}>
                        <option value="">— Tất cả —</option>
                        {(filterOpts?.thi_truong ?? []).map((m) => (
                          <option key={m} value={m}>{m}</option>
                        ))}
                      </select>
                    ) : (r.market_keyword || <span className="text-gray-400">—</span>)}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {isEditing ? (
                      <select className="input text-sm py-1 w-full"
                        value={editDraft?.route_keyword ?? ""}
                        onChange={(e) => setEditDraft((p) => p ? { ...p, route_keyword: e.target.value } : p)}>
                        <option value="">— Tùy chọn —</option>
                        {(editDraft?.market_keyword
                          ? (filterOpts?.routes_by_market?.[editDraft.market_keyword] ?? [])
                          : (filterOpts?.tuyen_tour ?? [])
                        ).map((r2) => (
                          <option key={r2} value={r2}>{r2}</option>
                        ))}
                      </select>
                    ) : (r.route_keyword || <span className="text-gray-400">—</span>)}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-600">
                    {isEditing ? (
                      <input className="input text-sm py-1 w-full" value={editDraft?.note ?? ""}
                        onChange={(e) => setEditDraft((p) => p ? { ...p, note: e.target.value } : p)} />
                    ) : (r.note || <span className="text-gray-400">—</span>)}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {isEditing ? (
                      <input type="checkbox" checked={editDraft?.active ?? true}
                        onChange={(e) => setEditDraft((p) => p ? { ...p, active: e.target.checked } : p)} />
                    ) : (r.active ? <span className="text-green-600 text-xs">✓</span> : <span className="text-gray-400 text-xs">—</span>)}
                  </td>
                  <td className="px-3 py-2">
                    {isEditing ? (
                      <span className="flex gap-1">
                        <button type="button" className="text-green-600 p-1" onClick={saveEdit} title="Lưu"><Check size={14} /></button>
                        <button type="button" className="text-gray-400 p-1" onClick={() => { setEditingId(null); setEditDraft(null); }} title="Huỷ"><X size={14} /></button>
                      </span>
                    ) : (
                      <span className="flex gap-1">
                        <button type="button" className="text-blue-600 p-1" onClick={() => startEdit(r)} title="Sửa"><Pencil size={14} /></button>
                        <button type="button" className="text-red-500 p-1"
                          onClick={() => { if (confirm("Xóa rule này?")) deleteMut.mutate(r.id); }}
                          title="Xóa"><Trash2 size={14} /></button>
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Tab "So sánh VTR ↔ Thị trường": admin-config compare segment rule ────────
function CompareSegmentRuleTab({ isAdmin, onMessage }: { isAdmin: boolean; onMessage: (msg: string) => void }) {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["compare-segment-rule"],
    queryFn: getCompareSegmentRule,
    staleTime: 60_000,
  });
  const [draftVtr, setDraftVtr] = useState<string[] | null>(null);
  const [draftMkt, setDraftMkt] = useState<string[] | null>(null);

  const currentVtr = draftVtr ?? data?.vtr_tiers ?? [];
  const currentMkt = draftMkt ?? data?.market_phan_khuc ?? [];
  const isDirty = (draftVtr !== null && JSON.stringify(draftVtr) !== JSON.stringify(data?.vtr_tiers))
    || (draftMkt !== null && JSON.stringify(draftMkt) !== JSON.stringify(data?.market_phan_khuc));

  const saveMut = useMutation({
    mutationFn: () => updateCompareSegmentRule({
      vtr_tiers: currentVtr,
      market_phan_khuc: currentMkt,
    }),
    onSuccess: (updated) => {
      qc.setQueryData(["compare-segment-rule"], updated);
      qc.invalidateQueries({ queryKey: ["compare"] });
      qc.invalidateQueries({ queryKey: ["market-lab"] });
      qc.invalidateQueries({ queryKey: ["insights"] });
      setDraftVtr(null);
      setDraftMkt(null);
      onMessage("Đã lưu quy tắc so sánh — cache đã được làm mới");
    },
    onError: (err) => {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail
        || (err as Error).message || "Lỗi không xác định";
      onMessage(`Lỗi khi lưu: ${msg}`);
    },
  });

  const resetToDefault = () => {
    if (!data) return;
    setDraftVtr(["Tiết kiệm", "Giá Tốt"]);
    setDraftMkt(["Premium"]);
  };

  const toggleItem = (list: string[], setter: (v: string[]) => void, item: string) => {
    if (list.includes(item)) {
      setter(list.filter((x) => x !== item));
    } else {
      setter([...list, item]);
    }
  };

  if (isLoading) return <div className="card p-6 text-center text-gray-500">Đang tải…</div>;
  if (error) return <div className="card p-6 text-red-600 text-sm">Lỗi: {(error as Error).message}</div>;
  if (!data) return null;

  return (
    <div className="space-y-4">
      {/* Method explanation */}
      <div className="card border-primary-100 bg-primary-50/40 p-4 text-sm text-gray-700 space-y-2">
        <h3 className="font-semibold text-primary-900 flex items-center gap-1.5">
          <Database size={14} /> Quy tắc so sánh giá VTR ↔ Thị trường
        </h3>
        <p className="text-xs">
          Module <strong>So sánh VTR</strong>, <strong>Market Lab</strong>, <strong>Insight Engine</strong> đều dùng
          quy tắc này để chọn TOUR NÀO tham gia so sánh GIÁ (tần suất khởi hành vẫn dùng toàn bộ tour, không lọc).
        </p>
        <ul className="text-xs list-disc list-inside space-y-1">
          <li>
            <strong>Phía Vietravel</strong>: lọc theo cột <code className="bg-white px-1 rounded">Dòng tour</code>{" "}
            (Tiết kiệm / Giá Tốt / Tiêu chuẩn / Cao cấp / Tour ESG & LEI).
          </li>
          <li>
            <strong>Phía Thị trường (đối thủ)</strong>: lọc theo cột <code className="bg-white px-1 rounded">Phân khúc</code>{" "}
            (Standard / Premium / Luxury) — auto compute trong sync.
          </li>
          <li>
            Default cũ (hardcoded): VTR (Tiết kiệm + Giá Tốt) vs Thị trường (Premium). Giờ có thể chỉnh tùy ý.
          </li>
          <li>
            Lưu thành công sẽ <strong>invalidate cache</strong> ngay → request kế tiếp dùng quy tắc mới.
          </li>
        </ul>
      </div>

      {/* Current rule state */}
      <div className="card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div>
            <h3 className="text-sm font-semibold text-gray-800">Quy tắc đang áp dụng</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              {data.is_default ? (
                <span className="text-amber-700">Đang dùng default — chưa admin nào cấu hình</span>
              ) : data.updated_at ? (
                <>Cập nhật lần cuối {new Date(data.updated_at).toLocaleString("vi-VN")}{" "}
                  {data.updated_by && <span>bởi <strong>{data.updated_by}</strong></span>}</>
              ) : null}
            </p>
          </div>
          {isAdmin && (
            <div className="flex gap-2">
              <button type="button" className="btn-secondary text-xs" onClick={resetToDefault}>
                <RefreshCw size={12} /> Reset default
              </button>
              <button type="button" className="btn-primary text-xs"
                disabled={!isAdmin || !isDirty || saveMut.isPending || currentVtr.length === 0 || currentMkt.length === 0}
                onClick={() => saveMut.mutate()}>
                {saveMut.isPending ? <RefreshCw size={12} className="animate-spin" /> : <Check size={12} />}
                Lưu thay đổi
              </button>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* VTR side */}
          <div className="border rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-semibold text-primary-700">Phía Vietravel (Dòng tour)</h4>
              <span className="text-xs text-gray-500">{currentVtr.length}/{data.available_vtr_tiers.length}</span>
            </div>
            <div className="space-y-1.5">
              {data.available_vtr_tiers.map((tier) => {
                const checked = currentVtr.includes(tier);
                return (
                  <label key={tier} className={cn(
                    "flex items-center gap-2 px-2 py-1.5 rounded text-sm cursor-pointer border",
                    checked ? "bg-primary-50 border-primary-300" : "bg-white border-gray-200 hover:bg-gray-50",
                    !isAdmin && "cursor-not-allowed opacity-70",
                  )}>
                    <input type="checkbox" checked={checked} disabled={!isAdmin}
                      onChange={() => toggleItem(currentVtr, (v) => setDraftVtr(v), tier)} />
                    <span className={checked ? "font-medium text-primary-900" : "text-gray-700"}>{tier}</span>
                  </label>
                );
              })}
            </div>
            {currentVtr.length === 0 && (
              <p className="text-xs text-red-600 mt-2">⚠ Phải chọn ít nhất 1 Dòng tour.</p>
            )}
          </div>

          {/* Market side */}
          <div className="border rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-semibold text-emerald-700">Phía Thị trường (Phân khúc)</h4>
              <span className="text-xs text-gray-500">{currentMkt.length}/{data.available_market_phan_khuc.length}</span>
            </div>
            <div className="space-y-1.5">
              {data.available_market_phan_khuc.map((phk) => {
                const checked = currentMkt.includes(phk);
                return (
                  <label key={phk} className={cn(
                    "flex items-center gap-2 px-2 py-1.5 rounded text-sm cursor-pointer border",
                    checked ? "bg-emerald-50 border-emerald-300" : "bg-white border-gray-200 hover:bg-gray-50",
                    !isAdmin && "cursor-not-allowed opacity-70",
                  )}>
                    <input type="checkbox" checked={checked} disabled={!isAdmin}
                      onChange={() => toggleItem(currentMkt, (v) => setDraftMkt(v), phk)} />
                    <span className={checked ? "font-medium text-emerald-900" : "text-gray-700"}>{phk}</span>
                  </label>
                );
              })}
            </div>
            {currentMkt.length === 0 && (
              <p className="text-xs text-red-600 mt-2">⚠ Phải chọn ít nhất 1 Phân khúc.</p>
            )}
          </div>
        </div>

        {/* Preview */}
        <div className="mt-4 p-3 bg-gray-50 rounded-lg border text-xs">
          <p className="font-semibold text-gray-700 mb-1">Preview rule áp dụng:</p>
          <p className="text-gray-600">
            So sánh tour Vietravel có Dòng tour ∈ {" "}
            <span className="font-mono bg-primary-100 px-1 rounded">[{currentVtr.join(", ") || "—"}]</span>
            {" "} với tour Thị trường có Phân khúc ∈ {" "}
            <span className="font-mono bg-emerald-100 px-1 rounded">[{currentMkt.join(", ") || "—"}]</span>
            .
          </p>
        </div>

        {!isAdmin && (
          <p className="text-xs text-amber-700 mt-3">
            ⚠ Chỉ admin mới có quyền sửa rule này. Bạn đang ở chế độ chỉ xem.
          </p>
        )}
      </div>
    </div>
  );
}

