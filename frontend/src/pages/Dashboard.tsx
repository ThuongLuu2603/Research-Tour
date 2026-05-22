import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, PieChart, Pie, Cell, ScatterChart, Scatter,
  XAxis, YAxis, Tooltip, ResponsiveContainer, Legend
} from "recharts";
import { getKPI, getByMarket, getByCompany, getBySegment, getScatterData } from "@/lib/api";
import { fmtVND } from "@/lib/utils";
import { TrendingUp, Building2, Map, Navigation } from "lucide-react";

const COLORS = ["#003580","#0057b8","#1a75d2","#3d8ee6","#66aaf5","#99c4f8","#bbdafb","#d1e9fe","#e8f4ff","#f0f8ff","#c7dffc","#94c5f8","#5ba8f5","#3091f2","#1178e5","#0062c8"];

function KpiCard({ label, value, icon: Icon, color }: { label: string; value: string | number; icon: any; color: string }) {
  return (
    <div className="kpi-card">
      <div className="flex items-center justify-between">
        <span className="text-sm text-gray-500 font-medium">{label}</span>
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${color}`}>
          <Icon size={18} className="text-white" />
        </div>
      </div>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
    </div>
  );
}

export default function Dashboard() {
  const { data: kpi } = useQuery({ queryKey: ["kpi"], queryFn: () => getKPI() });
  const { data: markets } = useQuery({ queryKey: ["by-market"], queryFn: () => getByMarket() });
  const { data: companies } = useQuery({ queryKey: ["by-company"], queryFn: () => getByCompany() });
  const { data: segments } = useQuery({ queryKey: ["by-segment"], queryFn: () => getBySegment() });
  const { data: scatter } = useQuery({ queryKey: ["scatter"], queryFn: () => getScatterData() });

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="bg-gradient-to-r from-primary-600 to-primary-500 rounded-xl p-5 text-white">
        <h1 className="text-xl font-bold">Dashboard Tổng Quan</h1>
        <p className="text-blue-100 text-sm mt-1">
          Dữ liệu tour OTA — Vietravel · FindTourGo · Tổng hợp thị trường
          {kpi?.last_updated && <span className="ml-2 opacity-70">· Cập nhật: {kpi.last_updated}</span>}
        </p>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="Tổng tour" value={(kpi?.total_tours ?? 0).toLocaleString("vi-VN")} icon={TrendingUp} color="bg-blue-500" />
        <KpiCard label="Công ty LH" value={kpi?.total_companies ?? 0} icon={Building2} color="bg-purple-500" />
        <KpiCard label="Thị trường" value={kpi?.total_markets ?? 0} icon={Map} color="bg-emerald-500" />
        <KpiCard label="Tuyến tour" value={kpi?.total_routes ?? 0} icon={Navigation} color="bg-amber-500" />
      </div>

      {/* Charts row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Market bar */}
        <div className="card p-5 lg:col-span-2">
          <h3 className="font-semibold text-gray-800 mb-4">Số tour theo Thị trường</h3>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={markets ?? []} layout="vertical" margin={{ left: 100 }}>
              <XAxis type="number" tick={{ fontSize: 12 }} />
              <YAxis dataKey="label" type="category" tick={{ fontSize: 12 }} width={100} />
              <Tooltip formatter={(v: number) => v.toLocaleString("vi-VN")} />
              <Bar dataKey="value" fill="#003580" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Segment pie */}
        <div className="card p-5">
          <h3 className="font-semibold text-gray-800 mb-4">Phân khúc giá</h3>
          <ResponsiveContainer width="100%" height={280}>
            <PieChart>
              <Pie data={segments ?? []} dataKey="value" nameKey="label" cx="50%" cy="50%" outerRadius={90} label={({ label, percent }) => `${(percent * 100).toFixed(0)}%`} labelLine={false}>
                {(segments ?? []).map((_: any, i: number) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
              <Tooltip />
              <Legend formatter={(v) => <span className="text-xs">{v}</span>} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Charts row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Top companies */}
        <div className="card p-5">
          <h3 className="font-semibold text-gray-800 mb-4">Top 15 Công ty lữ hành</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={(companies ?? []).slice(0, 15)} layout="vertical" margin={{ left: 180 }}>
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis dataKey="label" type="category" tick={{ fontSize: 11 }} width={180} />
              <Tooltip formatter={(v: number) => v.toLocaleString("vi-VN")} />
              <Bar dataKey="value" fill="#1a75d2" radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Scatter giá × ngày */}
        <div className="card p-5">
          <h3 className="font-semibold text-gray-800 mb-4">Tương quan Giá × Số ngày</h3>
          <p className="text-xs text-gray-500 mb-3">Nhấn vào điểm để xem chi tiết</p>
          <ResponsiveContainer width="100%" height={300}>
            <ScatterChart>
              <XAxis dataKey="so_ngay" name="Số ngày" tick={{ fontSize: 11 }} label={{ value: "Ngày", position: "insideBottom", offset: -5, fontSize: 12 }} />
              <YAxis dataKey="gia" name="Giá" tickFormatter={(v) => `${(v / 1e6).toFixed(0)}tr`} tick={{ fontSize: 11 }} />
              <Tooltip
                cursor={{ strokeDasharray: "3 3" }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0].payload;
                  return (
                    <div className="bg-white border border-gray-200 rounded-lg p-3 shadow text-xs max-w-xs">
                      <p className="font-semibold text-gray-800 mb-1 line-clamp-2">{d.ten_tour}</p>
                      <p className="text-gray-600">{d.cong_ty}</p>
                      <p className="text-primary-600 font-medium">{fmtVND(d.gia)} VND · {d.so_ngay}N</p>
                    </div>
                  );
                }}
              />
              <Scatter data={scatter ?? []} fill="#003580" opacity={0.6} />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
