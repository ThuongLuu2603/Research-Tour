import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";
import { getByMarket, getByCompany, getBySegment } from "@/lib/api";

const COLORS = ["#003580","#1a75d2","#3d8ee6","#66aaf5","#99c4f8","#bbdafb","#d1e9fe","#e8f4ff","#c7dffc","#94c5f8","#5ba8f5","#3091f2","#1178e5","#0062c8","#0050b0"];

export default function MarketShare() {
  const { data: markets } = useQuery({ queryKey: ["by-market"], queryFn: () => getByMarket() });
  const { data: companies } = useQuery({ queryKey: ["by-company"], queryFn: () => getByCompany() });
  const { data: segments } = useQuery({ queryKey: ["by-segment"], queryFn: () => getBySegment() });

  const total = (markets ?? []).reduce((s: number, r: any) => s + r.value, 0);

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Phân tích Thị trường</h1>
        <p className="text-sm text-gray-500">Thị phần, phân khúc và cơ cấu công ty lữ hành</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Markets */}
        <div className="card p-5">
          <h3 className="font-semibold text-gray-800 mb-4">Số tour theo Thị trường</h3>
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={markets ?? []} layout="vertical" margin={{ left: 100 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis dataKey="label" type="category" tick={{ fontSize: 11 }} width={100} />
              <Tooltip formatter={(v: number) => [`${v.toLocaleString("vi-VN")} tour (${total ? ((v / total) * 100).toFixed(1) : 0}%)`, "Số tour"]} />
              <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                {(markets ?? []).map((_: any, i: number) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Segments */}
        <div className="card p-5">
          <h3 className="font-semibold text-gray-800 mb-4">Phân khúc giá</h3>
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={segments ?? []} margin={{ left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => `${v.toLocaleString("vi-VN")} tour`} />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {(segments ?? []).map((_: any, i: number) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Top companies */}
      <div className="card p-5">
        <h3 className="font-semibold text-gray-800 mb-4">Top 15 Công ty lữ hành — Thị phần số tour</h3>
        <div className="space-y-2">
          {(companies ?? []).slice(0, 15).map((c: any, i: number) => {
            const pct = total ? (c.value / total) * 100 : 0;
            return (
              <div key={c.label} className="flex items-center gap-3">
                <span className="text-xs text-gray-400 w-4">{i + 1}</span>
                <span className="text-xs text-gray-700 w-48 truncate">{c.label}</span>
                <div className="flex-1 h-5 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${Math.max(pct * 4, 2)}%`, backgroundColor: COLORS[i % COLORS.length] }}
                  />
                </div>
                <span className="text-xs font-semibold text-gray-700 w-20 text-right">{c.value} tour</span>
                <span className="text-xs text-gray-400 w-12 text-right">{pct.toFixed(1)}%</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
