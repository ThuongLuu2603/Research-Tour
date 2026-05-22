import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend, Cell
} from "recharts";
import { getPriceStats } from "@/lib/api";
import { fmtVND } from "@/lib/utils";

const COLORS = ["#003580","#1a75d2","#3d8ee6","#66aaf5","#99c4f8","#bbdafb","#e8f4ff","#c7dffc","#94c5f8","#5ba8f5","#3091f2","#1178e5","#0062c8","#0050b0","#003f99"];

export default function PriceAnalysis() {
  const [groupBy, setGroupBy] = useState<"thi_truong" | "cong_ty" | "tuyen_tour">("thi_truong");
  const { data: stats } = useQuery({
    queryKey: ["price-stats", groupBy],
    queryFn: () => getPriceStats(groupBy),
  });

  const grouped = (stats ?? []).slice(0, 20);
  const groupLabel = { thi_truong: "Thị trường", cong_ty: "Công ty", tuyen_tour: "Tuyến tour" }[groupBy];

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Phân tích Giá</h1>
          <p className="text-sm text-gray-500">So sánh giá Min / Avg / Max theo nhóm</p>
        </div>
        <div className="flex gap-2">
          {(["thi_truong", "cong_ty", "tuyen_tour"] as const).map((g) => (
            <button
              key={g}
              onClick={() => setGroupBy(g)}
              className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${groupBy === g ? "bg-primary-600 text-white border-primary-600" : "bg-white text-gray-600 border-gray-300 hover:border-primary-400"}`}
            >
              {{ thi_truong: "Thị trường", cong_ty: "Công ty", tuyen_tour: "Tuyến" }[g]}
            </button>
          ))}
        </div>
      </div>

      {/* Min/Max/Avg grouped bar */}
      <div className="card p-5">
        <h3 className="font-semibold text-gray-800 mb-1">Giá Min / Trung bình / Max theo {groupLabel}</h3>
        <p className="text-xs text-gray-400 mb-4">Đơn vị: triệu VND</p>
        <ResponsiveContainer width="100%" height={420}>
          <BarChart data={grouped} layout="vertical" margin={{ left: 180 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" tickFormatter={(v) => `${(v / 1e6).toFixed(0)}tr`} tick={{ fontSize: 11 }} />
            <YAxis dataKey="group" type="category" tick={{ fontSize: 11 }} width={180} />
            <Tooltip formatter={(v: number) => `${fmtVND(v)} VND`} />
            <Legend />
            <Bar dataKey="min_gia" name="Min" fill="#66aaf5" radius={[0, 3, 3, 0]} />
            <Bar dataKey="avg_gia" name="Trung bình" fill="#003580" radius={[0, 3, 3, 0]} />
            <Bar dataKey="max_gia" name="Max" fill="#1a75d2" radius={[0, 3, 3, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Price stats table */}
      <div className="card overflow-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">{groupLabel}</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600">Số tour</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600">Min</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600">Trung bình</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600">Max</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {(stats ?? []).map((r: any, i: number) => (
              <tr key={i} className="hover:bg-blue-50 transition-colors">
                <td className="px-4 py-2.5 text-sm font-medium text-gray-900">{r.group}</td>
                <td className="px-4 py-2.5 text-right text-sm text-gray-600">{r.count.toLocaleString("vi-VN")}</td>
                <td className="px-4 py-2.5 text-right text-sm text-gray-600">{r.min_gia ? `${fmtVND(r.min_gia)}` : "—"}</td>
                <td className="px-4 py-2.5 text-right text-sm font-semibold text-primary-600">{r.avg_gia ? `${fmtVND(r.avg_gia)}` : "—"}</td>
                <td className="px-4 py-2.5 text-right text-sm text-gray-600">{r.max_gia ? `${fmtVND(r.max_gia)}` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
