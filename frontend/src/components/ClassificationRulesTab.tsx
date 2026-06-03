import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { RouteRule, UnmatchedItem } from "@/lib/api";
import { assignClassification, getClassifyMarketOrder, putClassifyMarketOrder, seedRouteDefaults } from "@/lib/api";
import { buildRouteKeywordConflicts, conflictHintForKeyword, parseRouteKeywordList } from "@/lib/rulesUnmatched";
import { InfoTip } from "@/components/InfoTip";
import { cn } from "@/lib/utils";
import { ChevronDown, ChevronRight, Database, GripVertical, Plus, Trash2 } from "lucide-react";
import {
  dropHandlers,
  dragAliasProps,
  keywordForRouteDrop,
  marketVisibleInRulesSearch,
  matchRulesSearch,
  RouteKeywordsCell,
} from "@/lib/rulesAdminUi";

type Props = {
  routeRules: RouteRule[] | undefined;
  searchQuery: string;
  gapItems: UnmatchedItem[];
  gapLoading: boolean;
  marketOptions: string[];
  routeKeywordConflicts: ReturnType<typeof buildRouteKeywordConflicts>;
  dropTarget: string | null;
  setDropTarget: (k: string | null) => void;
  onAfterSaved: (msg: string) => void;
  onError: (e: unknown) => void;
  appendKeywordToRouteRule: (rule: RouteRule, raw: string) => Promise<void>;
  deleteRouteRule: (id: number) => Promise<void>;
  actionBtns: (onDelete: () => void, onSave?: () => void) => React.ReactNode;
};

function sortRouteRulesForDisplay(rules: RouteRule[]): RouteRule[] {
  return [...rules].sort((a, b) => {
    const na = parseRouteKeywordList(a.keywords).length;
    const nb = parseRouteKeywordList(b.keywords).length;
    if (nb !== na) return nb - na;
    return a.sort_order - b.sort_order || a.id - b.id;
  });
}

export function ClassificationRulesTab({
  routeRules,
  searchQuery,
  gapItems,
  gapLoading,
  marketOptions,
  routeKeywordConflicts,
  dropTarget,
  setDropTarget,
  onAfterSaved,
  onError,
  appendKeywordToRouteRule,
  deleteRouteRule,
  actionBtns,
}: Props) {
  const [qMarket, setQMarket] = useState("");
  const [qRoute, setQRoute] = useState("");
  const [qRouteKw, setQRouteKw] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [dragMarket, setDragMarket] = useState<string | null>(null);
  const [dropMarket, setDropMarket] = useState<string | null>(null);

  const { data: marketOrderData, refetch: refetchMarketOrder } = useQuery({
    queryKey: ["classify-market-order"],
    queryFn: getClassifyMarketOrder,
  });

  const [pending, setPending] = useState<Record<string, {
    market: string;
    route: string;
    routeKw: string;
  }>>({});

  const routesByMarket = useMemo(() => {
    const map = new Map<string, RouteRule[]>();
    for (const r of routeRules ?? []) {
      const list = map.get(r.thi_truong) ?? [];
      list.push(r);
      map.set(r.thi_truong, list);
    }
    return map;
  }, [routeRules]);

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
    const p = pending[title] ?? {
      market: item.suggested_market || item.resolved_market || "",
      route: item.suggested_route || item.suggested_market || "",
      routeKw: item.route_keywords || keywordForRouteDrop(title),
    };
    const mk = p.market.trim();
    const route = p.route.trim();
    const routeKw = p.routeKw.trim();
    if (!mk || !route || !routeKw) return;
    await assignClassification({
      thi_truong: mk,
      tuyen_tour: route,
      route_keywords: routeKw,
    });
    onAfterSaved(`Đã gán ${route} → ${mk}`);
    setPending((prev) => {
      const n = { ...prev };
      delete n[title];
      return n;
    });
  };

  const quickAdd = async () => {
    const mk = qMarket.trim();
    const route = (qRoute || qMarket).trim();
    if (!mk || !route || !qRouteKw.trim()) return;
    await assignClassification({
      thi_truong: mk,
      tuyen_tour: route,
      route_keywords: qRouteKw.trim(),
    });
    setQRouteKw("");
    onAfterSaved(`Đã thêm tuyến ${route} (${mk})`);
  };

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-600 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
        <strong>Ưu tiên khớp:</strong> (1) thị trường <strong>trên xuống</strong> — kéo thả để sắp xếp;
        (2) trong mỗi TT, dòng có <strong>nhiều từ AND</strong> hơn được thử trước;
        (3) cùng tuyến, nhiều dòng = OR. Bấm tên TT để mở/đóng danh sách tuyến.
      </p>

      <div className="card p-4 space-y-3 bg-primary-50/40 border-primary-100">
        <p className="text-sm font-medium text-primary-900">
          Thêm rule tuyến
          <InfoTip text="Mỗi dòng = một điều kiện (OR). Trong dòng: dấu phẩy = AND. Thị trường chỉ là nhóm lưu trữ, không cần keyword TT." />
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <input className="input text-sm" placeholder="Thị trường (nhóm)" value={qMarket} onChange={(e) => setQMarket(e.target.value)} list="classify-market-list" />
          <input className="input text-sm" placeholder="Tên tuyến tour" value={qRoute} onChange={(e) => setQRoute(e.target.value)} />
          <input className="input text-sm font-mono" placeholder="Keyword tuyến (vd: kanazawa)" value={qRouteKw} onChange={(e) => setQRouteKw(e.target.value)} />
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={quickAdd} disabled={!qMarket.trim() || !qRouteKw.trim()} className="btn-primary text-sm">
            <Plus size={14} /> Thêm & áp dụng
          </button>
          <button type="button" onClick={() => seedRouteDefaults().then((r) => onAfterSaved(r.message || "Đã import tuyến")).catch(onError)} className="btn-secondary text-sm">
            <Database size={14} /> Import tuyến mặc định
          </button>
        </div>
      </div>

      {routeKeywordConflicts.size > 0 && (
        <p className="text-sm text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {routeKeywordConflicts.size} từ keyword trùng nhiều tuyến (đỏ) — cùng mức ưu tiên thì sort_order nhỏ hơn thắng.
        </p>
      )}

      <div className="card overflow-auto max-h-[420px]">
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
                          <th className="text-left py-1 w-8">#</th>
                          <th className="text-left py-1">Tuyến</th>
                          <th className="text-left">Keywords (AND — nhiều từ ưu tiên trước)</th>
                          <th className="w-10" />
                        </tr>
                      </thead>
                      <tbody>
                        {rRules.map((r, ri) => {
                          const dropKey = `route-${r.id}`;
                          const kwCount = parseRouteKeywordList(r.keywords).length;
                          const { dropClassName, ...drop } = dropHandlers(dropKey, dropTarget, setDropTarget, (raw) =>
                            appendKeywordToRouteRule(r, raw),
                          );
                          return (
                            <tr key={r.id} className="border-t border-gray-100">
                              <td className="py-1 text-gray-400">{ri + 1}</td>
                              <td className={cn("py-1 pr-2", dropClassName)} {...drop}>{r.tuyen_tour}</td>
                              <td className="py-1 font-mono">
                                <RouteKeywordsCell keywords={r.keywords} conflicts={routeKeywordConflicts} />
                                {kwCount > 1 && (
                                  <span className="text-[10px] text-gray-500 font-sans ml-1">({kwCount} AND)</span>
                                )}
                              </td>
                              <td className="py-1">{actionBtns(() => deleteRouteRule(r.id).then(() => onAfterSaved("Đã xóa")))}</td>
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

      <div className="card overflow-auto max-h-[480px]">
        <table className="w-full text-sm">
          <thead className="bg-amber-50 sticky top-0 z-10">
            <tr>
              <th className="px-2 py-2 text-left w-[30%]">Tour chưa khớp tuyến</th>
              <th className="px-2 py-2 text-left">Thị trường (nhóm)</th>
              <th className="px-2 py-2 text-left">Tuyến tour</th>
              <th className="px-2 py-2 text-left">
                <span className="inline-flex items-center gap-1">
                  Keyword tuyến (dòng mới)
                  <InfoTip text="Gán = thêm dòng OR. Dấu phẩy = AND. TT lấy từ ô Thị trường." />
                </span>
              </th>
              <th className="px-2 py-2 w-20" />
            </tr>
          </thead>
          <tbody>
            {gapLoading && (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-400">Đang quét tour…</td></tr>
            )}
            {!gapLoading && gapItems.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-green-700">Mọi tour đã khớp ít nhất một rule tuyến</td></tr>
            )}
            {gapItems.map((item) => {
              const title = item.value;
              const p = pending[title];
              const market = p?.market ?? item.suggested_market ?? item.resolved_market ?? "";
              const route = p?.route ?? item.suggested_route ?? "";
              const routeKw = p?.routeKw ?? item.route_keywords ?? keywordForRouteDrop(title);
              const routesForMk = routesByMarket.get(market) ?? [];
              const rowConflict = conflictHintForKeyword(parseRouteKeywordList(routeKw)[0] ?? "", routeKeywordConflicts);

              return (
                <tr key={title} className="border-t bg-amber-50/50 align-top">
                  <td className="px-2 py-2 text-xs">
                    {item.count > 1 && <span className="text-gray-500 block mb-0.5">{item.count} tour</span>}
                    <span className="line-clamp-3" title={item.sample}>{item.sample || title}</span>
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input text-xs py-1 w-full"
                      list="classify-market-list"
                      placeholder="Nhóm TT"
                      value={market}
                      onChange={(e) => setPending((prev) => ({
                        ...prev,
                        [title]: { market: e.target.value, route, routeKw },
                      }))}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input text-xs py-1 w-full"
                      list={market ? `classify-route-${encodeURIComponent(market)}` : undefined}
                      placeholder="Tên tuyến"
                      value={route}
                      onChange={(e) => setPending((prev) => ({
                        ...prev,
                        [title]: { market, route: e.target.value, routeKw },
                      }))}
                    />
                    {market ? (
                      <datalist id={`classify-route-${encodeURIComponent(market)}`}>
                        {routesForMk.map((r) => (
                          <option key={r.id} value={r.tuyen_tour} />
                        ))}
                      </datalist>
                    ) : null}
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input text-xs py-1 w-full font-mono"
                      value={routeKw}
                      onChange={(e) => setPending((prev) => ({
                        ...prev,
                        [title]: { market, route, routeKw: e.target.value },
                      }))}
                    />
                    {rowConflict && <p className="text-[10px] text-red-700 mt-0.5">{rowConflict}</p>}
                    <span {...dragAliasProps(routeKw)} className="text-[10px] text-amber-700 cursor-grab inline-flex items-center gap-0.5 mt-1">
                      <GripVertical size={10} /> kéo keyword
                    </span>
                  </td>
                  <td className="px-2 py-2">
                    <button
                      type="button"
                      className="btn-primary text-[10px] py-1 px-2 w-full"
                      disabled={!market.trim() || !route.trim() || !routeKw.trim()}
                      onClick={() => assignOne(title, item).catch(onError)}
                    >
                      Gán
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <datalist id="classify-market-list">{marketOptions.map((m) => <option key={m} value={m} />)}</datalist>
        <p className="text-xs text-gray-400 p-3">
          {gapItems.length} tour chưa khớp rule tuyến
        </p>
      </div>
    </div>
  );
}
