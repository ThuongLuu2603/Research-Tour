import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend,
} from "recharts";
import {
  getMarketLabOverview, getMarketLabSupplyCalendar,
  type MarketLabRouteRow, type MarketLabOverview,
} from "@/lib/api";
import { PageTitle } from "@/components/InfoTip";
import { TrendingUp, Map, Route, Sparkles, Wrench } from "lucide-react";

type Grain = "route" | "market";
type Tab = "opportunity" | "operating";

export default function MarketLab() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [grain, setGrain] = useState<Grain>((searchParams.get("grain") as Grain) || "route");
  const [tab, setTab] = useState<Tab>((searchParams.get("tab") as Tab) || "opportunity");
  const [marketFilter, setMarketFilter] = useState(searchParams.get("market") || "");
  const [hideSuspect, setHideSuspect] = useState(searchParams.get("hide_suspect") !== "false");

  const routeParam = searchParams.get("route") || "";
  const [selectedRoute, setSelectedRoute] = useState<MarketLabRouteRow | null>(null);

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["market-lab", grain, tab, marketFilter, hideSuspect],
    queryFn: () => getMarketLabOverview({
      grain,
      tab,
      thi_truong: marketFilter || undefined,
      hide_suspect: hideSuspect,
    }),
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
    queryFn: () =>
      getMarketLabSupplyCalendar(activeRoute!.thi_truong, activeRoute!.tuyen_tour),
    enabled: !!activeRoute?.thi_truong && !!activeRoute?.tuyen_tour,
  });

  const markets = useMemo(() => {
    const set = new Set<string>();
    (data?.markets ?? []).forEach((m) => set.add(m.thi_truong));
    return Array.from(set).sort();
  }, [data?.markets]);

  const rows = grain === "route" ? (data?.routes ?? []) : [];

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
          <PageTitle title="Tour Market Lab" tip="Nghiên cứu thị trường theo Tuyến tour — cung KH, giá/ngày, cơ hội & vận hành VTR. Không dùng KS/HK." />
          <p className="text-sm text-gray-500 mt-1">
            Lịch sử snapshot: {data?.history_days ?? 0} ngày · Ưu tiên tuyến tour
            {data?.meta && (
              <span className="ml-2">
                · {data.meta.source === "snapshot" ? "Đọc DB snapshot" : "Tính live"}
                {data.meta.compute_seconds != null && ` (${data.meta.compute_seconds}s)`}
              </span>
            )}
          </p>
        </div>
        <button type="button" onClick={() => refetch()} className="btn-secondary text-xs">
          {isFetching ? "Đang tải…" : "Làm mới"}
        </button>
      </div>

      {/* Weekly brief */}
      {data?.weekly_brief?.top_routes && data.weekly_brief.top_routes.length > 0 && (
        <div className="card p-5 border-l-4 border-l-primary-600">
          <h2 className="font-semibold text-sm mb-3 flex items-center gap-2">
            <Sparkles size={16} /> Triển vọng 1 tuần (top tuyến)
          </h2>
          <p className="text-xs text-gray-500 mb-3">{data.weekly_brief.note}</p>
          <ul className="space-y-3">
            {data.weekly_brief.top_routes.slice(0, 3).map((s) => (
              <li key={s.route_key} className="text-sm">
                <p className="font-medium text-gray-900">
                  {s.tuyen_tour}
                  <span className="text-gray-500 font-normal"> · {s.thi_truong}</span>
                </p>
                <p className="text-gray-600 text-xs mt-0.5">{s.base}</p>
                <p className="text-primary-700 text-xs mt-0.5">→ {s.action_hint}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {marketFilter && grain === "route" && (
        <div className="card p-3 bg-blue-50 border border-blue-200 text-sm flex flex-wrap items-center justify-between gap-2">
          <p>
            <strong>Đang lọc thị trường:</strong> {marketFilter} — bảng bên dưới là các <strong>tuyến tour</strong> có cột Thị trường = giá trị này trong database (có thể lẫn tour phân loại sai).
          </p>
          <button type="button" className="text-xs text-primary-700 underline" onClick={clearMarketFilter}>
            Xóa lọc thị trường
          </button>
        </div>
      )}

      {(data?.meta?.suspect_routes_hidden ?? 0) > 0 && hideSuspect && (
        <p className="text-xs text-amber-700">
          Đã ẩn {data!.meta!.suspect_routes_hidden} tuyến nghi ngờ sai thị trường (vd. Hồng Kông gán nhầm Đồng Bằng Sông Hồng).
          <button type="button" className="ml-2 underline" onClick={() => setHideSuspect(false)}>Hiện tất cả</button>
        </p>
      )}

      {/* Controls */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
          <button
            type="button"
            onClick={() => setGrain("route")}
            className={`px-3 py-1.5 flex items-center gap-1 ${grain === "route" ? "bg-primary-600 text-white" : "bg-white text-gray-600"}`}
          >
            <Route size={14} /> Tuyến tour
          </button>
          <button
            type="button"
            onClick={() => setGrain("market")}
            className={`px-3 py-1.5 flex items-center gap-1 ${grain === "market" ? "bg-primary-600 text-white" : "bg-white text-gray-600"}`}
          >
            <Map size={14} /> Thị trường
          </button>
        </div>
        <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
          <button
            type="button"
            onClick={() => setTab("opportunity")}
            className={`px-3 py-1.5 flex items-center gap-1 ${tab === "opportunity" ? "bg-emerald-600 text-white" : "bg-white text-gray-600"}`}
          >
            <TrendingUp size={14} /> Cơ hội (SP mới)
          </button>
          <button
            type="button"
            onClick={() => setTab("operating")}
            className={`px-3 py-1.5 flex items-center gap-1 ${tab === "operating" ? "bg-amber-600 text-white" : "bg-white text-gray-600"}`}
          >
            <Wrench size={14} /> Vận hành VTR
          </button>
        </div>
        <label className="flex items-center gap-1.5 text-xs text-gray-600">
          <input
            type="checkbox"
            checked={hideSuspect}
            onChange={(e) => setHideSuspect(e.target.checked)}
          />
          Ẩn tuyến nghi sai thị trường
        </label>
        <select
          className="input text-sm py-1.5 max-w-[200px]"
          value={marketFilter}
          onChange={(e) => {
            const v = e.target.value;
            setMarketFilter(v);
            if (v) setGrain("route");
          }}
        >
          <option value="">Tất cả thị trường</option>
          {markets.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Table */}
        <div className="lg:col-span-3 card overflow-hidden">
          {isLoading && (
            <div className="p-6 text-sm text-gray-500 space-y-2">
              <p className="font-medium">Đang tải từ database…</p>
              <p className="text-xs text-gray-400">
                Lần đầu sau deploy có thể mất 1–2 phút (gộp ~9k tour). Các lần sau nhanh hơn nhờ cache.
              </p>
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
                </tr>
              </thead>
              <tbody>
                {(data?.markets ?? []).map((m) => (
                  <tr
                    key={m.thi_truong}
                    className="border-t border-gray-100 hover:bg-gray-50 cursor-pointer"
                    onClick={() => drillIntoMarket(m.thi_truong)}
                  >
                    <td className="px-3 py-2 font-medium">{m.thi_truong}</td>
                    <td className="px-3 py-2">{m.route_count}</td>
                    <td className="px-3 py-2">{m.market_departures_monthly}</td>
                    <td className="px-3 py-2">{m.avg_gap_pct != null ? `${m.avg_gap_pct}%` : "—"}</td>
                    <td className="px-3 py-2">{m.white_space_routes} tuyến</td>
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
                    <th className="px-3 py-2">Thị trường</th>
                    <th className="px-3 py-2">Đoàn TT</th>
                    <th className="px-3 py-2">Đoàn VTR</th>
                    <th className="px-3 py-2">Chênh %</th>
                    <th className="px-3 py-2">Gap TS</th>
                    <th className="px-3 py-2">Phase</th>
                    <th className="px-3 py-2">Ghi chú</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr
                      key={r.route_key}
                      onClick={() => selectRoute(r)}
                      className={`border-t border-gray-100 cursor-pointer hover:bg-primary-50 ${
                        activeRoute?.route_key === r.route_key ? "bg-primary-50" : ""
                      }`}
                    >
                      <td className="px-3 py-2 font-medium max-w-[180px] truncate" title={r.tuyen_tour}>
                        {r.tuyen_tour}
                        {r.quality === "generic" && (
                          <span className="ml-1 text-[10px] text-amber-600">(chưa tách tuyến)</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-gray-600">{r.thi_truong}</td>
                      <td className="px-3 py-2">{r.market_departures_monthly}</td>
                      <td className="px-3 py-2">{r.vtr_departures_monthly}</td>
                      <td className="px-3 py-2">
                        {r.avg_gap_pct != null ? (
                          <span className={r.avg_gap_pct >= 5 ? "text-red-600" : r.avg_gap_pct <= -5 ? "text-green-600" : ""}>
                            {r.avg_gap_pct}%
                          </span>
                        ) : "—"}
                      </td>
                      <td className="px-3 py-2">
                        {r.avg_freq_gap_pct != null ? `${r.avg_freq_gap_pct}%` : "—"}
                      </td>
                      <td className="px-3 py-2">
                        <PhaseBadge phase={r.phase} />
                      </td>
                      <td className="px-3 py-2 text-[10px] text-amber-700 max-w-[140px]" title={r.quality_note}>
                        {r.quality === "generic" ? "Tuyến = tên TT" : r.quality_note ? "⚠" : ""}
                      </td>
                    </tr>
                  ))}
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-3 py-8 text-center text-gray-400">
                        Không có tuyến phù hợp bộ lọc
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Supply calendar */}
        <div className="lg:col-span-2 card p-4">
          <h3 className="font-semibold text-sm mb-2">Lịch chiến lược cung (theo tháng KH)</h3>
          {!activeRoute && (
            <p className="text-xs text-gray-400">Chọn một tuyến trong bảng để xem lịch TT vs VTR.</p>
          )}
          {activeRoute && (
            <>
              <p className="text-xs text-gray-600 mb-3">
                <strong>{activeRoute.tuyen_tour}</strong> · {activeRoute.thi_truong}
                {activeRoute.momentum?.supply_delta_pct != null && (
                  <span className="ml-2 text-amber-700">
                    TT cung {activeRoute.momentum.supply_delta_pct > 0 ? "+" : ""}
                    {activeRoute.momentum.supply_delta_pct}% vs snapshot trước
                  </span>
                )}
              </p>
              {calendar?.months && calendar.months.length > 0 ? (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={calendar.months}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="month" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="market_slots" name="TT (đoàn/tháng)" fill="#94a3b8" radius={[2, 2, 0, 0]} />
                    <Bar dataKey="vtr_slots" name="VTR" fill="#003580" radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-xs text-gray-400">Chưa parse được tháng KH từ lịch tour.</p>
              )}
              <div className="flex gap-2 mt-3">
                <Link
                  to={`/compare?tab=price&tuyen=${encodeURIComponent(activeRoute.tuyen_tour)}`}
                  className="text-xs text-primary-600 hover:underline"
                >
                  So sánh giá →
                </Link>
                <Link
                  to={`/compare?tab=coverage`}
                  className="text-xs text-primary-600 hover:underline"
                >
                  Phủ sóng →
                </Link>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function PhaseBadge({ phase }: { phase: string }) {
  const styles: Record<string, string> = {
    expansion: "bg-emerald-100 text-emerald-800",
    price_war: "bg-red-100 text-red-800",
    tight_supply: "bg-amber-100 text-amber-800",
    freq_pressure: "bg-orange-100 text-orange-800",
    stable: "bg-gray-100 text-gray-600",
  };
  const labels: Record<string, string> = {
    expansion: "Mở rộng",
    price_war: "Cạnh tranh giá",
    tight_supply: "Thắt cung",
    freq_pressure: "Áp lực lịch",
    stable: "Ổn định",
  };
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${styles[phase] ?? styles.stable}`}>
      {labels[phase] ?? phase}
    </span>
  );
}
