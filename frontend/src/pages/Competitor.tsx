import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from "recharts";
import { getByCompany, getCompetitorProfile } from "@/lib/api";
import { fmtVND, cn } from "@/lib/utils";
import { ExternalLink, TrendingUp, TrendingDown, Minus } from "lucide-react";

export default function Competitor() {
  const [selected, setSelected] = useState<string>("");
  const { data: companies } = useQuery({ queryKey: ["by-company", 50], queryFn: () => getByCompany([]) });
  const { data: profile, isFetching } = useQuery({
    queryKey: ["competitor", selected],
    queryFn: () => getCompetitorProfile(selected),
    enabled: !!selected,
  });

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Phân tích Đối thủ</h1>
        <p className="text-sm text-gray-500">Profile công ty · Định vị giá so với thị trường</p>
      </div>

      {/* Company picker */}
      <div className="card p-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">Chọn công ty lữ hành</label>
        <select
          className="input max-w-md"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
        >
          <option value="">— Chọn công ty —</option>
          {(companies ?? []).map((c: any) => (
            <option key={c.label} value={c.label}>{c.label} ({c.value} tour)</option>
          ))}
        </select>
      </div>

      {!selected && (
        <div className="card p-12 text-center text-gray-400">
          <p className="text-4xl mb-3">🏢</p>
          <p className="font-medium">Chọn công ty để xem phân tích</p>
        </div>
      )}

      {selected && isFetching && (
        <div className="card p-12 text-center text-gray-400 animate-pulse">Đang tải...</div>
      )}

      {profile && !isFetching && (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-3 gap-4">
            <div className="kpi-card">
              <span className="text-sm text-gray-500">Tổng tour</span>
              <p className="text-2xl font-bold text-gray-900">{profile.total_tours}</p>
            </div>
            <div className="kpi-card">
              <span className="text-sm text-gray-500">Giá trung bình</span>
              <p className="text-2xl font-bold text-gray-900">{profile.avg_price ? `${fmtVND(profile.avg_price)}` : "—"}</p>
            </div>
            <div className="kpi-card">
              <span className="text-sm text-gray-500">Thị trường chính</span>
              <p className="text-lg font-bold text-gray-900">{profile.markets?.[0]?.label ?? "—"}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Market breakdown */}
            <div className="card p-5">
              <h3 className="font-semibold text-gray-800 mb-4">Phân bổ thị trường</h3>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={profile.markets} layout="vertical" margin={{ left: 120 }}>
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis dataKey="label" type="category" tick={{ fontSize: 11 }} width={120} />
                  <Tooltip />
                  <Bar dataKey="value" fill="#003580" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Price positioning */}
            <div className="card p-5">
              <h3 className="font-semibold text-gray-800 mb-1">Định vị giá (% so với TB tuyến)</h3>
              <p className="text-xs text-gray-400 mb-4">Dương = cao hơn thị trường, Âm = thấp hơn</p>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={profile.route_positioning?.slice(0, 12)} layout="vertical" margin={{ left: 160 }}>
                  <XAxis type="number" tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11 }} />
                  <YAxis dataKey="route" type="category" tick={{ fontSize: 10 }} width={160} />
                  <ReferenceLine x={0} stroke="#9ca3af" />
                  <Tooltip formatter={(v: number) => `${v > 0 ? "+" : ""}${v}%`} />
                  <Bar dataKey="diff_pct" radius={[0, 4, 4, 0]}>
                    {(profile.route_positioning ?? []).slice(0, 12).map((r: any, i: number) => (
                      <Cell key={i} fill={r.diff_pct > 0 ? "#ef4444" : "#22c55e"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Tour list */}
          <div className="card overflow-auto">
            <div className="px-5 py-3 border-b border-gray-200 flex items-center justify-between">
              <h3 className="font-semibold text-gray-800">Danh sách tour ({profile.tours?.length})</h3>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  {["Tên Tour", "Thị trường", "Tuyến", "Giá", "Link"].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {(profile.tours ?? []).map((t: any) => (
                  <tr key={t.id} className="hover:bg-blue-50 transition-colors">
                    <td className="px-4 py-2.5 text-xs max-w-xs">
                      <span className="line-clamp-2 font-medium">{t.ten_tour}</span>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-600">{t.thi_truong}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-600 max-w-[140px] truncate">{t.tuyen_tour}</td>
                    <td className="px-4 py-2.5 text-xs font-medium text-gray-900 whitespace-nowrap">
                      {t.gia ? `${fmtVND(t.gia)}` : t.gia_raw || "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      {t.link_url && (
                        <a href={t.link_url} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:text-primary-800">
                          <ExternalLink size={14} />
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
