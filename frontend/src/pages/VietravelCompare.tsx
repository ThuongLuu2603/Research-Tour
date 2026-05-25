import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine,
} from "recharts";
import { getCompareSummary, getCompareSegments, getSegmentTours, getFilterOptions } from "@/lib/api";
import { fmtVND, cn } from "@/lib/utils";
import { TrendingDown, TrendingUp, Minus, Info } from "lucide-react";

function GapBadge({ pct }: { pct: number | null }) {
  if (pct === null) return <span className="badge bg-gray-100">N/A</span>;
  if (pct <= -5) return <span className="badge bg-green-100 text-green-800 flex items-center gap-1"><TrendingDown size={12} /> {pct}%</span>;
  if (pct >= 5) return <span className="badge bg-red-100 text-red-800 flex items-center gap-1"><TrendingUp size={12} /> +{pct}%</span>;
  return <span className="badge bg-blue-100 text-blue-800 flex items-center gap-1"><Minus size={12} /> {pct}%</span>;
}

export default function VietravelCompare() {
  const [thiTruong, setThiTruong] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const filters = thiTruong ? { thi_truong: [thiTruong] } : {};

  const { data: filterOpts } = useQuery({
    queryKey: ["filter-options"],
    queryFn: getFilterOptions,
  });

  const { data: summary } = useQuery({
    queryKey: ["compare-summary", thiTruong],
    queryFn: () => getCompareSummary(filters),
  });

  const { data: segments } = useQuery({
    queryKey: ["compare-segments", thiTruong],
    queryFn: () => getCompareSegments({ ...filters, sort_by: "gap_pct", limit: 200 }),
  });

  const { data: detail } = useQuery({
    queryKey: ["segment-tours", selectedKey],
    queryFn: () => getSegmentTours(selectedKey!),
    enabled: !!selectedKey,
  });

  const chartData = (segments?.items ?? [])
    .filter((s) => s.gap_pct !== null)
    .slice(0, 15)
    .map((s) => ({
      name: `${s.tuyen_tour.slice(0, 20)}… (${s.diem_kh}, ${s.so_ngay}N)`,
      gap: s.gap_pct,
      vtr: s.vietravel_avg_day,
      mkt: s.market_avg_day,
    }));

  return (
    <div className="p-6 space-y-6">
      <div className="bg-gradient-to-r from-primary-600 to-primary-500 rounded-xl p-5 text-white">
        <h1 className="text-xl font-bold">So sánh Vietravel vs Thị trường</h1>
        <p className="text-blue-100 text-sm mt-1">
          Giá/ngày chuẩn hóa theo cùng Tuyến tour + Điểm khởi hành + Số ngày
        </p>
      </div>

      <div className="card p-4 flex items-start gap-3 bg-blue-50 border-blue-200 text-sm text-blue-900">
        <Info size={18} className="shrink-0 mt-0.5" />
        <div>
          <p className="font-medium">Phương pháp so sánh (giá trung bình/ngày)</p>
          <p className="text-blue-800 mt-1">{segments?.methodology}</p>
          <p className="text-xs text-blue-700 mt-2">
            Chênh lệch % = (Giá VTR/ngày ÷ Giá thị trường/ngày − 1) × 100. Âm = Vietravel rẻ hơn.
          </p>
        </div>
      </div>

      <div className="flex gap-3 flex-wrap">
        <select className="input w-48 text-sm" value={thiTruong} onChange={(e) => setThiTruong(e.target.value)}>
          <option value="">Tất cả thị trường</option>
          {(filterOpts?.thi_truong ?? []).map((m: string) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>

      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <div className="kpi-card"><span className="text-xs text-gray-500">Tour Vietravel</span><p className="text-2xl font-bold">{summary.total_vietravel_tours}</p></div>
          <div className="kpi-card"><span className="text-xs text-gray-500">Segment so sánh</span><p className="text-2xl font-bold">{summary.segments_with_vietravel}</p></div>
          <div className="kpi-card"><span className="text-xs text-green-600">Rẻ hơn TT</span><p className="text-2xl font-bold text-green-700">{summary.cheaper_count}</p></div>
          <div className="kpi-card"><span className="text-xs text-red-600">Đắt hơn TT</span><p className="text-2xl font-bold text-red-700">{summary.expensive_count}</p></div>
          <div className="kpi-card"><span className="text-xs text-gray-500">Chênh TB</span><p className="text-2xl font-bold">{summary.avg_gap_pct != null ? `${summary.avg_gap_pct}%` : "—"}</p></div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card p-5">
          <h3 className="font-semibold mb-4">Top 15 segment — Chênh lệch giá/ngày (%)</h3>
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={chartData} layout="vertical" margin={{ left: 10 }}>
              <XAxis type="number" tickFormatter={(v) => `${v}%`} />
              <YAxis dataKey="name" type="category" width={140} tick={{ fontSize: 10 }} />
              <Tooltip formatter={(v: number) => [`${v}%`, "Chênh lệch"]} />
              <ReferenceLine x={0} stroke="#666" />
              <Bar dataKey="gap" radius={[0, 4, 4, 0]}>
                {chartData.map((e, i) => (
                  <Cell key={i} fill={(e.gap ?? 0) <= 0 ? "#16a34a" : "#dc2626"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card overflow-auto max-h-[420px]">
          <div className="px-4 py-3 border-b font-semibold text-sm sticky top-0 bg-white">
            Bảng so sánh ({segments?.total ?? 0} segment)
          </div>
          <table className="w-full text-xs">
            <thead className="bg-gray-50 sticky top-10">
              <tr>
                {["Tuyến tour", "Điểm KH", "Ngày", "VTR/ngày", "TT/ngày", "Chênh %", ""].map((h) => (
                  <th key={h} className="px-2 py-2 text-left font-semibold text-gray-600">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(segments?.items ?? []).map((s) => (
                <tr
                  key={s.segment_key}
                  className={cn("border-t hover:bg-blue-50 cursor-pointer", selectedKey === s.segment_key && "bg-blue-50")}
                  onClick={() => setSelectedKey(s.segment_key)}
                >
                  <td className="px-2 py-2 max-w-[140px] truncate" title={s.tuyen_tour}>{s.tuyen_tour}</td>
                  <td className="px-2 py-2">{s.diem_kh}</td>
                  <td className="px-2 py-2">{s.so_ngay}N</td>
                  <td className="px-2 py-2 font-medium">{fmtVND(s.vietravel_avg_day)}</td>
                  <td className="px-2 py-2">{fmtVND(s.market_avg_day)}</td>
                  <td className="px-2 py-2"><GapBadge pct={s.gap_pct} /></td>
                  <td className="px-2 py-2 text-gray-400">{s.position}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selectedKey && detail && (
        <div className="card p-5">
          <h3 className="font-semibold mb-3">Chi tiết segment</h3>
          <p className="text-xs text-gray-500 mb-3 font-mono">{selectedKey}</p>
          <table className="w-full text-sm">
            <thead><tr className="border-b text-xs text-gray-500">
              <th className="text-left py-2">Công ty</th><th className="text-left py-2">Tour</th>
              <th className="text-right py-2">Giá</th><th className="text-right py-2">Giá/ngày</th>
            </tr></thead>
            <tbody>
              {detail.tours.map((t) => (
                <tr key={t.id} className={cn("border-t", t.is_vietravel && "bg-blue-50 font-medium")}>
                  <td className="py-2">{t.cong_ty}</td>
                  <td className="py-2 max-w-md truncate">{t.ten_tour}</td>
                  <td className="py-2 text-right">{t.gia_raw || fmtVND(t.gia)}</td>
                  <td className="py-2 text-right">{fmtVND(t.gia_per_day)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
