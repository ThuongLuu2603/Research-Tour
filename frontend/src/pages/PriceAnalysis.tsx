import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend,
} from "recharts";
import { getPriceStats } from "@/lib/api";
import { fmtVND } from "@/lib/utils";
import { COL, GLOSSARY } from "@/lib/glossary";
import { InfoTip, PageTitle, ThTip } from "@/components/InfoTip";

export default function PriceAnalysis() {
  const [groupBy, setGroupBy] = useState<"thi_truong" | "cong_ty" | "tuyen_tour">("thi_truong");
  const { data: stats } = useQuery({
    queryKey: ["price-stats", groupBy],
    queryFn: () => getPriceStats(groupBy),
  });

  const grouped = (stats ?? []).slice(0, 20);
  const groupLabel = { thi_truong: COL.thiTruong, cong_ty: COL.congTy, tuyen_tour: COL.tuyenTour }[groupBy];

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <PageTitle title="Phân tích Giá" tip={GLOSSARY.methodologyPrice} />
          <p className="text-sm text-gray-500 mt-1">Min · TB robust · Median · Max — có trọng số theo đoàn</p>
        </div>
        <div className="flex gap-2">
          {(["thi_truong", "cong_ty", "tuyen_tour"] as const).map((g) => (
            <button
              key={g}
              onClick={() => setGroupBy(g)}
              className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${groupBy === g ? "bg-primary-600 text-white border-primary-600" : "bg-white text-gray-600 border-gray-300 hover:border-primary-400"}`}
            >
              {{ thi_truong: COL.thiTruong, cong_ty: COL.congTy, tuyen_tour: COL.tuyenTour }[g]}
            </button>
          ))}
        </div>
      </div>

      <div className="card p-5">
        <h3 className="font-semibold text-gray-800 mb-1 inline-flex items-center">
          Giá theo {groupLabel}
          <InfoTip text={GLOSSARY.giaTbTour} />
        </h3>
        <ResponsiveContainer width="100%" height={420}>
          <BarChart data={grouped} layout="vertical" margin={{ left: 180 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" tickFormatter={(v) => `${(v / 1e6).toFixed(0)}tr`} tick={{ fontSize: 11 }} />
            <YAxis dataKey="group" type="category" tick={{ fontSize: 10 }} width={180} />
            <Tooltip formatter={(v: number) => fmtVND(v)} />
            <Legend />
            <Bar dataKey="min_gia" name="Min" fill="#66aaf5" radius={[0, 3, 3, 0]} />
            <Bar dataKey="avg_gia" name="TB (robust)" fill="#003580" radius={[0, 3, 3, 0]} />
            <Bar dataKey="median_gia" name="Median" fill="#1a75d2" radius={[0, 3, 3, 0]} />
            <Bar dataKey="max_gia" name="Max" fill="#3d8ee6" radius={[0, 3, 3, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="card overflow-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600"><ThTip label={groupLabel} /></th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600"><ThTip label={COL.sanPham} tip={GLOSSARY.tenTour} /></th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600"><ThTip label={COL.tbDoanThang} tip={GLOSSARY.tbDoanThang} /></th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600">Min</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600"><ThTip label="TB" tip={GLOSSARY.giaTbTour} /></th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600">Median</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600"><ThTip label={COL.giaTbNgay} tip={GLOSSARY.giaTbNgay} /></th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600">Max</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {(stats ?? []).map((r, i) => (
              <tr key={i} className="hover:bg-blue-50 transition-colors">
                <td className="px-4 py-2.5 text-sm font-medium text-gray-900 max-w-xs truncate" title={r.group}>{r.group}</td>
                <td className="px-4 py-2.5 text-right text-sm text-gray-600">{r.count.toLocaleString("vi-VN")}</td>
                <td className="px-4 py-2.5 text-right text-sm text-gray-600">{r.avg_departures_per_month ?? "—"}</td>
                <td className="px-4 py-2.5 text-right text-sm text-gray-600">{r.min_gia ? fmtVND(r.min_gia) : "—"}</td>
                <td className="px-4 py-2.5 text-right text-sm font-semibold text-primary-600">{r.avg_gia ? fmtVND(r.avg_gia) : "—"}</td>
                <td className="px-4 py-2.5 text-right text-sm text-gray-600">{r.median_gia ? fmtVND(r.median_gia) : "—"}</td>
                <td className="px-4 py-2.5 text-right text-sm text-gray-600">{r.avg_price_day ? fmtVND(r.avg_price_day) : "—"}</td>
                <td className="px-4 py-2.5 text-right text-sm text-gray-600">{r.max_gia ? fmtVND(r.max_gia) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
