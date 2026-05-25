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
import { COL, GLOSSARY } from "@/lib/glossary";
import { InfoTip, PageTitle, ThTip } from "@/components/InfoTip";
import {
  TrendingDown, TrendingUp, Minus, ExternalLink, Calendar, Building2,
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

const TABS: { id: Tab; label: string; tip?: string }[] = [
  { id: "overview", label: "Tổng quan", tip: GLOSSARY.methodologyCompare },
  { id: "price", label: "So sánh giá", tip: GLOSSARY.giaSoSanh },
  { id: "frequency", label: "Tần suất khởi hành", tip: GLOSSARY.tanSuat },
  { id: "competitors", label: "Đối thủ", tip: GLOSSARY.segment },
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
    vtr: s.vtr_avg_departures_per_month ?? s.vietravel_freq_monthly,
    mkt: s.market_freq_avg_per_company,
  }));

  const scatterData = (segments?.items ?? [])
    .filter((s) => s.comparison_price && s.vietravel_avg_price)
    .slice(0, 80)
    .map((s) => ({
      x: s.comparison_price,
      y: s.vietravel_avg_price,
      z: s.vietravel_freq_monthly,
      name: s.tuyen_tour,
    }));

  const LinkCell = ({ url }: { url?: string }) => url ? (
    <a href={url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="text-primary-600 hover:text-primary-800">
      <ExternalLink size={12} />
    </a>
  ) : <span className="text-gray-300">—</span>;

  const priceHeaders: [string, string?][] = [
    [COL.thiTruong, GLOSSARY.thiTruong], [COL.tuyenTour, GLOSSARY.tuyenTour], [COL.diemKhoiHanh, GLOSSARY.diemKhoiHanh], [COL.thoiGian, GLOSSARY.thoiGian],
    [COL.giaTbVtr, GLOSSARY.giaTbVtr], [COL.ngayTb, GLOSSARY.thoiGian], ["Rẻ nhất VTR", GLOSSARY.reNhat], ["Link"],
    [COL.giaThiTruong, GLOSSARY.giaThiTruong], [COL.giaSoSanh, GLOSSARY.giaSoSanh], ["Rẻ nhất TT", GLOSSARY.reNhat], ["Link"],
    [COL.chenhPct, GLOSSARY.chenhGia], [""],
  ];

  const PriceTable = () => (
    <div className="card overflow-auto max-h-[520px]">
      <table className="w-full text-xs min-w-[1100px]">
        <thead className="bg-gray-50 sticky top-0">
          <tr>
            <th colSpan={4} className="px-2 py-1 text-left text-gray-400 font-normal border-b"><ThTip label="Nhóm so sánh" tip={GLOSSARY.segment} /></th>
            <th colSpan={4} className="px-2 py-1 text-left text-blue-700 font-semibold border-b bg-blue-50">Vietravel</th>
            <th colSpan={4} className="px-2 py-1 text-left text-gray-700 font-semibold border-b bg-gray-100">Thị trường</th>
            <th colSpan={2} className="px-2 py-1 text-left border-b">Kết quả</th>
          </tr>
          <tr className="border-b">
            {priceHeaders.map(([h, tip]) => (
              <th key={h || "x"} className="px-2 py-2 text-left font-semibold text-gray-600 whitespace-nowrap">
                {h ? <ThTip label={h} tip={tip} /> : null}
              </th>
            ))}
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
              <td className="px-2 py-2 max-w-[110px] truncate" title={s.tuyen_tour}>{s.tuyen_tour}</td>
              <td className="px-2 py-2">{s.diem_kh}</td>
              <td className="px-2 py-2">{s.so_ngay}N</td>
              <td className="px-2 py-2 font-medium text-blue-900">{fmtVND(s.vietravel_avg_price)}</td>
              <td className="px-2 py-2">{s.vietravel_avg_days ?? s.so_ngay}N</td>
              <td className="px-2 py-2">{fmtVND(s.vietravel_min_price)}</td>
              <td className="px-2 py-2"><LinkCell url={s.vietravel_min_link} /></td>
              <td className="px-2 py-2">{fmtVND(s.market_total_price)}</td>
              <td className="px-2 py-2 font-medium">{fmtVND(s.comparison_price)}</td>
              <td className="px-2 py-2">{fmtVND(s.market_min_price)}</td>
              <td className="px-2 py-2"><LinkCell url={s.market_min_link} /></td>
              <td className="px-2 py-2"><GapBadge pct={s.gap_pct} /></td>
              <td className="px-2 py-2 text-gray-400">{s.position}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const freqCols: [string, string?][] = [
    [COL.thiTruong, GLOSSARY.thiTruong], [COL.tuyenTour, GLOSSARY.tuyenTour], [COL.diemKhoiHanh, GLOSSARY.diemKhoiHanh], [COL.thoiGian, GLOSSARY.thoiGian],
    ["VTR " + COL.tbDoanThang, GLOSSARY.tbDoanThang], ["TB đối thủ " + COL.tbDoanThang, GLOSSARY.tbDoanThang], [COL.chenhPct, GLOSSARY.tanSuat], [""],
  ];

  const SegmentTable = ({ sortKey }: { sortKey?: string }) => (
    <div className="card overflow-auto max-h-[480px]">
      <table className="w-full text-xs">
        <thead className="bg-gray-50 sticky top-0">
          <tr>
            {(sortKey === "freq" ? freqCols : [
              [COL.thiTruong, GLOSSARY.thiTruong], [COL.tuyenTour, GLOSSARY.tuyenTour], [COL.diemKhoiHanh, GLOSSARY.diemKhoiHanh], [COL.thoiGian, GLOSSARY.thoiGian],
              [COL.giaTbNgay + " VTR", GLOSSARY.giaTbVtr], [COL.giaTbNgay + " TT", GLOSSARY.giaTbNgay], [COL.chenhPct, GLOSSARY.chenhGia], [""],
            ] as [string, string?][]).map(([h, tip]) => (
              <th key={h} className="px-2 py-2 text-left font-semibold text-gray-600"><ThTip label={h} tip={tip} /></th>
            ))}
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
                  <td className="px-2 py-2">{s.vtr_avg_departures_per_month ?? Math.round(s.vietravel_freq_monthly / Math.max(s.vietravel_count, 1))}</td>
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
        <h1 className="text-xl font-bold inline-flex items-center gap-1.5">
          So sánh & Đối thủ — Vietravel
          <InfoTip text={GLOSSARY.methodologyCompare} className="[&_svg]:text-blue-100" />
        </h1>
        <p className="text-blue-100 text-sm mt-1">Cùng {COL.thiTruong} · {COL.tuyenTour} · {COL.diemKhoiHanh} · {COL.thoiGian}</p>
      </div>

      {/* Filters */}
      <div className="card p-4 flex flex-wrap gap-3 items-end">
        <div>
          <label className="text-xs text-gray-500 inline-flex items-center">{COL.thiTruong}<InfoTip text={GLOSSARY.thiTruong} /></label>
          <select className="input w-44 text-sm" value={thiTruong} onChange={(e) => setThiTruong(e.target.value)}>
            <option value="">Tất cả</option>
            {(filterOpts?.thi_truong ?? []).map((m: string) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 inline-flex items-center">{COL.tuyenTour}<InfoTip text={GLOSSARY.tuyenTour} /></label>
          <input className="input w-44 text-sm" placeholder="Tìm tuyến..." value={tuyenTour} onChange={(e) => setTuyenTour(e.target.value)} />
        </div>
        <div>
          <label className="text-xs text-gray-500 inline-flex items-center">{COL.diemKhoiHanh}<InfoTip text={GLOSSARY.diemKhoiHanh} /></label>
          <input className="input w-36 text-sm" placeholder="TP.HCM..." value={diemKh} onChange={(e) => setDiemKh(e.target.value)} />
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 flex-wrap border-b border-gray-200">
        {TABS.map(({ id, label, tip }) => (
          <button key={id} onClick={() => setTab(id)}
            className={cn("px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors inline-flex items-center gap-1",
              tab === id ? "border-primary-600 text-primary-600" : "border-transparent text-gray-500 hover:text-gray-800")}>
            {label}
            {tip && <InfoTip text={tip} />}
          </button>
        ))}
      </div>

      {/* KPIs */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <div className="kpi-card"><span className="text-xs text-gray-500 inline-flex items-center">{COL.sanPham} VTR<InfoTip text={GLOSSARY.tenTour} /></span><p className="text-xl font-bold">{summary.total_vietravel_tours}</p></div>
          <div className="kpi-card"><span className="text-xs text-gray-500 inline-flex items-center">Nhóm so sánh<InfoTip text={GLOSSARY.segment} /></span><p className="text-xl font-bold">{summary.segments_with_vietravel}</p></div>
          <div className="kpi-card"><span className="text-xs text-green-600">Rẻ hơn TT</span><p className="text-xl font-bold text-green-700">{summary.cheaper_count}</p></div>
          <div className="kpi-card"><span className="text-xs text-red-600">Đắt hơn TT</span><p className="text-xl font-bold text-red-700">{summary.expensive_count}</p></div>
          <div className="kpi-card"><span className="text-xs text-gray-500 inline-flex items-center">{COL.chenhPct}<InfoTip text={GLOSSARY.chenhGia} /></span><p className="text-xl font-bold">{summary.avg_gap_pct != null ? `${summary.avg_gap_pct}%` : "—"}</p></div>
          <div className="kpi-card"><span className="text-xs text-gray-500 inline-flex items-center">{COL.tbDoanThang} VTR<InfoTip text={GLOSSARY.tbDoanThang} /></span><p className="text-xl font-bold">{summary.vtr_avg_departures_per_month ?? "—"}</p></div>
        </div>
      )}

      {tab === "overview" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="card p-5">
            <h3 className="font-semibold mb-3 inline-flex items-center">{COL.chenhPct} VTR vs {COL.giaSoSanh}<InfoTip text={GLOSSARY.chenhGia} /></h3>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={priceChart} layout="vertical"><XAxis type="number" tickFormatter={(v) => `${v}%`} />
                <YAxis dataKey="name" type="category" width={130} tick={{ fontSize: 9 }} />
                <Tooltip formatter={(v: number) => [`${v}%`, "Chênh lệch"]} /><ReferenceLine x={0} stroke="#666" />
                <Bar dataKey="gap" radius={[0, 4, 4, 0]}>{priceChart.map((e, i) => <Cell key={i} fill={(e.gap ?? 0) <= 0 ? "#16a34a" : "#dc2626"} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="card p-5">
            <h3 className="font-semibold mb-3 inline-flex items-center">{COL.giaTbVtr} vs {COL.giaSoSanh}<InfoTip text={GLOSSARY.giaSoSanh} /></h3>
            <ResponsiveContainer width="100%" height={280}>
              <ScatterChart><XAxis dataKey="x" name={COL.giaSoSanh} tickFormatter={(v) => `${(v / 1e6).toFixed(1)}tr`} />
                <YAxis dataKey="y" name={COL.giaTbVtr} tickFormatter={(v) => `${(v / 1e6).toFixed(1)}tr`} />
                <ZAxis dataKey="z" range={[30, 400]} /><Tooltip cursor={{ strokeDasharray: "3 3" }} />
                <Scatter data={scatterData} fill="#003580" /></ScatterChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {tab === "price" && (
        <div>
          <h3 className="font-semibold mb-2 text-sm inline-flex items-center">
            Bảng so sánh giá ({segments?.total ?? 0} nhóm)
            <InfoTip text={GLOSSARY.giaSoSanh} />
          </h3>
          <PriceTable />
        </div>
      )}

      {tab === "frequency" && (
        <div className="space-y-4">
          <div className="card p-5">
            <h3 className="font-semibold mb-3 flex items-center gap-2">
              <Calendar size={16} /> {COL.tbDoanThang} — VTR vs đối thủ (%)
              <InfoTip text={GLOSSARY.tanSuat} />
            </h3>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={freqChart} layout="vertical"><XAxis type="number" tickFormatter={(v) => `${v}%`} />
                <YAxis dataKey="name" type="category" width={130} tick={{ fontSize: 9 }} />
                <ReferenceLine x={0} stroke="#666" /><Tooltip />
                <Bar dataKey="gap" radius={[0, 4, 4, 0]}>{freqChart.map((e, i) => <Cell key={i} fill={(e.gap ?? 0) >= 0 ? "#059669" : "#d97706"} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <SegmentTable sortKey="freq" />
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
                {[
                  [COL.congTy, GLOSSARY.congTy], ["Nhóm trùng", GLOSSARY.segment], [COL.sanPham, GLOSSARY.tenTour],
                  [COL.tbDoanThang, GLOSSARY.tbDoanThang], [COL.giaTbNgay, GLOSSARY.giaTbNgay],
                ].map(([h, tip]) => (
                  <th key={h} className="px-2 py-2 text-left"><ThTip label={h} tip={tip} /></th>
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
                    <td className="px-2 py-2">{Math.round(c.freq_monthly / Math.max(c.tour_count, 1))}</td>
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
                  <div className="kpi-card"><span className="text-xs text-gray-500 inline-flex items-center">{COL.tbDoanThang}<InfoTip text={GLOSSARY.tbDoanThang} /></span><p className="text-lg font-bold">{compDetail.total_tours ? Math.round(compDetail.total_freq_monthly / compDetail.total_tours * 10) / 10 : "—"}</p></div>
                </div>
                <div className="card overflow-auto max-h-[400px]">
                  <div className="px-4 py-3 border-b font-semibold text-sm inline-flex items-center">
                    Nhóm trùng — giá & tần suất vs VTR
                    <InfoTip text={GLOSSARY.segment} />
                  </div>
                  <table className="w-full text-xs">
                    <thead className="bg-gray-50 sticky top-0"><tr>
                      {[
                        [COL.tuyenTour, GLOSSARY.tuyenTour], [COL.diemKhoiHanh, GLOSSARY.diemKhoiHanh], [COL.thoiGian, GLOSSARY.thoiGian],
                        [COL.giaSoSanh + " ĐT", GLOSSARY.giaSoSanh], [COL.giaTbVtr, GLOSSARY.giaTbVtr], [COL.chenhPct, GLOSSARY.chenhGia],
                        ["ĐT " + COL.tbDoanThang, GLOSSARY.tbDoanThang], ["VTR " + COL.tbDoanThang, GLOSSARY.tbDoanThang],
                      ].map(([h, tip]) => (
                        <th key={h} className="px-2 py-2 text-left"><ThTip label={h} tip={tip} /></th>
                      ))}
                    </tr></thead>
                    <tbody>
                      {(compDetail.segments ?? []).map((s: any) => (
                        <tr key={s.segment_key} className="border-t hover:bg-gray-50 cursor-pointer" onClick={() => setSelectedKey(s.segment_key)}>
                          <td className="px-2 py-2 max-w-[100px] truncate">{s.tuyen_tour}</td>
                          <td className="px-2 py-2">{s.diem_kh}</td>
                          <td className="px-2 py-2">{s.so_ngay}N</td>
                          <td className="px-2 py-2">{fmtVND(s.comp_compare_price)}</td>
                          <td className="px-2 py-2">{fmtVND(s.vtr_avg_price)}</td>
                          <td className="px-2 py-2"><GapBadge pct={s.price_gap_pct} /></td>
                          <td className="px-2 py-2">{s.comp_avg_departures_per_month ?? s.comp_freq_monthly}</td>
                          <td className="px-2 py-2">{s.vtr_avg_departures_per_month ?? s.vtr_freq_monthly}</td>
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
              <h3 className="font-semibold inline-flex items-center">Chi tiết nhóm so sánh<InfoTip text={GLOSSARY.segment} /></h3>
              <p className="text-xs text-gray-500 mt-1">{detail.segment?.tuyen_tour} · {detail.segment?.diem_kh} · {detail.segment?.so_ngay}N · {detail.segment?.thi_truong}</p>
            </div>
            <button className="text-xs text-gray-400 hover:text-gray-600" onClick={() => setSelectedKey(null)}>Đóng</button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <div className="bg-blue-50 rounded-lg p-3"><span className="text-xs text-blue-600 inline-flex items-center">{COL.giaTbVtr}<InfoTip text={GLOSSARY.giaTbVtr} /></span><p className="font-bold">{fmtVND(detail.segment?.vietravel_avg_price)}</p></div>
            <div className="bg-gray-50 rounded-lg p-3"><span className="text-xs text-gray-600 inline-flex items-center">{COL.giaSoSanh}<InfoTip text={GLOSSARY.giaSoSanh} /></span><p className="font-bold">{fmtVND(detail.segment?.comparison_price)}</p></div>
            <div className="bg-blue-50 rounded-lg p-3"><span className="text-xs text-blue-600 inline-flex items-center">VTR {COL.tbDoanThang}<InfoTip text={GLOSSARY.tbDoanThang} /></span><p className="font-bold">{detail.segment?.vtr_avg_departures_per_month ?? detail.segment?.vietravel_freq_monthly}</p></div>
            <div className="bg-gray-50 rounded-lg p-3"><span className="text-xs text-gray-600 inline-flex items-center">{COL.chenhPct}<InfoTip text={GLOSSARY.chenhGia} /></span><p className="font-bold"><GapBadge pct={detail.segment?.gap_pct} /></p></div>
          </div>
          {(detail.companies ?? []).map((co: any) => (
            <div key={co.cong_ty} className="mb-4">
              <h4 className={cn("text-sm font-semibold mb-2 px-2 py-1 rounded", co.is_vietravel ? "bg-blue-100 text-blue-900" : "bg-gray-100")}>
                {co.cong_ty} ({co.tour_count} tour)
              </h4>
              <table className="w-full text-xs mb-2">
                <thead><tr className="text-gray-500 border-b">
                  {[
                    [COL.tenTour, GLOSSARY.tenTour], [COL.gia, GLOSSARY.giaTbTour], [COL.giaTbNgay, GLOSSARY.giaTbNgay],
                    [COL.tbDoanThang, GLOSSARY.tbDoanThang], [COL.lichKhoiHanh, GLOSSARY.lichKhoiHanh], ["Lịch trình"], [COL.linkTour],
                  ].map(([h, tip]) => (
                    <th key={h} className="text-left py-1.5 px-2"><ThTip label={h} tip={tip} /></th>
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
