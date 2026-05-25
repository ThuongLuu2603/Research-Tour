import { useState, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine,
  ScatterChart, Scatter, ZAxis, Legend,
} from "recharts";
import {
  getCompareSummary, getCompareSegments, getSegmentDetail,
  getCompareCompetitors, getCompareCompetitorDetail, getFilterOptions,
  CompareSegment,
} from "@/lib/api";
import { fmtVND, cn } from "@/lib/utils";
import {
  TrendingDown, TrendingUp, Minus, Info, ExternalLink, Calendar, Building2,
} from "lucide-react";

type Tab = "overview" | "price" | "frequency" | "competitors";

function GapBadge({ pct }: { pct: number | null }) {
  if (pct === null) return <span className="badge bg-gray-100">N/A</span>;
  if (pct <= -5) return <span className="badge bg-green-100 text-green-800 flex items-center gap-1"><TrendingDown size={12} /> {pct}%</span>;
  if (pct >= 5) return <span className="badge bg-red-100 text-red-800 flex items-center gap-1"><TrendingUp size={12} /> +{pct}%</span>;
  return <span className="badge bg-blue-100 text-blue-800 flex items-center gap-1"><Minus size={12} /> {pct}%</span>;
}

function FreqBadge({ pct }: { pct: number | null }) {
  if (pct === null) return <span className="badge bg-gray-100">N/A</span>;
  if (pct >= 20) return <span className="badge bg-emerald-100 text-emerald-800">+{pct}% đoàn</span>;
  if (pct <= -20) return <span className="badge bg-amber-100 text-amber-800">{pct}% đoàn</span>;
  return <span className="badge bg-gray-100 text-gray-700">{pct}%</span>;
}

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Tổng quan" },
  { id: "price", label: "So sánh giá" },
  { id: "frequency", label: "Tần suất KH" },
  { id: "competitors", label: "Đối thủ" },
];

export default function VietravelCompare() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "overview";
  const setTab = (t: Tab) => setParams({ tab: t });

  const [thiTruong, setThiTruong] = useState("");
  const [tuyenTour, setTuyenTour] = useState("");
  const [diemKh, setDiemKh] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [selectedCompetitor, setSelectedCompetitor] = useState("");

  const filters = useMemo(() => ({
    ...(thiTruong ? { thi_truong: [thiTruong] } : {}),
    ...(tuyenTour ? { tuyen_tour: tuyenTour } : {}),
    ...(diemKh ? { diem_kh: diemKh } : {}),
  }), [thiTruong, tuyenTour, diemKh]);

  const { data: filterOpts } = useQuery({ queryKey: ["filter-options"], queryFn: getFilterOptions });
  const { data: summary } = useQuery({ queryKey: ["compare-summary", filters], queryFn: () => getCompareSummary(filters) });
  const { data: segments } = useQuery({
    queryKey: ["compare-segments", filters, tab],
    queryFn: () => getCompareSegments({
      ...filters,
      sort_by: tab === "frequency" ? "freq_gap_pct" : "gap_pct",
      limit: 300,
    }),
  });
  const { data: competitors } = useQuery({
    queryKey: ["compare-competitors", filters],
    queryFn: () => getCompareCompetitors(filters),
  });
  const { data: compDetail } = useQuery({
    queryKey: ["compare-competitor-detail", selectedCompetitor, filters],
    queryFn: () => getCompareCompetitorDetail(selectedCompetitor, filters),
    enabled: !!selectedCompetitor,
  });
  const { data: detail } = useQuery({
    queryKey: ["segment-detail", selectedKey],
    queryFn: () => getSegmentDetail(selectedKey!),
    enabled: !!selectedKey,
  });

  const priceChart = (segments?.items ?? []).filter((s) => s.gap_pct != null).slice(0, 12).map((s) => ({
    name: `${s.tuyen_tour.slice(0, 18)} (${s.diem_kh})`,
    gap: s.gap_pct,
  }));

  const freqChart = (segments?.items ?? []).filter((s) => s.freq_gap_pct != null).slice(0, 12).map((s) => ({
    name: `${s.tuyen_tour.slice(0, 18)} (${s.diem_kh})`,
    gap: s.freq_gap_pct,
    vtr: s.vietravel_freq_monthly,
    mkt: s.market_freq_avg_per_company,
  }));

  const scatterData = (segments?.items ?? [])
    .filter((s) => s.vietravel_avg_day && s.market_avg_day)
    .slice(0, 80)
    .map((s) => ({
      x: s.market_avg_day,
      y: s.vietravel_avg_day,
      z: s.vietravel_freq_monthly,
      name: s.tuyen_tour,
    }));

  const SegmentTable = ({ cols, sortKey }: { cols: string[]; sortKey?: string }) => (
    <div className="card overflow-auto max-h-[480px]">
      <table className="w-full text-xs">
        <thead className="bg-gray-50 sticky top-0">
          <tr>
            {cols.map((h) => <th key={h} className="px-2 py-2 text-left font-semibold text-gray-600">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {(segments?.items ?? []).map((s: CompareSegment) => (
            <tr
              key={s.segment_key}
              className={cn("border-t hover:bg-blue-50 cursor-pointer", selectedKey === s.segment_key && "bg-blue-50")}
              onClick={() => setSelectedKey(s.segment_key)}
            >
              <td className="px-2 py-2">{s.thi_truong}</td>
              <td className="px-2 py-2 max-w-[120px] truncate" title={s.tuyen_tour}>{s.tuyen_tour}</td>
              <td className="px-2 py-2">{s.diem_kh}</td>
              <td className="px-2 py-2">{s.so_ngay}N</td>
              {sortKey !== "freq" ? (
                <>
                  <td className="px-2 py-2 font-medium">{fmtVND(s.vietravel_avg_day)}</td>
                  <td className="px-2 py-2">{fmtVND(s.market_avg_day)}</td>
                  <td className="px-2 py-2"><GapBadge pct={s.gap_pct} /></td>
                </>
              ) : (
                <>
                  <td className="px-2 py-2">{Math.round(s.vietravel_freq_monthly)}</td>
                  <td className="px-2 py-2">{s.market_freq_avg_per_company ?? "—"}</td>
                  <td className="px-2 py-2"><FreqBadge pct={s.freq_gap_pct} /></td>
                </>
              )}
              <td className="px-2 py-2 text-gray-400">{sortKey !== "freq" ? s.position : s.freq_position}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="p-6 space-y-5">
      <div className="bg-gradient-to-r from-primary-600 to-primary-500 rounded-xl p-5 text-white">
        <h1 className="text-xl font-bold">Trung tâm So sánh Vietravel</h1>
        <p className="text-blue-100 text-sm mt-1">Giá/ngày + tần suất khởi hành vs thị trường & đối thủ — cùng tuyến, điểm KH, thời lượng</p>
      </div>

      <div className="card p-4 flex items-start gap-3 bg-blue-50 border-blue-200 text-sm text-blue-900">
        <Info size={18} className="shrink-0 mt-0.5" />
        <div>
          <p className="font-medium">Phương pháp phân tích</p>
          <p className="text-blue-800 mt-1">{summary?.methodology || segments?.methodology}</p>
          <ul className="text-xs text-blue-700 mt-2 list-disc ml-4 space-y-0.5">
            <li>Giá TB có trọng số theo số đoàn/ngày KH ước tính từ lịch khởi hành</li>
            <li>Loại trùng tour theo mã tour / link trước khi tính</li>
            <li>Tần suất: ước tính lượt KH/tháng (Hàng ngày, Theo thứ, ngày cố định…)</li>
          </ul>
        </div>
      </div>

      {/* Filters */}
      <div className="card p-4 flex flex-wrap gap-3 items-end">
        <div>
          <label className="text-xs text-gray-500">Thị trường</label>
          <select className="input w-44 text-sm" value={thiTruong} onChange={(e) => setThiTruong(e.target.value)}>
            <option value="">Tất cả</option>
            {(filterOpts?.thi_truong ?? []).map((m: string) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500">Tuyến tour</label>
          <input className="input w-44 text-sm" placeholder="Tìm tuyến..." value={tuyenTour} onChange={(e) => setTuyenTour(e.target.value)} />
        </div>
        <div>
          <label className="text-xs text-gray-500">Điểm KH</label>
          <input className="input w-36 text-sm" placeholder="TP.HCM..." value={diemKh} onChange={(e) => setDiemKh(e.target.value)} />
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 flex-wrap border-b border-gray-200">
        {TABS.map(({ id, label }) => (
          <button key={id} onClick={() => setTab(id)}
            className={cn("px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              tab === id ? "border-primary-600 text-primary-600" : "border-transparent text-gray-500 hover:text-gray-800")}>
            {label}
          </button>
        ))}
      </div>

      {/* KPIs */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <div className="kpi-card"><span className="text-xs text-gray-500">Tour VTR</span><p className="text-xl font-bold">{summary.total_vietravel_tours}</p></div>
          <div className="kpi-card"><span className="text-xs text-gray-500">Segment</span><p className="text-xl font-bold">{summary.segments_with_vietravel}</p></div>
          <div className="kpi-card"><span className="text-xs text-green-600">Rẻ hơn TT</span><p className="text-xl font-bold text-green-700">{summary.cheaper_count}</p></div>
          <div className="kpi-card"><span className="text-xs text-red-600">Đắt hơn TT</span><p className="text-xl font-bold text-red-700">{summary.expensive_count}</p></div>
          <div className="kpi-card"><span className="text-xs text-gray-500">Chênh giá TB</span><p className="text-xl font-bold">{summary.avg_gap_pct != null ? `${summary.avg_gap_pct}%` : "—"}</p></div>
          <div className="kpi-card"><span className="text-xs text-gray-500">Lượt KH VTR/tháng</span><p className="text-xl font-bold">{Math.round(summary.vtr_freq_monthly_total)}</p></div>
        </div>
      )}

      {tab === "overview" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="card p-5">
            <h3 className="font-semibold mb-3">Giá/ngày — Top chênh lệch (%)</h3>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={priceChart} layout="vertical"><XAxis type="number" tickFormatter={(v) => `${v}%`} />
                <YAxis dataKey="name" type="category" width={130} tick={{ fontSize: 9 }} />
                <Tooltip formatter={(v: number) => [`${v}%`, "Chênh lệch"]} /><ReferenceLine x={0} stroke="#666" />
                <Bar dataKey="gap" radius={[0, 4, 4, 0]}>{priceChart.map((e, i) => <Cell key={i} fill={(e.gap ?? 0) <= 0 ? "#16a34a" : "#dc2626"} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="card p-5">
            <h3 className="font-semibold mb-3">Ma trận Giá VTR vs TT (bubble = tần suất VTR)</h3>
            <ResponsiveContainer width="100%" height={280}>
              <ScatterChart><XAxis dataKey="x" name="TT/ngày" tickFormatter={(v) => `${(v / 1e6).toFixed(1)}tr`} />
                <YAxis dataKey="y" name="VTR/ngày" tickFormatter={(v) => `${(v / 1e6).toFixed(1)}tr`} />
                <ZAxis dataKey="z" range={[30, 400]} /><Tooltip cursor={{ strokeDasharray: "3 3" }} />
                <Scatter data={scatterData} fill="#003580" /></ScatterChart>
            </ResponsiveContainer>
            <p className="text-xs text-gray-400 mt-2">Điểm dưới đường chéo = VTR rẻ hơn thị trường</p>
          </div>
        </div>
      )}

      {tab === "price" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <h3 className="font-semibold mb-2 text-sm">Bảng so sánh giá/ngày ({segments?.total ?? 0} segment)</h3>
            <SegmentTable cols={["TT", "Tuyến", "Điểm KH", "Ngày", "VTR/ngày", "TT/ngày", "Chênh %", ""]} />
          </div>
          <div className="card p-4">
            <h3 className="font-semibold text-sm mb-3">Hướng dẫn đọc</h3>
            <p className="text-xs text-gray-600 space-y-2">
              <span className="block">Chỉ so sánh tour <strong>cùng segment</strong>: Thị trường + Tuyến + Điểm KH + Số ngày.</span>
              <span className="block">Giá trung bình có trọng số — tour nhiều đoàn/ngày KH được tính nặng hơn.</span>
              <span className="block">Click 1 dòng để xem chi tiết từng công ty và lịch trình.</span>
            </p>
          </div>
        </div>
      )}

      {tab === "frequency" && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="card p-5">
              <h3 className="font-semibold mb-3 flex items-center gap-2"><Calendar size={16} /> Tần suất KH — VTR vs TB đối thủ/segment (%)</h3>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={freqChart} layout="vertical"><XAxis type="number" tickFormatter={(v) => `${v}%`} />
                  <YAxis dataKey="name" type="category" width={130} tick={{ fontSize: 9 }} />
                  <ReferenceLine x={0} stroke="#666" /><Tooltip />
                  <Bar dataKey="gap" radius={[0, 4, 4, 0]}>{freqChart.map((e, i) => <Cell key={i} fill={(e.gap ?? 0) >= 0 ? "#059669" : "#d97706"} />)}</Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="card p-4 bg-amber-50 border-amber-200">
              <h3 className="font-semibold text-sm text-amber-900">Cách tính tần suất</h3>
              <ul className="text-xs text-amber-800 mt-2 space-y-1 list-disc ml-4">
                <li>Đếm ngày KH liệt kê + (+N ngày khác) từ lịch tour</li>
                <li>&quot;Hàng ngày&quot; ≈ 30 lượt/tháng; &quot;Theo thứ&quot; ≈ số thứ × 4</li>
                <li>So sánh VTR với TB tần suất mỗi đối thủ trong cùng segment</li>
                <li>+20% = VTR nhiều đoàn hơn TB đối thủ; −20% = ít đoàn hơn</li>
              </ul>
              {summary && (
                <p className="text-xs mt-3 text-amber-900">
                  Tổng lượt KH VTR: <strong>{Math.round(summary.vtr_freq_monthly_total)}</strong>/tháng ·
                  Thị trường: <strong>{Math.round(summary.market_freq_monthly_total)}</strong>/tháng
                </p>
              )}
            </div>
          </div>
          <SegmentTable cols={["TT", "Tuyến", "Điểm KH", "Ngày", "VTR lượt/th", "TB ĐT/th", "Chênh %", ""]} sortKey="freq" />
        </div>
      )}

      {tab === "competitors" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="card overflow-auto max-h-[520px]">
            <div className="px-4 py-3 border-b font-semibold text-sm sticky top-0 bg-white flex items-center gap-2">
              <Building2 size={16} /> Đối thủ cạnh tranh trực tiếp
            </div>
            <table className="w-full text-xs">
              <thead className="bg-gray-50"><tr>
                {["Công ty", "Segment", "Tour", "Lượt KH/th", "Giá/ngày"].map((h) => (
                  <th key={h} className="px-2 py-2 text-left">{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {(competitors?.items ?? []).map((c) => (
                  <tr key={c.cong_ty}
                    className={cn("border-t cursor-pointer hover:bg-blue-50", selectedCompetitor === c.cong_ty && "bg-blue-50")}
                    onClick={() => setSelectedCompetitor(c.cong_ty)}>
                    <td className="px-2 py-2 font-medium">{c.cong_ty}</td>
                    <td className="px-2 py-2">{c.overlap_segments}</td>
                    <td className="px-2 py-2">{c.tour_count}</td>
                    <td className="px-2 py-2">{Math.round(c.freq_monthly)}</td>
                    <td className="px-2 py-2">{fmtVND(c.avg_price_day)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="lg:col-span-2 space-y-4">
            {!selectedCompetitor && (
              <div className="card p-12 text-center text-gray-400">
                <Building2 size={40} className="mx-auto mb-3 opacity-40" />
                <p>Chọn đối thủ để xem segment trùng với Vietravel</p>
              </div>
            )}
            {compDetail && (
              <>
                <div className="grid grid-cols-4 gap-3">
                  <div className="kpi-card"><span className="text-xs text-gray-500">Tour</span><p className="text-lg font-bold">{compDetail.total_tours}</p></div>
                  <div className="kpi-card"><span className="text-xs text-gray-500">Segment trùng VTR</span><p className="text-lg font-bold">{compDetail.overlap_segments}</p></div>
                  <div className="kpi-card"><span className="text-xs text-gray-500">Giá/ngày TB</span><p className="text-lg font-bold">{fmtVND(compDetail.avg_price_day)}</p></div>
                  <div className="kpi-card"><span className="text-xs text-gray-500">Lượt KH/th</span><p className="text-lg font-bold">{Math.round(compDetail.total_freq_monthly)}</p></div>
                </div>
                <div className="card overflow-auto max-h-[400px]">
                  <div className="px-4 py-3 border-b font-semibold text-sm">Segment trùng — so sánh giá & tần suất vs VTR</div>
                  <table className="w-full text-xs">
                    <thead className="bg-gray-50 sticky top-0"><tr>
                      {["Tuyến", "Điểm KH", "Ngày", "ĐT/ngày", "VTR/ngày", "Chênh giá", "ĐT lượt/th", "VTR lượt/th"].map((h) => (
                        <th key={h} className="px-2 py-2 text-left">{h}</th>
                      ))}
                    </tr></thead>
                    <tbody>
                      {(compDetail.segments ?? []).map((s: any) => (
                        <tr key={s.segment_key} className="border-t hover:bg-gray-50 cursor-pointer" onClick={() => setSelectedKey(s.segment_key)}>
                          <td className="px-2 py-2 max-w-[100px] truncate">{s.tuyen_tour}</td>
                          <td className="px-2 py-2">{s.diem_kh}</td>
                          <td className="px-2 py-2">{s.so_ngay}N</td>
                          <td className="px-2 py-2">{fmtVND(s.comp_avg_day)}</td>
                          <td className="px-2 py-2">{fmtVND(s.vtr_avg_day)}</td>
                          <td className="px-2 py-2"><GapBadge pct={s.price_gap_pct} /></td>
                          <td className="px-2 py-2">{s.comp_freq_monthly}</td>
                          <td className="px-2 py-2">{s.vtr_freq_monthly}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Segment drill-down */}
      {selectedKey && detail?.found && (
        <div className="card p-5 border-2 border-primary-200">
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3 className="font-semibold">Chi tiết segment</h3>
              <p className="text-xs text-gray-500 mt-1">{detail.segment?.tuyen_tour} · {detail.segment?.diem_kh} · {detail.segment?.so_ngay}N · {detail.segment?.thi_truong}</p>
            </div>
            <button className="text-xs text-gray-400 hover:text-gray-600" onClick={() => setSelectedKey(null)}>Đóng</button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <div className="bg-blue-50 rounded-lg p-3"><span className="text-xs text-blue-600">VTR giá/ngày</span><p className="font-bold">{fmtVND(detail.segment?.vietravel_avg_day)}</p></div>
            <div className="bg-gray-50 rounded-lg p-3"><span className="text-xs text-gray-600">TT giá/ngày</span><p className="font-bold">{fmtVND(detail.segment?.market_avg_day)}</p></div>
            <div className="bg-blue-50 rounded-lg p-3"><span className="text-xs text-blue-600">VTR lượt KH/th</span><p className="font-bold">{detail.segment?.vietravel_freq_monthly}</p></div>
            <div className="bg-gray-50 rounded-lg p-3"><span className="text-xs text-gray-600">Chênh giá</span><p className="font-bold"><GapBadge pct={detail.segment?.gap_pct} /></p></div>
          </div>
          {(detail.companies ?? []).map((co: any) => (
            <div key={co.cong_ty} className="mb-4">
              <h4 className={cn("text-sm font-semibold mb-2 px-2 py-1 rounded", co.is_vietravel ? "bg-blue-100 text-blue-900" : "bg-gray-100")}>
                {co.cong_ty} ({co.tour_count} tour)
              </h4>
              <table className="w-full text-xs mb-2">
                <thead><tr className="text-gray-500 border-b">
                  {["Tour", "Giá", "Giá/ngày", "Lượt KH/th", "Lịch KH", "Lịch trình", ""].map((h) => (
                    <th key={h} className="text-left py-1.5 px-2">{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {co.tours.map((t: any) => (
                    <tr key={t.id} className="border-t hover:bg-gray-50">
                      <td className="px-2 py-1.5 max-w-[200px] truncate" title={t.ten_tour}>{t.ten_tour}</td>
                      <td className="px-2 py-1.5">{t.gia_raw || fmtVND(t.gia)}</td>
                      <td className="px-2 py-1.5 font-medium">{fmtVND(t.price_day)}</td>
                      <td className="px-2 py-1.5">{Math.round(t.freq_monthly)}</td>
                      <td className="px-2 py-1.5 max-w-[120px] truncate text-gray-500" title={t.lich_kh}>{t.lich_kh || "—"}</td>
                      <td className="px-2 py-1.5 max-w-[150px] truncate text-gray-500" title={t.lich_trinh}>{t.lich_trinh || "—"}</td>
                      <td className="px-2 py-1.5">{t.link_url && <a href={t.link_url} target="_blank" rel="noopener noreferrer"><ExternalLink size={12} /></a>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
