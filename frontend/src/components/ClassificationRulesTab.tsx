import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { RouteRule, UnmatchedItem } from "@/lib/api";
import {
  assignClassification,
  assignClassificationBulk,
  getClassifyMarketOrder,
  putClassifyMarketOrder,
  previewKeywordMatch,
  seedRouteDefaults,
} from "@/lib/api";
import { buildRouteKeywordConflicts, conflictHintForKeyword, parseRouteKeywordList } from "@/lib/rulesUnmatched";
import { UnmatchedMembers } from "@/components/UnmatchedMembers";
import { InfoTip } from "@/components/InfoTip";
import { cn } from "@/lib/utils";
import { ChevronDown, ChevronRight, Database, GripVertical, Plus, RefreshCw, Trash2, Search, Users, Star, Pencil, Check, X } from "lucide-react";
import {
  dropHandlers,
  dragAliasProps,
  keepInputKeys,
  keywordForRouteDrop,
  marketVisibleInRulesSearch,
  matchRulesSearch,
  RouteKeywordsCell,
  routeDatalistId,
  uniqueRouteNames,
} from "@/lib/rulesAdminUi";

type Props = {
  routeRules: RouteRule[] | undefined;
  searchQuery: string;
  gapItems: UnmatchedItem[];
  gapLoading: boolean;
  marketOptions: string[];
  routeKeywordConflicts: ReturnType<typeof buildRouteKeywordConflicts>;
  routeStats?: Record<string, number>; // tour count per rule_id
  dropTarget: string | null;
  setDropTarget: (k: string | null) => void;
  onAfterSaved: (msg: string, opts?: { gapValues?: string[]; skipPoll?: boolean }) => void;
  onMarkGapsHandled: (values: string[]) => void;
  onGapAssignFailed: (values: string[]) => void;
  onError: (e: unknown) => void;
  appendKeywordToRouteRule: (rule: RouteRule, raw: string) => Promise<void>;
  deleteRouteRule: (id: string) => Promise<void>;
  toggleRoutePriority: (rule: RouteRule) => Promise<void>;
  editRouteKeywords: (rule: RouteRule, newKeywords: string) => Promise<void>;
  actionBtns: (onDelete: () => void, onSave?: () => void) => React.ReactNode;
};

function sortRouteRulesForDisplay(rules: RouteRule[]): RouteRule[] {
  return [...rules].sort((a, b) => {
    const routeCmp = (a.tuyen_tour || "").localeCompare(b.tuyen_tour || "", "vi");
    if (routeCmp !== 0) return routeCmp;
    const na = parseRouteKeywordList(a.keywords).length;
    const nb = parseRouteKeywordList(b.keywords).length;
    if (nb !== na) return nb - na;
    // id giờ là string (CockroachDB unique_rowid() > 2^53) → so sánh chuỗi thay cho phép trừ
    return a.sort_order - b.sort_order || a.id.localeCompare(b.id);
  });
}

export function ClassificationRulesTab({
  routeRules,
  searchQuery,
  gapItems,
  gapLoading,
  marketOptions,
  routeKeywordConflicts,
  routeStats,
  dropTarget,
  setDropTarget,
  onAfterSaved,
  onMarkGapsHandled,
  onGapAssignFailed,
  onError,
  appendKeywordToRouteRule,
  deleteRouteRule,
  toggleRoutePriority,
  editRouteKeywords,
  actionBtns,
}: Props) {
  const [qMarket, setQMarket] = useState("");
  const [qRoute, setQRoute] = useState("");
  const [qRouteKw, setQRouteKw] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [dragMarket, setDragMarket] = useState<string | null>(null);
  const [dropMarket, setDropMarket] = useState<string | null>(null);
  const [actionFeedback, setActionFeedback] = useState<{ kind: "loading" | "ok" | "err"; text: string } | null>(null);

  const { data: marketOrderData, refetch: refetchMarketOrder } = useQuery({
    queryKey: ["classify-market-order"],
    queryFn: getClassifyMarketOrder,
  });

  const [pending, setPending] = useState<Record<string, {
    market: string;
    route: string;
    routeKw: string;
  }>>({});

  // Preview keyword match (#6)
  const [previewKw, setPreviewKw] = useState("");
  const [previewDebouncedKw, setPreviewDebouncedKw] = useState("");
  // id đổi sang string (CockroachDB unique_rowid() > 2^53 → JS làm tròn)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null); // confirm delete 2-step (#4)
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);
  const [togglingPriorityId, setTogglingPriorityId] = useState<string | null>(null);

  const startEdit = (rule: RouteRule) => {
    setEditingRuleId(rule.id);
    setEditDraft(rule.keywords);
    setConfirmDeleteId(null);
  };
  const cancelEdit = () => { setEditingRuleId(null); setEditDraft(""); };
  const saveEdit = async (rule: RouteRule) => {
    const kw = editDraft.trim();
    if (!kw || kw === rule.keywords) { cancelEdit(); return; }
    setSavingEdit(true);
    try {
      await editRouteKeywords(rule, kw);
      onAfterSaved(`Đã cập nhật keywords: ${kw}`);
      cancelEdit();
    } catch (e) { onError(e); }
    finally { setSavingEdit(false); }
  };
  const handleTogglePriority = async (rule: RouteRule) => {
    setTogglingPriorityId(rule.id);
    try {
      await toggleRoutePriority(rule);
      const label = rule.priority ? "thường" : "ưu tiên (★)";
      onAfterSaved(`Rule «${rule.tuyen_tour}» → ${label}`);
    } catch (e) { onError(e); }
    finally { setTogglingPriorityId(null); }
  };
  useEffect(() => {
    const t = window.setTimeout(() => setPreviewDebouncedKw(previewKw), 600);
    return () => window.clearTimeout(t);
  }, [previewKw]);
  const { data: previewResult, isFetching: previewFetching } = useQuery({
    queryKey: ["preview-keyword", previewDebouncedKw],
    queryFn: () => previewKeywordMatch(previewDebouncedKw, 20),
    enabled: previewDebouncedKw.trim().length >= 2,
    staleTime: 30_000,
  });
  const [selectedGaps, setSelectedGaps] = useState<Set<string>>(() => new Set());
  // assigning = bulk "Gán N dòng"; assigningRows = per-row pending (gán liên tiếp
  // nhiều dòng → mỗi dòng tự quản spinner riêng, không disable cả panel)
  const [assigning, setAssigning] = useState(false);
  const [assigningRows, setAssigningRows] = useState<Set<string>>(() => new Set());
  const [quickAdding, setQuickAdding] = useState(false);

  const applyResultMessage = (
    r: Awaited<ReturnType<typeof assignClassification>>,
    fallback: string,
  ) => r.tours_apply?.message || r.tours_apply?.result?.message || r.message || fallback;

  const rowDraft = (title: string, item: UnmatchedItem) => {
    const p = pending[title];
    return {
      market: (p?.market ?? item.suggested_market ?? item.resolved_market ?? "").trim(),
      route: (p?.route ?? item.suggested_route ?? "").trim(),
      routeKw: (p?.routeKw ?? item.route_keywords ?? keywordForRouteDrop(title)).trim(),
    };
  };

  const isRowReady = (title: string, item: UnmatchedItem) => {
    const d = rowDraft(title, item);
    return Boolean(d.market && d.route && d.routeKw);
  };

  const routesByMarket = useMemo(() => {
    const map = new Map<string, RouteRule[]>();
    for (const r of routeRules ?? []) {
      const list = map.get(r.thi_truong) ?? [];
      list.push(r);
      map.set(r.thi_truong, list);
    }
    return map;
  }, [routeRules]);

  const routeNamesByMarket = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const [mk, rules] of routesByMarket) {
      map.set(mk, uniqueRouteNames(rules));
    }
    return map;
  }, [routesByMarket]);

  const orderedMarkets = useMemo(() => {
    const saved = marketOrderData?.markets ?? [];
    const keys = [...routesByMarket.keys()];
    const out: string[] = [];
    const seen = new Set<string>();
    for (const mk of saved) {
      if (!keys.includes(mk) || seen.has(mk)) continue;
      if (!marketVisibleInRulesSearch(searchQuery, mk, routesByMarket.get(mk) ?? [])) continue;
      out.push(mk);
      seen.add(mk);
    }
    for (const mk of keys.sort((a, b) => a.localeCompare(b, "vi"))) {
      if (seen.has(mk)) continue;
      if (!marketVisibleInRulesSearch(searchQuery, mk, routesByMarket.get(mk) ?? [])) continue;
      out.push(mk);
    }
    return out;
  }, [marketOrderData, routesByMarket, searchQuery]);

  useEffect(() => {
    if (!searchQuery.trim()) return;
    setExpanded(new Set(orderedMarkets));
  }, [searchQuery, orderedMarkets]);

  const toggleMarket = (mk: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(mk)) next.delete(mk);
      else next.add(mk);
      return next;
    });
  };

  const saveMarketOrder = async (order: string[]) => {
    await putClassifyMarketOrder(order);
    await refetchMarketOrder();
    onAfterSaved("Đã lưu thứ tự thị trường — trên xuống = ưu tiên khi khớp tour");
  };

  const onDropMarket = (targetMk: string) => {
    if (!dragMarket || dragMarket === targetMk) return;
    const order = [...orderedMarkets];
    const from = order.indexOf(dragMarket);
    const to = order.indexOf(targetMk);
    if (from < 0 || to < 0) return;
    order.splice(from, 1);
    order.splice(to, 0, dragMarket);
    setDragMarket(null);
    setDropMarket(null);
    saveMarketOrder(order).catch(onError);
  };

  const deleteMarketGroup = async (mk: string) => {
    const rRules = routesByMarket.get(mk) ?? [];
    if (!rRules.length) return;
    if (!window.confirm(`Xóa toàn bộ ${rRules.length} dòng rule tuyến của «${mk}»?`)) return;
    await Promise.all(rRules.map((r) => deleteRouteRule(r.id)));
    onAfterSaved(`Đã xóa nhóm ${mk}`);
  };

  const assignOne = async (title: string, item: UnmatchedItem) => {
    const d = rowDraft(title, item);
    if (!d.market || !d.route || !d.routeKw) return;
    onMarkGapsHandled([title]);
    setAssigningRows((prev) => new Set(prev).add(title));
    setActionFeedback({ kind: "loading", text: `Đang gán «${d.routeKw}» → ${d.route}…` });
    try {
      const r = await assignClassification({
        thi_truong: d.market,
        tuyen_tour: d.route,
        route_keywords: d.routeKw,
      });
      setSelectedGaps((prev) => {
        const n = new Set(prev);
        n.delete(title);
        return n;
      });
      setPending((prev) => {
        const n = { ...prev };
        delete n[title];
        return n;
      });
      const msg = applyResultMessage(r, `Đã gán ${d.route} (${d.market})`);
      setActionFeedback({ kind: "ok", text: msg });
      onAfterSaved(msg, { gapValues: [title], skipPoll: true });
    } catch (e) {
      onGapAssignFailed([title]);
      setActionFeedback({ kind: "err", text: "Gán thất bại — xem thông báo phía trên." });
      throw e;
    } finally {
      setAssigningRows((prev) => { const n = new Set(prev); n.delete(title); return n; });
    }
  };

  const assignSelected = async () => {
    const titles = [...selectedGaps].filter((t) => {
      const item = gapItems.find((x) => x.value === t);
      return item && isRowReady(t, item);
    });
    if (!titles.length) return;
    const items = titles.map((title) => {
      const item = gapItems.find((x) => x.value === title)!;
      const d = rowDraft(title, item);
      return { thi_truong: d.market, tuyen_tour: d.route, route_keywords: d.routeKw };
    });
    onMarkGapsHandled(titles);
    setAssigning(true);
    setActionFeedback({ kind: "loading", text: `Đang gán ${titles.length} dòng…` });
    try {
      const r = await assignClassificationBulk({ items });
      setSelectedGaps((prev) => {
        const n = new Set(prev);
        for (const t of titles) n.delete(t);
        return n;
      });
      setPending((prev) => {
        const n = { ...prev };
        for (const t of titles) delete n[t];
        return n;
      });
      const msg = r.message || `Đã gán ${titles.length} dòng`;
      setActionFeedback({ kind: "ok", text: msg });
      onAfterSaved(msg, { gapValues: titles, skipPoll: true });
    } catch (e) {
      onGapAssignFailed(titles);
      setActionFeedback({ kind: "err", text: "Gán hàng loạt thất bại." });
      throw e;
    } finally {
      setAssigning(false);
    }
  };

  const toggleGapSelect = (title: string) => {
    setSelectedGaps((prev) => {
      const n = new Set(prev);
      if (n.has(title)) n.delete(title);
      else n.add(title);
      return n;
    });
  };

  const selectAllReadyGaps = () => {
    setSelectedGaps(new Set(gapItems.filter((item) => isRowReady(item.value, item)).map((i) => i.value)));
  };

  const quickAdd = async () => {
    const mk = qMarket.trim();
    const route = (qRoute || qMarket).trim();
    const kw = qRouteKw.trim();
    if (!mk || !route || !kw) return;
    setQuickAdding(true);
    setActionFeedback({
      kind: "loading",
      text: `Đang thêm rule «${kw}» → ${route} và áp dụng lên tour (có thể mất vài giây)…`,
    });
    try {
      const r = await assignClassification({
        thi_truong: mk,
        tuyen_tour: route,
        route_keywords: kw,
      });
      setQRouteKw("");
      const msg = applyResultMessage(r, `Đã thêm tuyến ${route} (${mk})`);
      setActionFeedback({ kind: "ok", text: msg });
      onAfterSaved(msg, { skipPoll: true });
    } catch (e) {
      setActionFeedback({ kind: "err", text: "Thêm & áp dụng thất bại." });
      onError(e);
    } finally {
      setQuickAdding(false);
    }
  };

  const selectedReadyCount = useMemo(
    () => [...selectedGaps].filter((t) => {
      const item = gapItems.find((x) => x.value === t);
      return item && isRowReady(t, item);
    }).length,
    [selectedGaps, gapItems, pending],
  );

  // ── datalists dùng chung cho cả 2 cột ──────────────────────────────────────
  const sharedDataLists = (
    <>
      <datalist id="classify-market-list">{marketOptions.map((m) => <option key={m} value={m} />)}</datalist>
      {[...routeNamesByMarket.entries()].map(([mk, names]) => (
        <datalist key={mk} id={routeDatalistId(mk)}>
          {names.map((name) => <option key={name} value={name} />)}
        </datalist>
      ))}
    </>
  );

  return (
    <div className="grid lg:grid-cols-[3fr_2fr] gap-4 items-start">

      {/* ══════ LEFT — Thêm rule + Preview + Bảng rules hiện có ══════════════ */}
      <div className="space-y-3">

        {/* 1. Quick-add form — việc đầu tiên khi muốn tạo rule mới */}
        <div className="card p-4 space-y-3 bg-primary-50/40 border-primary-100">
          <p className="text-sm font-medium text-primary-900">
            Thêm rule tuyến mới
            <InfoTip text="Mỗi dòng = một điều kiện (OR). Trong dòng: dấu phẩy = AND. Thị trường chỉ là nhóm lưu trữ, không cần keyword TT." />
          </p>
          <div className="space-y-2">
            <input className="input text-sm w-full" placeholder="Thị trường (nhóm)" value={qMarket} onChange={(e) => setQMarket(e.target.value)} onKeyDown={keepInputKeys} list="classify-market-list" />
            <input className="input text-sm w-full" placeholder="Tên tuyến tour" value={qRoute} onChange={(e) => setQRoute(e.target.value)} onKeyDown={keepInputKeys} list={qMarket.trim() ? routeDatalistId(qMarket.trim()) : undefined} />
            <input className="input text-sm font-mono w-full" placeholder="Keyword tuyến (vd: kanazawa, osaka)" value={qRouteKw} onChange={(e) => setQRouteKw(e.target.value)} onKeyDown={keepInputKeys} />
          </div>
          <div className="flex flex-wrap gap-2 items-center">
            <button type="button" onClick={() => void quickAdd()} disabled={!qMarket.trim() || !qRouteKw.trim() || quickAdding || assigning} className="btn-primary text-sm disabled:opacity-60">
              <Plus size={14} className={quickAdding ? "animate-pulse" : ""} />
              {quickAdding ? "Đang áp dụng…" : "Thêm & áp dụng"}
            </button>
            <button type="button" onClick={() => seedRouteDefaults().then((r) => onAfterSaved(r.message || "Đã import tuyến")).catch(onError)} className="btn-secondary text-sm">
              <Database size={14} /> Import mặc định
            </button>
          </div>
          {actionFeedback && (
            <p className={cn("text-sm px-3 py-2 rounded-lg border",
              actionFeedback.kind === "loading" && "text-amber-900 bg-amber-50 border-amber-200",
              actionFeedback.kind === "ok" && "text-green-800 bg-green-50 border-green-200",
              actionFeedback.kind === "err" && "text-red-800 bg-red-50 border-red-200",
            )} role="status">{actionFeedback.text}</p>
          )}
        </div>

        {/* 2. Preview keyword — test ngay sau khi nhập keyword */}
        <div className="card p-4 border-dashed border-2 border-blue-200 bg-blue-50/40">
          <p className="text-sm font-medium text-blue-900 mb-2 flex items-center gap-2">
            <Search size={14} /> Test keyword trước khi lưu
          </p>
          <div className="flex gap-2 items-center flex-wrap">
            <input className="input text-sm font-mono flex-1 min-w-[160px]" placeholder="bangkok, osaka — phẩy = AND"
              value={previewKw} onChange={(e) => setPreviewKw(e.target.value)} />
            {previewFetching && <span className="text-xs text-blue-600 animate-pulse">Đang tìm…</span>}
            {previewResult && !previewFetching && (
              <span className={cn("text-sm font-bold", previewResult.tour_count > 0 ? "text-blue-900" : "text-gray-500")}>
                {previewResult.tour_count} tour match
              </span>
            )}
          </div>
          {previewResult && previewResult.samples.length > 0 && (
            <div className="mt-2 max-h-32 overflow-auto space-y-1">
              {previewResult.samples.map((t) => (
                <div key={t.id} className="text-xs bg-white rounded px-2 py-1 border border-blue-100 flex items-start gap-2">
                  <span className="text-blue-700 shrink-0 font-mono">{t.thi_truong || "?"}</span>
                  <span className="flex-1 truncate text-gray-800" title={t.ten_tour}>{t.ten_tour}</span>
                  {t.tuyen_tour && <span className="text-gray-400 shrink-0 text-[10px]">{t.tuyen_tour}</span>}
                </div>
              ))}
              {previewResult.tour_count > previewResult.samples.length && (
                <p className="text-[10px] text-blue-600 px-1">…và {previewResult.tour_count - previewResult.samples.length} tour khác</p>
              )}
            </div>
          )}
          {previewResult && previewResult.tour_count === 0 && previewDebouncedKw.length >= 2 && (
            <p className="text-xs text-gray-400 mt-1">Không có tour nào chứa tất cả keyword này.</p>
          )}
        </div>

        {/* 3. Route rules table — tham chiếu rules đang có */}
        <div className="card overflow-auto" style={{ maxHeight: "calc(100vh - 260px)" }}>
          <p className="px-3 py-2 text-xs font-semibold text-gray-600 bg-gray-50 sticky top-0 z-10 border-b flex items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1">
              Quy tắc theo thị trường
              <InfoTip text="Kéo ⋮⋮ để đổi thứ tự TT. Trong nhóm: dòng nhiều «và» hơn được ưu tiên trước." />
            </span>
            {searchQuery.trim() && (
              <span className="font-normal text-gray-500">{orderedMarkets.length} nhóm khớp</span>
            )}
          </p>
          <div className="text-sm">
            {orderedMarkets.length === 0 && searchQuery.trim() && (
              <p className="p-4 text-sm text-gray-500">Không có rule khớp «{searchQuery.trim()}»</p>
            )}
            {orderedMarkets.map((mk, idx) => {
              const rRulesAll = routesByMarket.get(mk) ?? [];
              const showAll = matchRulesSearch(searchQuery, mk);
              const filtered = showAll || !searchQuery.trim()
                ? rRulesAll
                : rRulesAll.filter((r) => matchRulesSearch(searchQuery, r.tuyen_tour, r.keywords));
              const rRules = sortRouteRulesForDisplay(filtered);
              if (!rRules.length) return null;
              const open = expanded.has(mk);
              const dragging = dragMarket === mk;
              const dropHint = dropMarket === mk && dragMarket && dragMarket !== mk;
              return (
                <div
                  key={mk}
                  className={cn(
                    "border-b border-gray-100",
                    dragging && "opacity-40",
                    dropHint && "bg-primary-50 ring-1 ring-inset ring-primary-200",
                  )}
                  onDragOver={(e) => { e.preventDefault(); setDropMarket(mk); }}
                  onDragLeave={() => setDropMarket((d) => (d === mk ? null : d))}
                  onDrop={(e) => { e.preventDefault(); onDropMarket(mk); }}
                >
                  <div className="flex items-center gap-1 px-2 py-2 bg-gray-50/80">
                    <span
                      draggable
                      onDragStart={() => setDragMarket(mk)}
                      onDragEnd={() => { setDragMarket(null); setDropMarket(null); }}
                      className="cursor-grab text-gray-400 hover:text-gray-600 shrink-0 touch-none"
                      title="Kéo để đổi thứ tự thị trường"
                    >
                      <GripVertical size={14} />
                    </span>
                    <button
                      type="button"
                      className="flex-1 flex items-center gap-1 text-left font-medium text-gray-900 min-w-0"
                      onClick={() => toggleMarket(mk)}
                    >
                      {open ? <ChevronDown size={14} className="shrink-0" /> : <ChevronRight size={14} className="shrink-0" />}
                      <span className="truncate">{idx + 1}. {mk}</span>
                      <span className="text-gray-400 font-normal text-xs shrink-0">({rRules.length} dòng)</span>
                    </button>
                    <button
                      type="button"
                      className="text-red-500 hover:text-red-700 shrink-0 p-1"
                      title="Xóa nhóm"
                      onClick={() => deleteMarketGroup(mk).catch(onError)}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                  {open && (
                    <div className="px-3 pb-3">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-gray-500">
                            <th className="text-left py-1 w-6">#</th>
                            <th className="py-1 w-5" title="Ưu tiên — kiểm tra trước tất cả rule khác"><Star size={9} className="text-amber-400" /></th>
                            <th className="text-left py-1">Tuyến</th>
                            <th className="text-left">Keywords (AND)</th>
                            <th className="text-right pr-1 w-14">
                              <span className="inline-flex items-center gap-0.5 text-gray-400" title="Số tour đang dùng rule này">
                                <Users size={9} /> Tour
                              </span>
                            </th>
                            <th className="w-20" />
                          </tr>
                        </thead>
                        <tbody>
                          {rRules.map((r, ri) => {
                            const dropKey = `route-${r.id}`;
                            const kwCount = parseRouteKeywordList(r.keywords).length;
                            const { dropClassName, ...drop } = dropHandlers(dropKey, dropTarget, setDropTarget, (raw) =>
                              appendKeywordToRouteRule(r, raw),
                            );
                            // Backend route-stats chỉ trả những rule có >=1 tour (filter WHERE
                            // classification_rule_id IS NOT NULL + GROUP BY). Rule chưa khớp tour
                            // nào sẽ KHÔNG xuất hiện trong dict → trước đây hiện "—" (giống loading).
                            // Phân biệt: routeStats undefined = đang load, có data + key missing = 0.
                            const tourCount = routeStats?.[String(r.id)] ?? (routeStats ? 0 : undefined);
                            const isEditing = editingRuleId === r.id;
                            const isPriorityToggling = togglingPriorityId === r.id;
                            return (
                              <tr key={r.id} className={cn("border-t border-gray-100", r.priority && "bg-amber-50/60")}>
                                <td className="py-1 text-gray-400 text-[10px]">{ri + 1}</td>
                                {/* ★ priority toggle */}
                                <td className="py-1">
                                  <button
                                    type="button"
                                    title={r.priority ? "Đang ưu tiên — bấm để tắt" : "Bật ưu tiên (kiểm tra trước tất cả)"}
                                    disabled={isPriorityToggling}
                                    onClick={() => handleTogglePriority(r)}
                                    className={cn(
                                      "p-0.5 rounded transition-colors",
                                      r.priority ? "text-amber-500 hover:text-amber-700" : "text-gray-200 hover:text-amber-400",
                                      isPriorityToggling && "opacity-40 cursor-not-allowed"
                                    )}
                                  >
                                    <Star size={11} fill={r.priority ? "currentColor" : "none"} />
                                  </button>
                                </td>
                                <td className={cn("py-1 pr-2", dropClassName)} {...drop}>
                                  {r.tuyen_tour}
                                  {r.priority && <span className="ml-1 text-[9px] text-amber-600 font-semibold">ưu tiên</span>}
                                </td>
                                {/* Keywords — inline edit khi click ✏️ */}
                                <td className="py-1 font-mono">
                                  {isEditing ? (
                                    <input
                                      autoFocus
                                      className="input text-xs font-mono w-full py-0.5 px-1"
                                      value={editDraft}
                                      onChange={(e) => setEditDraft(e.target.value)}
                                      onKeyDown={(e) => {
                                        e.stopPropagation();
                                        if (e.key === "Enter") saveEdit(r).catch(onError);
                                        if (e.key === "Escape") cancelEdit();
                                      }}
                                      placeholder="keyword1, keyword2 (AND)"
                                    />
                                  ) : (
                                    <>
                                      <RouteKeywordsCell keywords={r.keywords} conflicts={routeKeywordConflicts} />
                                      {kwCount > 1 && (
                                        <span className="text-[10px] text-gray-500 font-sans ml-1">({kwCount} AND)</span>
                                      )}
                                    </>
                                  )}
                                </td>
                                <td className="py-1 text-right pr-1">
                                  {tourCount != null ? (
                                    <span className={cn("text-[10px] font-medium", tourCount > 0 ? "text-primary-700" : "text-gray-300")}>
                                      {tourCount}
                                    </span>
                                  ) : <span className="text-gray-200 text-[10px]">—</span>}
                                </td>
                                {/* Actions: edit / save / cancel / delete */}
                                <td className="py-1">
                                  {isEditing ? (
                                    <span className="flex gap-1 items-center">
                                      <button type="button" disabled={savingEdit}
                                        className="text-green-600 hover:text-green-800 p-0.5 disabled:opacity-40"
                                        title="Lưu" onClick={() => saveEdit(r).catch(onError)}>
                                        <Check size={13} />
                                      </button>
                                      <button type="button" className="text-gray-400 hover:text-gray-600 p-0.5"
                                        title="Hủy" onClick={cancelEdit}>
                                        <X size={13} />
                                      </button>
                                    </span>
                                  ) : confirmDeleteId === r.id ? (
                                    <span className="flex gap-1 items-center">
                                      <button type="button" className="text-[9px] bg-red-600 text-white px-1 py-0.5 rounded"
                                        onClick={() => { setConfirmDeleteId(null); deleteRouteRule(r.id).then(() => onAfterSaved("Đã xóa")); }}>Xóa</button>
                                      <button type="button" className="text-[9px] bg-gray-100 px-1 py-0.5 rounded"
                                        onClick={() => setConfirmDeleteId(null)}>Hủy</button>
                                    </span>
                                  ) : (
                                    <span className="flex gap-0.5 items-center">
                                      <button type="button" className="text-gray-400 hover:text-blue-600 p-0.5"
                                        title="Sửa keywords" onClick={() => startEdit(r)}>
                                        <Pencil size={12} />
                                      </button>
                                      <button type="button" className="text-red-400 hover:text-red-600 p-0.5"
                                        title="Xóa rule" onClick={() => setConfirmDeleteId(r.id)}>
                                        <Trash2 size={12} />
                                      </button>
                                    </span>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      {/* ════ END LEFT ════ */}

      {/* ══════ RIGHT — Giải quyết Tour Chưa Khớp ══════════════════════════ */}
      <div className="space-y-3">

        {/* Ghi chú ưu tiên + conflict (nhỏ gọn, không chiếm nhiều chỗ) */}
        <div className="text-xs text-slate-600 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 leading-relaxed">
          Ưu tiên: <strong>thị trường trên xuống</strong> → nhiều từ AND hơn ưu tiên → cùng tuyến = OR.
          {routeKeywordConflicts.size > 0 && (
            <span className="ml-1 text-red-700 font-medium">⚠ {routeKeywordConflicts.size} keyword trùng tuyến</span>
          )}
        </div>

        {/* Unmatched gaps — chiếm toàn bộ chiều cao còn lại */}
        <div className="card overflow-auto" style={{ maxHeight: "calc(100vh - 200px)" }}>
          <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b bg-amber-50/80 sticky top-0 z-20">
            <span className="text-xs font-semibold text-amber-900">
              Chưa khớp tuyến {gapItems.length > 0 && `(${gapItems.length})`}
            </span>
            <button type="button" className="btn-secondary text-xs py-0.5 ml-auto" disabled={gapLoading || !gapItems.length} onClick={selectAllReadyGaps}>
              Chọn tất cả
            </button>
            <button type="button" className="btn-secondary text-xs py-0.5" disabled={!selectedGaps.size} onClick={() => setSelectedGaps(new Set())}>
              Bỏ chọn
            </button>
            <button type="button" className="btn-primary text-xs py-0.5" disabled={assigning || selectedReadyCount < 1} onClick={() => assignSelected().catch(onError)}>
              {assigning ? "Đang gán…" : `Gán ${selectedReadyCount} dòng`}
            </button>
          </div>
          <table className="w-full text-xs">
            <thead className="bg-amber-50 sticky top-[41px] z-10">
              <tr>
                <th className="px-1 py-2 w-7" />
                <th className="px-2 py-2 text-left">Tour chưa khớp</th>
                <th className="px-2 py-2 text-left">TT · Tuyến · Keyword</th>
                <th className="px-2 py-2 w-14" />
              </tr>
            </thead>
            <tbody>
              {gapLoading && (
                <tr><td colSpan={4} className="px-3 py-6 text-center text-gray-400">Đang tải…</td></tr>
              )}
              {!gapLoading && gapItems.length === 0 && (
                <tr><td colSpan={4} className="px-3 py-6 text-center text-green-700">Tất cả tour đã có tuyến</td></tr>
              )}
              {gapItems.map((item) => {
                const title = item.value;
                const d = rowDraft(title, item);
                const rowConflict = conflictHintForKeyword(parseRouteKeywordList(d.routeKw)[0] ?? "", routeKeywordConflicts);
                const ready = isRowReady(title, item);
                return (
                  <tr key={title} className={cn("border-t bg-amber-50/40 align-top", selectedGaps.has(title) && "ring-1 ring-primary-400")}>
                    <td className="px-1 py-2 text-center">
                      <input type="checkbox" className="rounded" checked={selectedGaps.has(title)} disabled={!ready || assigning || assigningRows.has(title)}
                        title={ready ? "Chọn để gán hàng loạt" : "Điền đủ thị trường, tuyến, keyword"}
                        onChange={() => toggleGapSelect(title)} />
                    </td>
                    <td className="px-2 py-2 text-xs max-w-[120px]">
                      {item.count > 1 && <span className="text-gray-500 block mb-0.5">{item.count} tour</span>}
                      <span className="line-clamp-3" title={item.sample}>{item.sample || title}</span>
                      <UnmatchedMembers members={item.members} itemKey={title} />
                    </td>
                    <td className="px-2 py-2 space-y-1">
                      <input className="input text-xs py-1 w-full" list="classify-market-list" placeholder="Nhóm TT"
                        value={d.market} onKeyDown={keepInputKeys}
                        onChange={(e) => setPending((prev) => ({ ...prev, [title]: { market: e.target.value, route: d.route, routeKw: d.routeKw } }))} />
                      <input className="input text-xs py-1 w-full" list={d.market.trim() ? routeDatalistId(d.market.trim()) : undefined} placeholder="Tên tuyến"
                        value={d.route} onKeyDown={keepInputKeys}
                        onChange={(e) => setPending((prev) => ({ ...prev, [title]: { market: d.market, route: e.target.value, routeKw: d.routeKw } }))} />
                      <input className="input text-xs py-1 w-full font-mono" placeholder="keyword"
                        value={d.routeKw} onKeyDown={keepInputKeys}
                        onChange={(e) => setPending((prev) => ({ ...prev, [title]: { market: d.market, route: d.route, routeKw: e.target.value } }))} />
                      {rowConflict && <p className="text-[10px] text-red-700">{rowConflict}</p>}
                      <span {...dragAliasProps(d.routeKw)} className="text-[10px] text-amber-700 cursor-grab inline-flex items-center gap-0.5">
                        <GripVertical size={10} /> kéo keyword
                      </span>
                    </td>
                    <td className="px-2 py-2">
                      <button type="button" className="btn-primary text-[10px] py-1 px-2 w-full disabled:opacity-60"
                        disabled={!ready || assigningRows.has(title)}
                        onClick={() => assignOne(title, item).catch(onError)}>
                        {assigningRows.has(title)
                          ? <RefreshCw size={10} className="animate-spin mx-auto" />
                          : "Gán"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {sharedDataLists}
          <p className="text-xs text-gray-400 p-3">
            {gapLoading ? "Đang tải…" : `${gapItems.length} tên tour chưa có tuyến trong DB`}
          </p>
        </div>

      </div>
      {/* ════ END RIGHT ════ */}

    </div>
  );
}
