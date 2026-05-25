import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";
import { getMarketIntelligence } from "@/lib/api";
import { fmtVND } from "@/lib/utils";
import { COL, GLOSSARY } from "@/lib/glossary";
import { InfoTip, PageTitle, ThTip } from "@/components/InfoTip";
import { Calendar, DollarSign, MapPin } from "lucide-react";

const COLORS = ["#003580","#1a75d2","#3d8ee6","#66aaf5","#99c4f8","#bbdafb","#d1e9fe","#e8f4ff","#c7dffc","#94c5f8","#5ba8f5","#3091f2","#1178e5","#0062c8","#0050b0"];

export default function MarketShare() {
  const [tab, setTab] = useState<"departures" | "price" | "routes">("departures");
  const { data } = useQuery({
    queryKey: ["market-intelligence"],
    queryFn: () => getMarketIntelligence(),
  });

  const departureChart = (data?.markets ?? []).slice(0, 15).map((m) => ({
    label: m.label.length > 18 ? m.label.slice(0, 18) + "…" : m.label,
    value: m.departure_monthly,
    share: m.departure_share_pct,
  }));

  return (
    <div className="p-6 space-y-6">
      <div>
        <PageTitle title="Phân tích Thị trường" tip={GLOSSARY.methodologyMarket} />
        <p className="text-sm text-gray-500 mt-1">Theo sản phẩm tour · trọng số theo số đoàn khởi hành</p>
      </div>

      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="kpi-card">
            <span className="text-xs text-gray-500 inline-flex items-center">{COL.sanPham}<InfoTip text={GLOSSARY.tenTour} /></span>
            <p className="text-xl font-bold">{data.totals.tours.toLocaleString("vi-VN")}</p>
          </div>
          <div className="kpi-card">
            <span className="text-xs text-gray-500 inline-flex items-center">{COL.doanThang}<InfoTip text={GLOSSARY.doanThang} /></span>
            <p className="text-xl font-bold">{Math.round(data.totals.departure_monthly).toLocaleString("vi-VN")}</p>
          </div>
          <div className="kpi-card">
            <span className="text-xs text-gray-500 inline-flex items-center">{COL.tbDoanThang}<InfoTip text={GLOSSARY.tbDoanThang} /></span>
            <p className="text-xl font-bold">{data.totals.avg_departures_per_month ?? "—"}</p>
          </div>
          <div className="kpi-card">
            <span className="text-xs text-gray-500 inline-flex items-center">{COL.giaThiTruong}<InfoTip text={GLOSSARY.giaThiTruong} /></span>
            <p className="text-xl font-bold">{fmtVND(data.market_avg.market_price)}</p>
          </div>
        </div>
      )}

      <div className="flex gap-2 border-b border-gray-200">
        {([
          { id: "departures" as const, label: "Tần suất khởi hành", icon: Calendar, tip: GLOSSARY.tanSuat },
          { id: "price" as const, label: "Giá thị trường", icon: DollarSign, tip: GLOSSARY.giaTbTour },
          { id: "routes" as const, label: "Theo tuyến tour", icon: MapPin, tip: GLOSSARY.tuyenTour },
        ]).map(({ id, label, icon: Icon, tip }) => (
          <button key={id} onClick={() => setTab(id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px flex items-center gap-1.5 ${tab === id ? "border-primary-600 text-primary-600" : "border-transparent text-gray-500"}`}>
            <Icon size={14} /> {label}
            <InfoTip text={tip} />
          </button>
        ))}
      </div>

      {tab === "departures" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="card p-5">
            <h3 className="font-semibold text-gray-800 mb-4 inline-flex items-center">
              Tổng đoàn/tháng theo {COL.thiTruong}
              <InfoTip text={GLOSSARY.doanThang} />
            </h3>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={departureChart} layout="vertical" margin={{ left: 100 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis dataKey="label" type="category" tick={{ fontSize: 10 }} width={100} />
                <Tooltip formatter={(v: number, _n, p: any) => [`${Math.round(v)} đoàn (${p.payload.share}%)`, COL.doanThang]} />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {departureChart.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="card overflow-auto max-h-[400px]">
            <div className="px-4 py-3 border-b font-semibold text-sm inline-flex items-center">
              Top {COL.congTy} — {COL.thiPhanDoan}
              <InfoTip text={GLOSSARY.thiPhanDoan} />
            </div>
            <table className="w-full text-xs">
              <thead className="bg-gray-50 sticky top-0"><tr>
                <th className="px-3 py-2 text-left"><ThTip label={COL.congTy} tip={GLOSSARY.congTy} /></th>
                <th className="px-3 py-2 text-left"><ThTip label={COL.sanPham} tip={GLOSSARY.tenTour} /></th>
                <th className="px-3 py-2 text-left"><ThTip label={COL.doanThang} tip={GLOSSARY.doanThang} /></th>
                <th className="px-3 py-2 text-left"><ThTip label="Thị phần" tip={GLOSSARY.thiPhanDoan} /></th>
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
          <div className="px-4 py-3 border-b font-semibold text-sm">Giá trung bình theo {COL.thiTruong}</div>
          <table className="w-full text-xs">
            <thead className="bg-gray-50 sticky top-0"><tr>
              {[
                [COL.thiTruong, GLOSSARY.thiTruong],
                [COL.sanPham, GLOSSARY.tenTour],
                [COL.tbDoanThang, GLOSSARY.tbDoanThang],
                [COL.giaTbTour, GLOSSARY.giaTbTour],
                [COL.ngayTb, GLOSSARY.thoiGian],
                [COL.giaTbNgay, GLOSSARY.giaTbNgay],
                [COL.giaThiTruong, GLOSSARY.giaThiTruong],
              ].map(([label, tip]) => (
                <th key={label} className="px-3 py-2 text-left font-semibold text-gray-600">
                  <ThTip label={label} tip={tip} />
                </th>
              ))}
            </tr></thead>
            <tbody>
              {(data?.markets ?? []).map((m) => (
                <tr key={m.label} className="border-t hover:bg-gray-50">
                  <td className="px-3 py-2 font-medium">{m.label}</td>
                  <td className="px-3 py-2">{m.tour_count}</td>
                  <td className="px-3 py-2">{m.avg_departures_per_month ?? "—"}</td>
                  <td className="px-3 py-2">{fmtVND(m.avg_price)}</td>
                  <td className="px-3 py-2">{m.avg_days ? `${m.avg_days}N` : "—"}</td>
                  <td className="px-3 py-2">{fmtVND(m.avg_price_day)}</td>
                  <td className="px-3 py-2 font-medium">{fmtVND(m.market_price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "routes" && (
        <div className="card overflow-auto max-h-[520px]">
          <div className="px-4 py-3 border-b font-semibold text-sm">Top {COL.tuyenTour}</div>
          <table className="w-full text-xs">
            <thead className="bg-gray-50 sticky top-0"><tr>
              {[
                [COL.thiTruong, GLOSSARY.thiTruong],
                [COL.tuyenTour, GLOSSARY.tuyenTour],
                [COL.sanPham, GLOSSARY.tenTour],
                [COL.tbDoanThang, GLOSSARY.tbDoanThang],
                [COL.giaTbTour, GLOSSARY.giaTbTour],
                [COL.giaThiTruong, GLOSSARY.giaThiTruong],
              ].map(([label, tip]) => (
                <th key={label} className="px-3 py-2 text-left"><ThTip label={label} tip={tip} /></th>
              ))}
            </tr></thead>
            <tbody>
              {(data?.routes ?? []).map((r) => (
                <tr key={`${r.thi_truong}-${r.tuyen_tour}`} className="border-t">
                  <td className="px-3 py-2">{r.thi_truong}</td>
                  <td className="px-3 py-2 max-w-[200px] truncate" title={r.tuyen_tour}>{r.tuyen_tour}</td>
                  <td className="px-3 py-2">{r.tour_count}</td>
                  <td className="px-3 py-2">{r.avg_departures_per_month ?? "—"}</td>
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
            <h4 className="font-semibold text-blue-900 inline-flex items-center">Vietravel<InfoTip text={GLOSSARY.congTy} /></h4>
            <p className="text-xs text-blue-700 mt-2">{COL.sanPham}: {data.vietravel.tour_count} · {COL.tbDoanThang}: {data.vietravel.avg_departures_per_month ?? "—"}</p>
            <p className="text-xs text-blue-700">{COL.giaTbTour}: {fmtVND(data.vietravel.avg_price)} · {COL.giaThiTruong}: {fmtVND(data.vietravel.market_price)}</p>
          </div>
          <div className="bg-gray-50 rounded-lg p-4">
            <h4 className="font-semibold inline-flex items-center">Thị trường (TB)<InfoTip text={GLOSSARY.giaThiTruong} /></h4>
            <p className="text-xs text-gray-600 mt-2">{COL.sanPham}: {data.market_avg.tour_count} · {COL.tbDoanThang}: {data.market_avg.avg_departures_per_month ?? "—"}</p>
            <p className="text-xs text-gray-600">{COL.giaTbTour}: {fmtVND(data.market_avg.avg_price)} · {COL.giaThiTruong}: {fmtVND(data.market_avg.market_price)}</p>
          </div>
        </div>
      )}
    </div>
  );
}
