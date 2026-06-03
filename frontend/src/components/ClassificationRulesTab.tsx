import { useMemo, useState } from "react";
import type { MarketRule, RouteRule, UnmatchedItem } from "@/lib/api";
import { assignClassification, seedMarketDefaults, seedRouteDefaults } from "@/lib/api";
import { buildRouteKeywordConflicts, conflictHintForKeyword, parseRouteKeywordList } from "@/lib/rulesUnmatched";
import { InfoTip } from "@/components/InfoTip";
import { cn } from "@/lib/utils";
import { Database, GripVertical, Plus } from "lucide-react";
import {
  dropHandlers,
  dragAliasProps,
  keywordForRouteDrop,
  marketVisibleInRulesSearch,
  matchRulesSearch,
  RouteKeywordsCell,
} from "@/lib/rulesAdminUi";

type Props = {
  marketRules: MarketRule[] | undefined;
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
  deleteMarketRule: (id: number) => Promise<void>;
  deleteRouteRule: (id: number) => Promise<void>;
  actionBtns: (onDelete: () => void, onSave?: () => void) => React.ReactNode;
};

export function ClassificationRulesTab({
  marketRules,
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
  deleteMarketRule,
  deleteRouteRule,
  actionBtns,
}: Props) {
  const [qMarket, setQMarket] = useState("");
  const [qRoute, setQRoute] = useState("");
  const [qRouteKw, setQRouteKw] = useState("");
  const [qMarketKw, setQMarketKw] = useState("");

  const [pending, setPending] = useState<Record<string, {
    market: string;
    route: string;
    routeKw: string;
    marketKw: string;
    linkMarketKw: boolean;
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

  const rulesByMarket = useMemo(() => {
    const keys = new Set<string>();
    (marketRules ?? []).forEach((r) => keys.add(r.market));
    (routeRules ?? []).forEach((r) => keys.add(r.thi_truong));
    return [...keys].sort();
  }, [marketRules, routeRules]);

  const assignOne = async (title: string, item: UnmatchedItem) => {
    const p = pending[title] ?? {
      market: item.suggested_market || item.resolved_market || "",
      route: item.suggested_route || item.suggested_market || "",
      routeKw: item.route_keywords || item.market_keyword || keywordForRouteDrop(title),
      marketKw: item.market_keyword || keywordForRouteDrop(title),
      linkMarketKw: true,
    };
    const mk = p.market.trim();
    const route = (p.route || mk).trim();
    const routeKw = p.routeKw.trim();
    const marketKw = (p.linkMarketKw ? routeKw.split(",")[0]?.trim() : p.marketKw.trim()) || routeKw.split(",")[0]?.trim();
    if (!mk || !routeKw) return;
    await assignClassification({
      thi_truong: mk,
      tuyen_tour: route,
      route_keywords: routeKw,
      market_keyword: marketKw,
    });
    onAfterSaved(`Đã gán ${mk} / ${route}`);
    setPending((prev) => {
      const n = { ...prev };
      delete n[title];
      return n;
    });
  };

  const quickAdd = async () => {
    if (!qMarket.trim() || !qRouteKw.trim()) return;
    await assignClassification({
      thi_truong: qMarket.trim(),
      tuyen_tour: (qRoute || qMarket).trim(),
      route_keywords: qRouteKw.trim(),
      market_keyword: (qMarketKw || qRouteKw.split(",")[0]).trim(),
    });
    setQRouteKw("");
    setQMarketKw("");
    onAfterSaved(`Đã thêm rule ${qMarket}`);
  };

  return (
    <div className="space-y-4">
      <div className="card p-4 space-y-3 bg-primary-50/40 border-primary-100">
        <p className="text-sm font-medium text-primary-900">
          Gán một lần — thị trường + tuyến + keyword
          <InfoTip text="Gán / Thêm = tạo thêm một dòng điều kiện tuyến (OR với các dòng khác cùng tên). Trong một dòng, dấu phẩy = tour phải có đủ các từ (AND). Kéo keyword lên bảng quy tắc phía trên = bổ sung từ vào đúng dòng đó." />
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <input className="input text-sm" placeholder="Thị trường" value={qMarket} onChange={(e) => setQMarket(e.target.value)} list="classify-market-list" />
          <input className="input text-sm" placeholder="Tuyến tour" value={qRoute} onChange={(e) => setQRoute(e.target.value)} title="Để trống = trùng tên thị trường" />
          <input className="input text-sm font-mono" placeholder="Keyword tuyến (vd: đài loan)" value={qRouteKw} onChange={(e) => setQRouteKw(e.target.value)} />
          <input className="input text-sm font-mono" placeholder="Keyword TT (tùy chọn)" value={qMarketKw} onChange={(e) => setQMarketKw(e.target.value)} title="Trống = lấy từ từ đầu keyword tuyến" />
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={quickAdd} disabled={!qMarket.trim() || !qRouteKw.trim()} className="btn-primary text-sm">
            <Plus size={14} /> Thêm & áp dụng
          </button>
          <button type="button" onClick={() => seedMarketDefaults().then(() => onAfterSaved("Đã import thị trường")).catch(onError)} className="btn-secondary text-sm">
            <Database size={14} /> Import TT
          </button>
          <button type="button" onClick={() => seedRouteDefaults().then((r) => onAfterSaved(r.message || "Đã import tuyến")).catch(onError)} className="btn-secondary text-sm">
            <Database size={14} /> Import tuyến
          </button>
        </div>
      </div>

      {routeKeywordConflicts.size > 0 && (
        <p className="text-sm text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {routeKeywordConflicts.size} từ keyword trùng nhiều tuyến (đỏ bên dưới) — rule sort_order nhỏ hơn được ưu tiên.
        </p>
      )}

      <div className="card overflow-auto max-h-[320px]">
        <p className="px-3 py-2 text-xs font-semibold text-gray-600 bg-gray-50 sticky top-0 z-10 border-b">Quy tắc theo thị trường</p>
        <div className="divide-y text-sm">
          {rulesByMarket.length === 0 && searchQuery.trim() && (
            <p className="p-4 text-sm text-gray-500">Không có quy tắc khớp «{searchQuery.trim()}»</p>
          )}
          {rulesByMarket.map((mk) => {
            const mRulesAll = (marketRules ?? []).filter((r) => r.market === mk);
            const rRulesAll = routesByMarket.get(mk) ?? [];
            const showAllRoutes = matchRulesSearch(searchQuery, mk);
            const mRules = showAllRoutes || !searchQuery.trim()
              ? mRulesAll
              : mRulesAll.filter((r) => matchRulesSearch(searchQuery, r.keyword));
            const rRules = showAllRoutes || !searchQuery.trim()
              ? rRulesAll
              : rRulesAll.filter((r) => matchRulesSearch(searchQuery, r.tuyen_tour, r.keywords));
            return (
              <div key={mk} className="p-3">
                <div className="font-medium text-gray-900 mb-1">{mk}</div>
                <div className="text-xs text-gray-600 mb-2">
                  Thị trường: {mRules.length ? mRules.map((r) => r.keyword).join(", ") : "—"}
                </div>
                <table className="w-full text-xs">
                  <thead><tr className="text-gray-500"><th className="text-left py-1">Tuyến</th><th className="text-left">Keywords</th><th /></tr></thead>
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
              <th className="px-2 py-2 text-left w-[28%]">Tour / trạng thái</th>
              <th className="px-2 py-2 text-left">Thị trường</th>
              <th className="px-2 py-2 text-left">Tuyến</th>
              <th className="px-2 py-2 text-left">
                <span className="inline-flex items-center gap-1">
                  Điều kiện tuyến (dòng mới)
                  <InfoTip text="Mỗi tour vàng: Gán = thêm một dòng rule (OR). Trong ô: dấu phẩy = AND trong cùng dòng." />
                </span>
              </th>
              <th className="px-2 py-2 w-24" />
            </tr>
          </thead>
          <tbody>
            {gapLoading && (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-400">Đang quét tour…</td></tr>
            )}
            {!gapLoading && gapItems.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-green-700">Không còn tour thiếu thị trường/tuyến</td></tr>
            )}
            {gapItems.map((item) => {
              const title = item.value;
              const p = pending[title];
              const market = p?.market ?? item.suggested_market ?? item.resolved_market ?? "";
              const route = p?.route ?? item.suggested_route ?? market;
              const routeKw = p?.routeKw ?? item.route_keywords ?? keywordForRouteDrop(title);
              const routesForMk = routesByMarket.get(market) ?? [];
              const rowConflict = conflictHintForKeyword(parseRouteKeywordList(routeKw)[0] ?? "", routeKeywordConflicts);

              return (
                <tr key={title} className="border-t bg-amber-50/50 align-top">
                  <td className="px-2 py-2 text-xs">
                    <div className="flex flex-wrap gap-1 mb-1">
                      {item.needs_market && <span className="px-1 rounded bg-amber-200 text-amber-900">Thiếu TT</span>}
                      {item.needs_route && <span className="px-1 rounded bg-orange-200 text-orange-900">Thiếu tuyến</span>}
                      {item.count > 1 && <span className="text-gray-500">{item.count} tour</span>}
                    </div>
                    <span className="line-clamp-3" title={item.sample}>{item.sample || title}</span>
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input text-xs py-1 w-full"
                      list="classify-market-list"
                      value={market}
                      onChange={(e) => setPending((prev) => ({
                        ...prev,
                        [title]: { market: e.target.value, route, routeKw, marketKw: p?.marketKw ?? routeKw, linkMarketKw: p?.linkMarketKw ?? true },
                      }))}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input text-xs py-1 w-full"
                      list={market ? `classify-route-${encodeURIComponent(market)}` : undefined}
                      placeholder={market ? `${market} (mặc định)` : "Nhập tên tuyến mới…"}
                      value={route}
                      onChange={(e) => setPending((prev) => ({
                        ...prev,
                        [title]: { market, route: e.target.value, routeKw, marketKw: p?.marketKw ?? routeKw, linkMarketKw: p?.linkMarketKw ?? true },
                      }))}
                    />
                    {market ? (
                      <datalist id={`classify-route-${encodeURIComponent(market)}`}>
                        <option value={market} />
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
                        [title]: { market, route, routeKw: e.target.value, marketKw: p?.marketKw ?? e.target.value, linkMarketKw: false },
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
                      disabled={!market.trim() || !routeKw.trim()}
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
          {gapItems.length} tour cần xử lý
          {gapItems.length > 0 && " — Gán thêm một dòng điều kiện (OR), không gộp vào dòng rule cũ"}
        </p>
      </div>
    </div>
  );
}
