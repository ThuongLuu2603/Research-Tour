import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";
import { getMarketIntelligence } from "@/lib/api";
import { fmtVND } from "@/lib/utils";
import { Info, Calendar, DollarSign } from "lucide-react";

const COLORS = ["#003580","#1a75d2","#3d8ee6","#66aaf5","#99c4f8","#bbdafb","#d1e9fe","#e8f4ff","#c7dffc","#94c5f8","#5ba8f5","#3091f2","#1178e5","#0062c8","#0050b0"];

export default function MarketShare() {
  const [tab, setTab] = useState<"departures" | "price" | "routes">("departures");
  const { data } = useQuery({
    queryKey: ["market-intelligence"],
    queryFn: () => getMarketIntelligence(),
  });

  const totalDepartures = data?.totals?.departure_monthly ?? 0;

  const departureChart = (data?.markets ?? []).slice(0, 15).map((m) => ({
    label: m.label.length > 18 ? m.label.slice(0, 18) + "…" : m.label,
    value: m.departure_monthly,
    share: m.departure_share_pct,
  }));

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Phân tích Thị trường</h1>
        <p className="text-sm text-gray-500">Giá & tần suất khởi hành có trọng số theo số đoàn — không chỉ đếm số tour</p>
      </div>

      <div className="card p-4 flex items-start gap-3 bg-blue-50 border-blue-200 text-sm text-blue-900">
        <Info size={18} className="shrink-0 mt-0.5" />
        <div>
          <p className="font-medium">Phương pháp</p>
          <p className="text-blue-800 mt-1 text-xs">{data?.methodology}</p>
        </div>
      </div>

      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="kpi-card"><span className="text-xs text-gray-500">Tour có giá</span><p className="text-xl font-bold">{data.totals.tours}</p></div>
          <div className="kpi-card"><span className="text-xs text-gray-500">Lượt KH/tháng (TT)</span><p className="text-xl font-bold">{Math.round(data.totals.departure_monthly)}</p></div>
          <div className="kpi-card"><span className="text-xs text-gray-500">Giá TB ngày TT</span><p className="text-xl font-bold">{fmtVND(data.market_avg.avg_price_day)}</p></div>
          <div className="kpi-card"><span className="text-xs text-gray-500">Giá TT (ngày×ngày TB)</span><p className="text-xl font-bold">{fmtVND(data.market_avg.market_price)}</p></div>
        </div>
      )}

      <div className="flex gap-2 border-b border-gray-200">
        {([
          { id: "departures" as const, label: "Tần suất KH / Đoàn", icon: Calendar },
          { id: "price" as const, label: "Giá thị trường", icon: DollarSign },
          { id: "routes" as const, label: "Theo tuyến", icon: Info },
        ]).map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px flex items-center gap-1.5 ${tab === id ? "border-primary-600 text-primary-600" : "border-transparent text-gray-500"}`}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {tab === "departures" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="card p-5">
            <h3 className="font-semibold text-gray-800 mb-4">Lượt khởi hành/tháng theo Thị trường</h3>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={departureChart} layout="vertical" margin={{ left: 100 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis dataKey="label" type="category" tick={{ fontSize: 10 }} width={100} />
                <Tooltip formatter={(v: number, _n, p: any) => [`${Math.round(v)} lượt (${p.payload.share}%)`, "Số đoàn/th"]} />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {departureChart.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="card overflow-auto max-h-[400px]">
            <div className="px-4 py-3 border-b font-semibold text-sm">Top công ty — Thị phần số đoàn</div>
            <table className="w-full text-xs">
              <thead className="bg-gray-50 sticky top-0"><tr>
                {["Công ty", "Tour", "Lượt KH/th", "Thị phần %"].map((h) => <th key={h} className="px-3 py-2 text-left">{h}</th>)}
              </tr></thead>
              <tbody>
                {(data?.companies ?? []).slice(0, 20).map((c) => (
                  <tr key={c.label} className={`border-t ${c.is_vietravel ? "bg-blue-50 font-medium" : ""}`}>
                    <td className="px-3 py-2">{c.label}</td>
                    <td className="px-3 py-2">{c.tour_count}</td>
                    <td className="px-3 py-2">{Math.round(c.departure_monthly)}</td>
                    <td className="px-3 py-2">{c.departure_share_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "price" && (
        <div className="card overflow-auto">
          <div className="px-4 py-3 border-b font-semibold text-sm">Giá trung bình thị trường theo từng thị trường</div>
          <table className="w-full text-xs">
            <thead className="bg-gray-50 sticky top-0"><tr>
              {["Thị trường", "Tour", "Lượt KH/th", "Giá TB tour", "Ngày TB", "Giá TB/ngày", "Giá TT"].map((h) => (
                <th key={h} className="px-3 py-2 text-left font-semibold text-gray-600">{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {(data?.markets ?? []).map((m) => (
                <tr key={m.label} className="border-t hover:bg-gray-50">
                  <td className="px-3 py-2 font-medium">{m.label}</td>
                  <td className="px-3 py-2">{m.tour_count}</td>
                  <td className="px-3 py-2">{Math.round(m.departure_monthly)}</td>
                  <td className="px-3 py-2">{fmtVND(m.avg_price)}</td>
                  <td className="px-3 py-2">{m.avg_days ? `${m.avg_days}N` : "—"}</td>
                  <td className="px-3 py-2">{fmtVND(m.avg_price_day)}</td>
                  <td className="px-3 py-2 font-medium">{fmtVND(m.market_price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-gray-400 p-3">Giá TT = Giá TB ngày × Số ngày TB (có trọng số theo lượt KH)</p>
        </div>
      )}

      {tab === "routes" && (
        <div className="card overflow-auto max-h-[520px]">
          <div className="px-4 py-3 border-b font-semibold text-sm">Top tuyến tour — Giá & tần suất KH</div>
          <table className="w-full text-xs">
            <thead className="bg-gray-50 sticky top-0"><tr>
              {["Thị trường", "Tuyến", "Tour", "Lượt KH/th", "Giá TB", "Giá TT"].map((h) => (
                <th key={h} className="px-3 py-2 text-left">{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {(data?.routes ?? []).map((r) => (
                <tr key={`${r.thi_truong}-${r.tuyen_tour}`} className="border-t">
                  <td className="px-3 py-2">{r.thi_truong}</td>
                  <td className="px-3 py-2 max-w-[200px] truncate" title={r.tuyen_tour}>{r.tuyen_tour}</td>
                  <td className="px-3 py-2">{r.tour_count}</td>
                  <td className="px-3 py-2">{Math.round(r.departure_monthly)}</td>
                  <td className="px-3 py-2">{fmtVND(r.avg_price)}</td>
                  <td className="px-3 py-2">{fmtVND(r.market_price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && (
        <div className="card p-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div className="bg-blue-50 rounded-lg p-4">
            <h4 className="font-semibold text-blue-900">Vietravel</h4>
            <p className="text-xs text-blue-700 mt-2">Tour: {data.vietravel.tour_count} · Lượt KH/th: {Math.round(data.vietravel.departure_monthly)}</p>
            <p className="text-xs text-blue-700">Giá TB: {fmtVND(data.vietravel.avg_price)} · Giá TT: {fmtVND(data.vietravel.market_price)}</p>
          </div>
          <div className="bg-gray-50 rounded-lg p-4">
            <h4 className="font-semibold">Toàn thị trường (TB)</h4>
            <p className="text-xs text-gray-600 mt-2">Tour: {data.market_avg.tour_count} · Lượt KH/th: {Math.round(data.market_avg.departure_monthly)}</p>
            <p className="text-xs text-gray-600">Giá TB: {fmtVND(data.market_avg.avg_price)} · Giá TT: {fmtVND(data.market_avg.market_price)}</p>
          </div>
        </div>
      )}
    </div>
  );
}
