import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis, Legend, Treemap, ReferenceLine,
} from "recharts";
import {
  getMarketLabOverview, getMarketLabSupplyCalendar, getMarketLabRouteHistory,
  type MarketLabRouteRow, type MarketLabOverview,
} from "@/lib/api";
import { PageTitle } from "@/components/InfoTip";
import { TrendingUp, TrendingDown, Minus, Map, Route, Sparkles, Wrench, Filter } from "lucide-react";
import { fmtVND } from "@/lib/utils";

type Grain = "route" | "market";
type Tab = "opportunity" | "operating";

const PHASE_META: Record<string, { label: string; color: string; bg: string; desc: string; hint: string }> = {
  expansion:    { label: "Mở rộng",      color: "text-emerald-800", bg: "bg-emerald-100", desc: "TT đang tăng cung mạnh (≥12%)", hint: "Tăng lịch KH — thị trường đang nóng" },
  price_war:    { label: "Cạnh tranh giá",color: "text-red-800",     bg: "bg-red-100",     desc: "Đối thủ đang hạ giá mạnh",        hint: "Kiểm tra lại giá tour — xem tour mẫu đối thủ" },
  tight_supply: { label: "Thắt cung",     color: "text-amber-800",   bg: "bg-amber-100",   desc: "TT giảm cung mạnh (≤-10%)",       hint: "Cơ hội tăng giá hoặc giữ lịch KH ổn định" },
  freq_pressure:{ label: "Áp lực lịch",  color: "text-orange-800",  bg: "bg-orange-100",  desc: "VTR ít lịch hơn TT ≥25%",         hint: "Bổ sung lịch KH — đặc biệt cuối tuần" },
  stable:       { label: "Ổn định",       color: "text-gray-600",    bg: "bg-gray-100",    desc: "Không có biến động lớn",          hint: "Theo dõi định kỳ" },
};

function PhaseBadge({ phase, row }: { phase: string; row?: MarketLabRouteRow }) {
  const m = PHASE_META[phase] ?? PHASE_META.stable;
  const mom = row?.momentum;
  return (
    <span className="relative group cursor-help">
      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${m.bg} ${m.color}`}>
        {m.label}
      </span>
      {/* Tooltip */}
      <span className="absolute bottom-full left-0 mb-1.5 z-50 hidden group-hover:block w-64 bg-gray-900 text-white text-xs rounded-lg p-3 shadow-xl">
        <span className="font-semibold block mb-1">{m.label}</span>
        <span className="text-gray-300 block mb-2">{m.desc}</span>
        {row && (
          <span className="border-t border-gray-700 pt-2 block space-y-1 text-gray-200">
            <span className="block">TT: <strong>{row.market_departures_monthly} đoàn/tháng</strong></span>
            <span className="block">VTR: <strong>{row.vtr_departures_monthly} đoàn/tháng</strong></span>
            {row.avg_gap_pct != null && <span className="block">Chênh giá: <strong className={row.avg_gap_pct >= 5 ? "text-red-300" : row.avg_gap_pct <= -5 ? "text-green-300" : "text-blue-300"}>{row.avg_gap_pct > 0 ? "+" : ""}{row.avg_gap_pct}%</strong></span>}
            {mom?.supply_delta_pct != null && <span className="block">Cung TT: <strong className={mom.supply_delta_pct >= 0 ? "text-emerald-300" : "text-red-300"}>{mom.supply_delta_pct > 0 ? "+" : ""}{mom.supply_delta_pct}%</strong> vs snapshot trước</span>}
            <span className="block">{row.competitor_count} đối thủ · {row.market_tour_count} tour TT</span>
          </span>
        )}
        <span className="border-t border-gray-700 pt-2 mt-2 block text-emerald-300 font-medium">→ {m.hint}</span>
      </span>
    </span>
  );
}

function TrendArrow({ val }: { val: number | null | undefined }) {
  if (val == null) return <span className="text-gray-400 text-xs">—</span>;
  if (val >= 5) return <span className="text-emerald-600 text-xs flex items-center gap-0.5"><TrendingUp size={11} />+{val}%</span>;
  if (val <= -5) return <span className="text-red-600 text-xs flex items-center gap-0.5"><TrendingDown size={11} />{val}%</span>;
  return <span className="text-gray-500 text-xs flex items-center gap-0.5"><Minus size={11} />{val}%</span>;
}

const TREEMAP_COLORS = [
  "#003580","#0057b8","#1a75d2","#3d8ee6","#66aaf5","#00897b","#26a69a",
  "#43a047","#7cb342","#c0ca33","#fdd835","#fb8c00","#e53935","#8e24aa",
];

function MarketHeatMap({ markets }: { markets: any[] }) {
  const data = useMemo(() => {
    const root = markets
      .filter((m) => m.market_departures_monthly > 0)
      .map((m, i) => ({
        name: m.thi_truong,
        value: Math.round(m.market_departures_monthly * 10) / 10,
        score: m.opportunity_score,
        gap: m.avg_gap_pct,
        fill: TREEMAP_COLORS[i % TREEMAP_COLORS.length],
      }));
    return root;
  }, [markets]);

  return (
    <div className="card p-4">
      <h3 className="font-semibold text-sm mb-1">Heat Map thị trường — theo đoàn TT/tháng</h3>
      <p className="text-xs text-gray-500 mb-3">Kích cỡ = cung thị trường. Click thị trường để drill-down tuyến.</p>
      <ResponsiveContainer width="100%" height={280}>
        <Treemap
          data={data}
          dataKey="value"
          nameKey="name"
          content={({ x, y, width, height, name, value, fill, gap, score }: any) => {
            if (!width || !height || width < 20 || height < 18) return null;
            return (
              <g>
                <rect x={x} y={y} width={width} height={height} fill={fill} fillOpacity={0.85} stroke="#fff" strokeWidth={2} rx={4} />
                {width > 50 && height > 30 && (
                  <>
                    <text x={x + width / 2} y={y + height / 2 - 6} textAnchor="middle" dominantBaseline="middle" fontSize={Math.min(12, width / 7)} fill="#fff" fontWeight="600">
                      {name && name.length > 14 ? name.slice(0, 13) + "…" : name}
                    </text>
                    <text x={x + width / 2} y={y + height / 2 + 10} textAnchor="middle" dominantBaseline="middle" fontSize={10} fill="#e2e8f0">
                      {value} đoàn{gap != null ? ` · ${gap > 0 ? "+" : ""}${gap}%` : ""}
                    </text>
                  </>
                )}
              </g>
            );
          }}
        />
      </ResponsiveContainer>
    </div>
  );
}

function RouteHistoryChart({ routeKey }: { routeKey: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["route-history", routeKey],
    queryFn: () => getMarketLabRouteHistory(routeKey, 30),
    staleTime: 120_000,
    enabled: !!routeKey,
  });

  if (isLoading) return <div className="h-48 flex items-center justify-center text-xs text-gray-400">Đang tải lịch sử…</div>;
  if (!data?.points?.length) return <div className="h-48 flex items-center justify-center text-xs text-gray-400">Chưa có dữ liệu lịch sử (cần ≥2 snapshot)</div>;

  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs font-medium text-gray-600 mb-1">Cung đoàn/tháng — 30 ngày qua</p>
        <ResponsiveContainer width="100%" height={140}>
          <LineChart data={data.points} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={(v) => v.slice(5)} />
            <YAxis tick={{ fontSize: 9 }} width={28} />
            <Tooltip
              labelFormatter={(v) => `Ngày ${v}`}
              formatter={(val: number, name: string) => [val, name === "market_dep" ? "TT" : "VTR"]}
            />
            <Legend formatter={(v) => v === "market_dep" ? "TT (đoàn/tháng)" : "VTR"} iconSize={10} wrapperStyle={{ fontSize: 10 }} />
            <Line type="monotone" dataKey="market_dep" stroke="#64748b" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="vtr_dep" stroke="#003580" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {data.points.some((p) => p.gap_pct != null) && (
        <div>
          <p className="text-xs font-medium text-gray-600 mb-1">Chênh giá VTR vs TT (%)</p>
          <ResponsiveContainer width="100%" height={100}>
            <LineChart data={data.points} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={(v) => v.slice(5)} />
              <YAxis tick={{ fontSize: 9 }} width={32} tickFormatter={(v) => `${v}%`} />
              <Tooltip labelFormatter={(v) => `Ngày ${v}`} formatter={(v: number) => [`${v}%`, "Chênh giá"]} />
              <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="4 3" />
              <Line type="monotone" dataKey="gap_pct" stroke="#e53935" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function WeeklyBriefCard({ route }: { route: any }) {
  const mom = route.momentum ?? {};
  return (
    <li className="text-sm border border-gray-100 rounded-lg p-3 bg-gray-50/50">
      <div className="flex items-start justify-between gap-2 flex-wrap">
        <div>
          <p className="font-semibold text-gray-900 leading-snug">{route.tuyen_tour}</p>
          <p className="text-gray-500 text-xs mt-0.5">{route.thi_truong}</p>
        </div>
        <PhaseBadge phase={route.phase} />
      </div>

      {/* Số liệu key */}
      <div className="grid grid-cols-3 gap-2 mt-2 text-xs">
        <div className="bg-white rounded p-1.5 border border-gray-100">
          <p className="text-gray-500">TT đoàn/tháng</p>
          <p className="font-bold text-gray-900">{route.market_departures_monthly ?? "—"}</p>
          {mom.supply_delta_pct != null && (
            <p className={mom.supply_delta_pct >= 0 ? "text-emerald-600" : "text-red-600"}>
              {mom.supply_delta_pct > 0 ? "+" : ""}{mom.supply_delta_pct}% vs trước
            </p>
          )}
        </div>
        <div className="bg-white rounded p-1.5 border border-gray-100">
          <p className="text-gray-500">VTR đoàn/tháng</p>
          <p className="font-bold text-blue-900">{route.vtr_departures_monthly ?? "—"}</p>
          {route.avg_freq_gap_pct != null && (
            <p className={route.avg_freq_gap_pct <= -20 ? "text-amber-600" : "text-gray-400"}>
              Gap TS: {route.avg_freq_gap_pct}%
            </p>
          )}
        </div>
        <div className="bg-white rounded p-1.5 border border-gray-100">
          <p className="text-gray-500">Chênh giá</p>
          <p className={`font-bold ${(route.avg_gap_pct ?? 0) >= 5 ? "text-red-700" : (route.avg_gap_pct ?? 0) <= -5 ? "text-green-700" : "text-gray-700"}`}>
            {route.avg_gap_pct != null ? `${route.avg_gap_pct > 0 ? "+" : ""}${route.avg_gap_pct}%` : "—"}
          </p>
          {route.competitor_count > 0 && <p className="text-gray-400">{route.competitor_count} đối thủ</p>}
        </div>
      </div>

      <p className="text-gray-600 text-xs mt-2">{route.base}</p>
      <p className="text-primary-700 text-xs mt-1 font-medium">→ {route.action_hint}</p>
    </li>
  );
}

export default function MarketLab() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [grain, setGrain] = useState<Grain>((searchParams.get("grain") as Grain) || "route");
  const [tab, setTab] = useState<Tab>((searchParams.get("tab") as Tab) || "opportunity");
  const [marketFilter, setMarketFilter] = useState(searchParams.get("market") || "");
  const [hideSuspect, setHideSuspect] = useState(searchParams.get("hide_suspect") !== "false");
  const [minScore, setMinScore] = useState(0);

  const routeParam = searchParams.get("route") || "";
  const [selectedRoute, setSelectedRoute] = useState<MarketLabRouteRow | null>(null);

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["market-lab", grain, tab, marketFilter, hideSuspect],
    queryFn: () => getMarketLabOverview({ grain, tab, thi_truong: marketFilter || undefined, hide_suspect: hideSuspect }),
    staleTime: 120_000,
    retry: 1,
  });

  const pickFromParam = useMemo(() => {
    if (!routeParam || !data || grain !== "route") return null;
    const routes = (data as MarketLabOverview).routes ?? [];
    return routes.find((r) => r.route_key === routeParam) ?? null;
  }, [routeParam, data, grain]);

  const activeRoute = selectedRoute ?? pickFromParam;

  const { data: calendar } = useQuery({
    queryKey: ["market-lab-calendar", activeRoute?.thi_truong, activeRoute?.tuyen_tour],
    queryFn: () => getMarketLabSupplyCalendar(activeRoute!.thi_truong, activeRoute!.tuyen_tour),
    enabled: !!activeRoute?.thi_truong && !!activeRoute?.tuyen_tour,
  });

  const markets = useMemo(() => {
    const set = new Set<string>();
    (data?.markets ?? []).forEach((m) => set.add(m.thi_truong));
    return Array.from(set).sort();
  }, [data?.markets]);

  const rows = useMemo(() => {
    const base = grain === "route" ? (data?.routes ?? []) : [];
    return minScore > 0 ? base.filter((r) => r.opportunity_score >= minScore) : base;
  }, [grain, data?.routes, minScore]);

  const drillIntoMarket = (market: string) => {
    setMarketFilter(market);
    setGrain("route");
    setSelectedRoute(null);
    setSearchParams({ grain: "route", tab, market, hide_suspect: hideSuspect ? "true" : "false" });
  };

  const clearMarketFilter = () => {
    setMarketFilter("");
    setSearchParams({ grain, tab, hide_suspect: hideSuspect ? "true" : "false" });
  };

  const selectRoute = (r: MarketLabRouteRow) => {
    setSelectedRoute(r);
    setSearchParams((p) => {
      const next = new URLSearchParams(p);
      next.set("route", r.route_key);
      next.set("tab", tab);
      next.set("grain", grain);
      return next;
    });
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle title="Tour Market Lab" tip="Nghiên cứu thị trường theo Tuyến tour — cung KH, giá/ngày, cơ hội & vận hành VTR." />
          <p className="text-sm text-gray-500 mt-1">
            Lịch sử snapshot: {data?.history_days ?? 0} ngày
            {data?.meta && (
              <span className="ml-2">
                · {data.meta.source === "snapshot" ? "DB snapshot" : "Tính live"}
                {data.meta.compute_seconds != null && ` (${data.meta.compute_seconds}s)`}
              </span>
            )}
          </p>
        </div>
        <button type="button" onClick={() => refetch()} className="btn-secondary text-xs">
          {isFetching ? "Đang tải…" : "Làm mới"}
        </button>
      </div>

      {/* Weekly brief — enhanced */}
      {data?.weekly_brief?.top_routes && data.weekly_brief.top_routes.length > 0 && (
        <div className="card p-5 border-l-4 border-l-primary-600">
          <h2 className="font-semibold text-sm mb-1 flex items-center gap-2">
            <Sparkles size={16} /> Triển vọng tuần này — top tuyến cần chú ý
          </h2>
          <p className="text-xs text-gray-500 mb-4">{data.weekly_brief.note}</p>
          <ul className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {data.weekly_brief.top_routes.slice(0, 3).map((s) => (
              <WeeklyBriefCard key={s.route_key} route={s} />
            ))}
          </ul>
        </div>
      )}

      {marketFilter && grain === "route" && (
        <div className="card p-3 bg-blue-50 border border-blue-200 text-sm flex flex-wrap items-center justify-between gap-2">
          <p><strong>Đang lọc:</strong> {marketFilter}</p>
          <button type="button" className="text-xs text-primary-700 underline" onClick={clearMarketFilter}>Xóa lọc</button>
        </div>
      )}

      {(data?.meta?.suspect_routes_hidden ?? 0) > 0 && hideSuspect && (
        <p className="text-xs text-amber-700">
          Đã ẩn {data!.meta!.suspect_routes_hidden} tuyến nghi sai thị trường.
          <button type="button" className="ml-2 underline" onClick={() => setHideSuspect(false)}>Hiện tất cả</button>
        </p>
      )}

      {/* Controls */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
          <button type="button" onClick={() => setGrain("route")} className={`px-3 py-1.5 flex items-center gap-1 ${grain === "route" ? "bg-primary-600 text-white" : "bg-white text-gray-600"}`}>
            <Route size={14} /> Tuyến tour
          </button>
          <button type="button" onClick={() => setGrain("market")} className={`px-3 py-1.5 flex items-center gap-1 ${grain === "market" ? "bg-primary-600 text-white" : "bg-white text-gray-600"}`}>
            <Map size={14} /> Thị trường
          </button>
        </div>
        <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
          <button type="button" onClick={() => setTab("opportunity")} className={`px-3 py-1.5 flex items-center gap-1 ${tab === "opportunity" ? "bg-emerald-600 text-white" : "bg-white text-gray-600"}`}>
            <TrendingUp size={14} /> Cơ hội
          </button>
          <button type="button" onClick={() => setTab("operating")} className={`px-3 py-1.5 flex items-center gap-1 ${tab === "operating" ? "bg-amber-600 text-white" : "bg-white text-gray-600"}`}>
            <Wrench size={14} /> Vận hành VTR
          </button>
        </div>
        <label className="flex items-center gap-1.5 text-xs text-gray-600">
          <input type="checkbox" checked={hideSuspect} onChange={(e) => setHideSuspect(e.target.checked)} />
          Ẩn tuyến nghi sai TT
        </label>
        <select className="input text-sm py-1.5 max-w-[200px]" value={marketFilter}
          onChange={(e) => { setMarketFilter(e.target.value); if (e.target.value) setGrain("route"); }}>
          <option value="">Tất cả thị trường</option>
          {markets.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        {grain === "route" && (
          <div className="flex items-center gap-2 text-xs text-gray-600">
            <Filter size={13} />
            <span>Score ≥</span>
            <select className="input text-xs py-1 w-20" value={minScore} onChange={(e) => setMinScore(Number(e.target.value))}>
              {[0, 5, 10, 20, 30, 50].map((v) => <option key={v} value={v}>{v === 0 ? "Tất cả" : v}</option>)}
            </select>
          </div>
        )}
      </div>

      {/* Heat Map cho grain=market */}
      {!isLoading && grain === "market" && (data?.markets ?? []).length > 0 && (
        <MarketHeatMap markets={data!.markets!} />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Table */}
        <div className="lg:col-span-3 card overflow-hidden">
          {isLoading && (
            <div className="p-6 text-sm text-gray-500 space-y-2">
              <p className="font-medium">Đang tải…</p>
              <p className="text-xs text-gray-400">Lần đầu sau deploy có thể mất 1–2 phút. Các lần sau nhanh hơn nhờ cache.</p>
            </div>
          )}
          {isError && (
            <div className="p-6 text-sm text-red-600">
              <p className="font-medium">Không tải được dữ liệu</p>
              <p className="text-xs mt-1">{(error as Error)?.message || "Timeout — thử Làm mới"}</p>
              <button type="button" className="btn-secondary text-xs mt-2" onClick={() => refetch()}>Thử lại</button>
            </div>
          )}
          {!isLoading && grain === "market" && (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-xs text-gray-500">
                <tr>
                  <th className="px-3 py-2">Thị trường</th>
                  <th className="px-3 py-2">Tuyến</th>
                  <th className="px-3 py-2">Đoàn TT/tháng</th>
                  <th className="px-3 py-2">Gap VTR</th>
                  <th className="px-3 py-2">Khoảng trống</th>
                  <th className="px-3 py-2">Score</th>
                </tr>
              </thead>
              <tbody>
                {(data?.markets ?? []).map((m) => (
                  <tr key={m.thi_truong} className="border-t border-gray-100 hover:bg-gray-50 cursor-pointer" onClick={() => drillIntoMarket(m.thi_truong)}>
                    <td className="px-3 py-2 font-medium">{m.thi_truong}</td>
                    <td className="px-3 py-2">{m.route_count}</td>
                    <td className="px-3 py-2">{m.market_departures_monthly}</td>
                    <td className="px-3 py-2">{m.avg_gap_pct != null ? `${m.avg_gap_pct}%` : "—"}</td>
                    <td className="px-3 py-2">{m.white_space_routes} tuyến</td>
                    <td className="px-3 py-2 font-bold text-emerald-700">{m.opportunity_score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {!isLoading && grain === "route" && (
            <div className="overflow-auto max-h-[520px]">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left text-xs text-gray-500 sticky top-0">
                  <tr>
                    <th className="px-3 py-2">Tuyến tour</th>
                    <th className="px-3 py-2">TT</th>
                    <th className="px-3 py-2">Đoàn TT</th>
                    <th className="px-3 py-2">Đoàn VTR</th>
                    <th className="px-3 py-2">Chênh %</th>
                    <th className="px-3 py-2">Gap TS</th>
                    <th className="px-3 py-2">Phase</th>
                    <th className="px-3 py-2">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.route_key} onClick={() => selectRoute(r)}
                      className={`border-t border-gray-100 cursor-pointer hover:bg-primary-50 ${activeRoute?.route_key === r.route_key ? "bg-primary-50" : ""}`}>
                      <td className="px-3 py-2 font-medium max-w-[180px] truncate" title={r.tuyen_tour}>
                        {r.tuyen_tour}
                        {r.quality === "generic" && <span className="ml-1 text-[10px] text-amber-600">(chưa tách)</span>}
                      </td>
                      <td className="px-3 py-2 text-gray-500 text-xs">{r.thi_truong}</td>
                      <td className="px-3 py-2">{r.market_departures_monthly}</td>
                      <td className="px-3 py-2">{r.vtr_departures_monthly}</td>
                      <td className="px-3 py-2">
                        {r.avg_gap_pct != null ? (
                          <span className={r.avg_gap_pct >= 5 ? "text-red-600" : r.avg_gap_pct <= -5 ? "text-green-600" : ""}>
                            {r.avg_gap_pct}%
                          </span>
                        ) : "—"}
                      </td>
                      <td className="px-3 py-2">{r.avg_freq_gap_pct != null ? `${r.avg_freq_gap_pct}%` : "—"}</td>
                      <td className="px-3 py-2"><PhaseBadge phase={r.phase} row={r} /></td>
                      <td className="px-3 py-2 font-bold text-emerald-700">{r.opportunity_score > 0 ? r.opportunity_score : "—"}</td>
                    </tr>
                  ))}
                  {rows.length === 0 && (
                    <tr><td colSpan={8} className="px-3 py-8 text-center text-gray-400">Không có tuyến phù hợp</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Detail panel — supply calendar + trend chart */}
        <div className="lg:col-span-2 space-y-4">
          <div className="card p-4">
            <h3 className="font-semibold text-sm mb-2">Lịch chiến lược cung (theo tháng KH)</h3>
            {!activeRoute && <p className="text-xs text-gray-400">Chọn một tuyến để xem chi tiết.</p>}
            {activeRoute && (
              <>
                <p className="text-xs text-gray-600 mb-2">
                  <strong>{activeRoute.tuyen_tour}</strong> · {activeRoute.thi_truong}
                  {activeRoute.momentum?.supply_delta_pct != null && (
                    <span className={`ml-2 ${activeRoute.momentum.supply_delta_pct >= 0 ? "text-emerald-700" : "text-red-700"}`}>
                      TT cung {activeRoute.momentum.supply_delta_pct > 0 ? "+" : ""}{activeRoute.momentum.supply_delta_pct}% vs snapshot trước
                    </span>
                  )}
                </p>
                {calendar?.months && calendar.months.length > 0 ? (
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={calendar.months}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="month" tick={{ fontSize: 9 }} />
                      <YAxis tick={{ fontSize: 9 }} />
                      <Tooltip />
                      <Legend wrapperStyle={{ fontSize: 10 }} />
                      <Bar dataKey="market_slots" name="TT đoàn/tháng" fill="#94a3b8" radius={[2, 2, 0, 0]} />
                      <Bar dataKey="vtr_slots" name="VTR" fill="#003580" radius={[2, 2, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <p className="text-xs text-gray-400">Chưa parse được tháng KH từ lịch tour.</p>
                )}
                <div className="flex gap-3 mt-2">
                  <Link to={`/compare?tab=price&tuyen=${encodeURIComponent(activeRoute.tuyen_tour)}`} className="text-xs text-primary-600 hover:underline">So sánh giá →</Link>
                  <Link to={`/compare?tab=coverage`} className="text-xs text-primary-600 hover:underline">Phủ sóng →</Link>
                </div>
              </>
            )}
          </div>

          {/* Trend chart 30 ngày */}
          {activeRoute && (
            <div className="card p-4">
              <h3 className="font-semibold text-sm mb-3">Xu hướng 30 ngày qua</h3>
              <RouteHistoryChart routeKey={activeRoute.route_key} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
