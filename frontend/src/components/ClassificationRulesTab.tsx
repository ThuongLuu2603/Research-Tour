import { useMemo, useState } from "react";
import type { RouteRule, UnmatchedItem } from "@/lib/api";
import { assignClassification, seedRouteDefaults } from "@/lib/api";
import { buildRouteKeywordConflicts, conflictHintForKeyword, parseRouteKeywordList } from "@/lib/rulesUnmatched";
import { InfoTip } from "@/components/InfoTip";
import { cn } from "@/lib/utils";
import { Database, GripVertical, Plus, Trash2 } from "lucide-react";
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

  const rulesByMarket = useMemo(
    () =>
      [...routesByMarket.keys()]
        .filter((mk) => marketVisibleInRulesSearch(searchQuery, mk, routesByMarket.get(mk) ?? []))
        .sort((a, b) => a.localeCompare(b, "vi")),
    [routesByMarket, searchQuery],
  );

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
        <strong>Route-first:</strong> chỉ cần rule <strong>tuyến</strong> (keyword trong tên tour).
        Thị trường = cột «Thị trường» trên mỗi dòng rule — tour khớp tuyến sẽ được gán cả TT + tuyến.
        Tour placeholder FIT tự loại khỏi thống kê.
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
          {routeKeywordConflicts.size} từ keyword trùng nhiều tuyến — rule sort_order nhỏ hơn được ưu tiên.
        </p>
      )}

      <div className="card overflow-auto max-h-[320px]">
        <p className="px-3 py-2 text-xs font-semibold text-gray-600 bg-gray-50 sticky top-0 z-10 border-b flex items-center justify-between gap-2">
          <span>Quy tắc theo thị trường (từ rule tuyến)</span>
          {searchQuery.trim() && (
            <span className="font-normal text-gray-500">{rulesByMarket.length} nhóm khớp</span>
          )}
        </p>
        <div className="divide-y text-sm">
          {rulesByMarket.length === 0 && searchQuery.trim() && (
            <p className="p-4 text-sm text-gray-500">Không có rule khớp «{searchQuery.trim()}»</p>
          )}
          {rulesByMarket.map((mk) => {
            const rRulesAll = routesByMarket.get(mk) ?? [];
            const showAll = matchRulesSearch(searchQuery, mk);
            const rRules = showAll || !searchQuery.trim()
              ? rRulesAll
              : rRulesAll.filter((r) => matchRulesSearch(searchQuery, r.tuyen_tour, r.keywords));
            if (!rRules.length) return null;
            return (
              <div key={mk} className="p-3">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="font-medium text-gray-900">{mk}</div>
                  <button
                    type="button"
                    className="text-red-500 hover:text-red-700 shrink-0 inline-flex items-center gap-0.5 text-[10px]"
                    onClick={() => deleteMarketGroup(mk).catch(onError)}
                  >
                    <Trash2 size={12} /> Xóa nhóm
                  </button>
                </div>
                <table className="w-full text-xs">
                  <thead><tr className="text-gray-500"><th className="text-left py-1">Tuyến</th><th className="text-left">Keywords (AND trong dòng)</th><th /></tr></thead>
                  <tbody>
                    {rRules.map((r) => {
                      const dropKey = `route-${r.id}`;
                      const { dropClassName, ...drop } = dropHandlers(dropKey, dropTarget, setDropTarget, (raw) =>
                        appendKeywordToRouteRule(r, raw),
                      );
                      return (
                        <tr key={r.id} className="border-t">
                          <td className={cn("py-1 pr-2", dropClassName)} {...drop}>{r.tuyen_tour}</td>
                          <td className="py-1 font-mono"><RouteKeywordsCell keywords={r.keywords} conflicts={routeKeywordConflicts} /></td>
                          <td className="py-1">{actionBtns(() => deleteRouteRule(r.id).then(() => onAfterSaved("Đã xóa")))}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
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
