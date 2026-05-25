import { useState, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine,
  ScatterChart, Scatter, ZAxis, Legend, CartesianGrid,
} from "recharts";
import {
  getCompareSummary, getCompareSegments, getSegmentDetail,
  getCompareCompetitors, getCompareCompetitorDetail,
  getCompareFilterOptions, getCompareClassificationGaps, getCompareWeekdayDistribution,
  getCoverageMap, getMatcherSuggest, getMatcherDetail,
  CompareSegment,
} from "@/lib/api";
import { fmtVND, cn } from "@/lib/utils";
import { COL, GLOSSARY } from "@/lib/glossary";
import { InfoTip, PageTitle, ThTip } from "@/components/InfoTip";
import {
  TrendingDown, TrendingUp, Minus, ExternalLink, Calendar, Building2, ArrowUpDown,
} from "lucide-react";

type Tab = "overview" | "price" | "frequency" | "competitors" | "coverage" | "matcher";

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

type SortCol = "thi_truong" | "tuyen_tour" | "diem_kh" | "so_ngay" | "vietravel_avg_price" | "comparison_price" | "market_min_price" | "gap_pct" | "freq_gap_pct";

function SortTh({
  col, label, tip, sortBy, sortDir, onSort,
}: {
  col: SortCol; label: string; tip?: string; sortBy: SortCol; sortDir: "asc" | "desc"; onSort: (c: SortCol) => void;
}) {
  const active = sortBy === col;
  return (
    <th
      className="px-2 py-2 text-left font-semibold text-gray-600 whitespace-nowrap cursor-pointer select-none hover:bg-gray-100"
      onClick={() => onSort(col)}
    >
      <span className="inline-flex items-center gap-1">
        <ThTip label={label} tip={tip} />
        <ArrowUpDown size={11} className={cn(active ? "text-primary-600" : "text-gray-300")} />
        {active && <span className="text-primary-600 text-[10px]">{sortDir === "asc" ? "↑" : "↓"}</span>}
      </span>
    </th>
  );
}

const TABS: { id: Tab; label: string; tip?: string }[] = [
  { id: "overview", label: "Tổng quan", tip: GLOSSARY.methodologyCompare },
  { id: "price", label: "So sánh giá", tip: GLOSSARY.giaSoSanh },
  { id: "frequency", label: "Tần suất KH", tip: GLOSSARY.tanSuat },
  { id: "competitors", label: "Đối thủ", tip: GLOSSARY.segment },
  { id: "coverage", label: "Phủ sóng", tip: GLOSSARY.thiTruong },
  { id: "matcher", label: "Ghép SP", tip: GLOSSARY.tenTour },
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

  const [selectedMatcherTour, setSelectedMatcherTour] = useState<number | null>(null);
  const [sortBy, setSortBy] = useState<SortCol>("gap_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const handleSort = (col: SortCol) => {
    if (sortBy === col) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortBy(col); setSortDir(col === "tuyen_tour" || col === "diem_kh" || col === "thi_truong" ? "asc" : "desc"); }
  };

  const filters = useMemo(() => ({
    ...(thiTruong ? { thi_truong: [thiTruong] } : {}),
    ...(tuyenTour ? { tuyen_tour: tuyenTour } : {}),
    ...(diemKh ? { diem_kh: diemKh } : {}),
  }), [thiTruong, tuyenTour, diemKh]);

  const segmentQueryFilters = useMemo(() => ({
    ...filters,
    sort_by: tab === "frequency" ? "freq_gap_pct" : sortBy,
    sort_dir: sortDir,
    limit: 300,
  }), [filters, tab, sortBy, sortDir]);

  const compareStale = 5 * 60_000;
  const needsSegments = tab === "overview" || tab === "price" || tab === "frequency";

  const { data: filterOpts } = useQuery({
    queryKey: ["compare-filter-options"],
    queryFn: getCompareFilterOptions,
    staleTime: compareStale,
  });
  const routeOptions = useMemo(() => {
    if (!thiTruong) return filterOpts?.tuyen_tour ?? [];
    return filterOpts?.routes_by_market?.[thiTruong] ?? [];
  }, [thiTruong, filterOpts]);

  const { data: summary } = useQuery({
    queryKey: ["compare-summary", filters],
    queryFn: () => getCompareSummary(filters),
    staleTime: compareStale,
  });
  const { data: segments, isLoading: segmentsLoading, isError: segmentsError, refetch: refetchSegments } = useQuery({
    queryKey: ["compare-segments", segmentQueryFilters],
    queryFn: () => getCompareSegments(segmentQueryFilters),
    enabled: needsSegments,
    staleTime: compareStale,
    retry: 1,
  });
  const { data: classGaps } = useQuery({
    queryKey: ["compare-class-gaps", filters],
    queryFn: () => getCompareClassificationGaps(filters),
    enabled: tab === "price" || tab === "frequency",
    staleTime: compareStale,
  });
  const { data: weekdayDist } = useQuery({
    queryKey: ["compare-weekday-dist", filters],
    queryFn: () => getCompareWeekdayDistribution(filters),
    enabled: tab === "frequency",
    staleTime: compareStale,
  });
  const { data: competitors } = useQuery({
    queryKey: ["compare-competitors", filters],
    queryFn: () => getCompareCompetitors(filters),
    enabled: tab === "competitors",
    staleTime: compareStale,
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
  const { data: coverage } = useQuery({ queryKey: ["coverage"], queryFn: getCoverageMap, enabled: tab === "coverage" });
  const { data: matcherSuggest } = useQuery({ queryKey: ["matcher-suggest"], queryFn: getMatcherSuggest, enabled: tab === "matcher" });
  const { data: matcherDetail } = useQuery({
    queryKey: ["matcher-detail", selectedMatcherTour],
    queryFn: () => getMatcherDetail(selectedMatcherTour!),
    enabled: !!selectedMatcherTour,
  });

  const fmtDays = (d: number | null | undefined) => {
    if (d == null) return "—";
    const r = Math.round(d * 10) / 10;
    return Number.isInteger(r) ? `${r}N` : `${r}N`;
  };

  const priceChart = (segments?.items ?? []).filter((s) => s.gap_pct != null).slice(0, 12).map((s) => ({
    name: `${s.tuyen_tour.slice(0, 22)} (${s.diem_kh})`,
    gap: s.gap_pct,
  }));

  const freqChart = (segments?.items ?? []).filter((s) => s.freq_gap_pct != null).slice(0, 12).map((s) => ({
    name: `${s.tuyen_tour.slice(0, 22)} (${s.diem_kh})`,
    gap: s.freq_gap_pct,
    vtr: s.vtr_avg_departures_per_month ?? s.vietravel_freq_monthly,
    mkt: s.top_freq_competitor_departures,
  }));

  const weekdayCompareChart = useMemo(() => {
    if (!weekdayDist) return [];
    return weekdayDist.labels.map((label, i) => ({
      weekday: label,
      vtr: weekdayDist.vietravel[i]?.departures_monthly ?? 0,
      mkt: weekdayDist.market[i]?.departures_monthly ?? 0,
      vtrPct: weekdayDist.vietravel[i]?.share_pct ?? 0,
      mktPct: weekdayDist.market[i]?.share_pct ?? 0,
    }));
  }, [weekdayDist]);

  const scatterData = (segments?.items ?? [])
    .filter((s) => s.comparison_price && s.vietravel_avg_price)
    .slice(0, 80)
    .map((s) => ({
      x: s.comparison_price,
      y: s.vietravel_avg_price,
      z: s.vietravel_freq_monthly,
      name: s.tuyen_tour,
    }));

  const LinkCell = ({ url, title }: { url?: string; title?: string }) => {
    const href = url && /^https?:\/\//i.test(url) ? url : undefined;
    return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="text-primary-600 hover:text-primary-800" title={title}>
      <ExternalLink size={12} />
    </a>
  ) : (
    <span className="text-gray-400 text-[10px]" title={title || "Chưa có link — kiểm tra dữ liệu scrape"}>—</span>
  );
  };

  const UnmatchedPanel = () => {
    const hasAny = (classGaps?.cong_ty?.length || classGaps?.diem_kh?.length || classGaps?.thoi_gian?.length);
    if (!hasAny) return null;
    return (
      <div className="card p-4 border border-amber-200 bg-amber-50/50 space-y-3">
        <p className="text-sm font-semibold text-amber-900 inline-flex items-center gap-1">
          Giá trị chưa khớp alias (tour VTR)
          <InfoTip text="Bổ sung alias tại Quy tắc phân loại để gom nhóm chính xác hơn" />
        </p>
        <div className="grid md:grid-cols-3 gap-4 text-xs">
          {([
            { label: COL.congTy, items: classGaps?.cong_ty },
            { label: COL.diemKhoiHanh, items: classGaps?.diem_kh },
            { label: COL.thoiGian, items: classGaps?.thoi_gian },
          ] as const).map(({ label, items }) => (
            <div key={label}>
              <p className="font-medium text-gray-700 mb-1">{label}</p>
              <ul className="space-y-1 max-h-32 overflow-auto">
                {(items ?? []).map((x) => (
                  <li key={x.value} className="flex justify-between gap-2 bg-white/80 px-2 py-1 rounded border border-amber-100">
                    <span className="truncate" title={x.value}>{x.value || "—"}</span>
                    <span className="text-gray-500 shrink-0">{x.count}</span>
                  </li>
                ))}
                {!(items?.length) && <li className="text-gray-400">Đã khớp hết</li>}
              </ul>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const SegmentsErrorBanner = () => (
    segmentsError ? (
      <div className="card p-4 border border-red-200 bg-red-50 text-sm text-red-800 flex flex-wrap items-center justify-between gap-2">
        <span>Không tải được bảng so sánh — thử làm mới hoặc liên hệ admin.</span>
        <button type="button" className="btn btn-sm" onClick={() => refetchSegments()}>Thử lại</button>
      </div>
    ) : null
  );

  const PriceTable = () => (
    <div className="card overflow-auto max-h-[520px]">
      <table className="w-full text-xs min-w-[1200px]">
        <thead className="bg-gray-50 sticky top-0">
          <tr>
            <th colSpan={5} className="px-2 py-1 text-left text-gray-400 font-normal border-b"><ThTip label="Nhóm so sánh" tip={GLOSSARY.segment} /></th>
            <th colSpan={3} className="px-2 py-1 text-left text-blue-700 font-semibold border-b bg-blue-50">Vietravel</th>
            <th colSpan={4} className="px-2 py-1 text-left text-gray-700 font-semibold border-b bg-gray-100">Thị trường (giai đoạn VTR)</th>
            <th colSpan={2} className="px-2 py-1 text-left border-b">Kết quả</th>
          </tr>
          <tr className="border-b">
            <SortTh col="thi_truong" label={COL.thiTruong} tip={GLOSSARY.thiTruong} sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
            <SortTh col="tuyen_tour" label={COL.tuyenTour} tip={GLOSSARY.tuyenTour} sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
            <SortTh col="diem_kh" label={COL.diemKhoiHanh} tip={GLOSSARY.diemKhoiHanh} sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
            <SortTh col="so_ngay" label={COL.ngayTb} tip="Số ngày TB có trọng số theo đoàn — gộp mọi sản phẩm trên tuyến" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
            <th className="px-2 py-2 text-left font-semibold text-gray-600 whitespace-nowrap"><ThTip label="Giai đoạn" tip="Theo ngày KH tour VTR — VD: T5–T8/2025" /></th>
            <SortTh col="vietravel_avg_price" label={COL.giaTbVtr} tip={GLOSSARY.giaTbVtr} sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
            <th className="px-2 py-2 text-left font-semibold text-gray-600 whitespace-nowrap"><ThTip label="Rẻ nhất VTR" tip={GLOSSARY.reNhat} /></th>
            <th className="px-2 py-2 text-left font-semibold text-gray-600">Link</th>
            <th className="px-2 py-2 text-left font-semibold text-gray-600 whitespace-nowrap"><ThTip label={COL.giaThiTruong} tip={GLOSSARY.giaThiTruong} /></th>
            <SortTh col="comparison_price" label={COL.giaSoSanh} tip={GLOSSARY.giaSoSanh} sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
            <SortTh col="market_min_price" label="Rẻ nhất TT" tip={GLOSSARY.reNhat} sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
            <th className="px-2 py-2 text-left font-semibold text-gray-600">Link</th>
            <SortTh col="gap_pct" label={COL.chenhPct} tip={GLOSSARY.chenhGia} sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
            <th className="px-2 py-2 text-left font-semibold text-gray-600"></th>
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
              <td className="px-2 py-2">{fmtDays(s.so_ngay)}</td>
              <td className="px-2 py-2 text-[10px] text-gray-600 whitespace-nowrap">{s.vtr_comparison_period || "—"}</td>
              <td className="px-2 py-2 font-medium text-blue-900">{fmtVND(s.vietravel_avg_price)}</td>
              <td className="px-2 py-2">{fmtVND(s.vietravel_min_price)}</td>
              <td className="px-2 py-2"><LinkCell url={s.vietravel_min_link} title={s.vietravel_min_tour} /></td>
              <td className="px-2 py-2">{fmtVND(s.market_total_price)}</td>
              <td className="px-2 py-2 font-medium">{fmtVND(s.comparison_price)}</td>
              <td className="px-2 py-2">{fmtVND(s.market_min_price)}</td>
              <td className="px-2 py-2">
                <LinkCell url={s.market_min_link} title={s.market_min_has_link ? s.market_min_tour : `${s.market_min_tour || "Tour rẻ nhất"} — chưa có URL`} />
              </td>
              <td className="px-2 py-2"><GapBadge pct={s.gap_pct} /></td>
              <td className="px-2 py-2 text-gray-400">{s.position}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const freqCols: [string, string?][] = [
    [COL.thiTruong, GLOSSARY.thiTruong], [COL.tuyenTour, GLOSSARY.tuyenTour], [COL.diemKhoiHanh, GLOSSARY.diemKhoiHanh], [COL.ngayTb, "Số ngày TB có trọng số trên tuyến"],
    ["VTR " + COL.tbDoanThang, GLOSSARY.tbDoanThang], [COL.congTy + " TS cao nhất", "Đối thủ có TB đoàn/tháng cao nhất trên tuyến trong giai đoạn VTR"], ["TB đối thủ " + COL.tbDoanThang, GLOSSARY.tbDoanThang], [COL.chenhPct, GLOSSARY.tanSuat], [""],
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
              <td className="px-2 py-2">{fmtDays(s.so_ngay)}</td>
              {sortKey !== "freq" ? (
                <>
                  <td className="px-2 py-2 font-medium">{fmtVND(s.vietravel_avg_day)}</td>
                  <td className="px-2 py-2">{fmtVND(s.market_avg_day)}</td>
                  <td className="px-2 py-2"><GapBadge pct={s.gap_pct} /></td>
                </>
              ) : (
                <>
                  <td className="px-2 py-2">{s.vtr_avg_departures_per_month ?? Math.round(s.vietravel_freq_monthly / Math.max(s.vietravel_count, 1))}</td>
                  <td className="px-2 py-2 max-w-[100px] truncate" title={s.top_freq_competitor}>{s.top_freq_competitor || "—"}</td>
                  <td className="px-2 py-2">{s.top_freq_competitor_departures ?? "—"}</td>
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
          <select className="input w-44 text-sm" value={thiTruong} onChange={(e) => { setThiTruong(e.target.value); setTuyenTour(""); }}>
            <option value="">Tất cả thị trường VTR</option>
            {(filterOpts?.thi_truong ?? []).map((m: string) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 inline-flex items-center">{COL.tuyenTour}<InfoTip text={GLOSSARY.tuyenTour} /></label>
          <select className="input w-52 text-sm" value={tuyenTour} onChange={(e) => setTuyenTour(e.target.value)}>
            <option value="">Tất cả tuyến VTR</option>
            {routeOptions.map((r: string) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 inline-flex items-center">{COL.diemKhoiHanh}<InfoTip text={GLOSSARY.diemKhoiHanh} /></label>
          <select className="input w-40 text-sm" value={diemKh} onChange={(e) => setDiemKh(e.target.value)}>
            <option value="">Tất cả điểm KH</option>
            {(filterOpts?.diem_kh ?? []).map((d: string) => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        <p className="text-[10px] text-gray-400 self-end pb-1">Bộ lọc theo dữ liệu tour VTR</p>
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
          {segmentsError && (
            <div className="lg:col-span-2 card p-4 border border-red-200 bg-red-50 text-sm text-red-800">
              Không tải được dữ liệu biểu đồ — thử làm mới trang hoặc liên hệ admin.
            </div>
          )}
          <div className="card p-5">
            <h3 className="font-semibold mb-3 inline-flex items-center">{COL.chenhPct} VTR vs {COL.giaSoSanh}<InfoTip text={GLOSSARY.chenhGia} /></h3>
            {segmentsLoading ? (
              <div className="h-[280px] flex items-center justify-center text-gray-400 text-sm">Đang tải biểu đồ...</div>
            ) : priceChart.length === 0 ? (
              <div className="h-[280px] flex items-center justify-center text-gray-400 text-sm">Chưa có nhóm có chênh giá so sánh</div>
            ) : (
            <div className="w-full h-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart key={priceChart.length} data={priceChart} layout="vertical"><XAxis type="number" tickFormatter={(v) => `${v}%`} />
                <YAxis dataKey="name" type="category" width={130} tick={{ fontSize: 9 }} />
                <Tooltip formatter={(v: number) => [`${v}%`, "Chênh lệch"]} /><ReferenceLine x={0} stroke="#666" />
                <Bar dataKey="gap" radius={[0, 4, 4, 0]}>{priceChart.map((e, i) => <Cell key={i} fill={(e.gap ?? 0) <= 0 ? "#16a34a" : "#dc2626"} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
            </div>
            )}
          </div>
          <div className="card p-5">
            <h3 className="font-semibold mb-3 inline-flex items-center">{COL.giaTbVtr} vs {COL.giaSoSanh}<InfoTip text={GLOSSARY.giaSoSanh} /></h3>
            {segmentsLoading ? (
              <div className="h-[280px] flex items-center justify-center text-gray-400 text-sm">Đang tải biểu đồ...</div>
            ) : scatterData.length === 0 ? (
              <div className="h-[280px] flex items-center justify-center text-gray-400 text-sm">Chưa có dữ liệu giá so sánh</div>
            ) : (
            <div className="w-full h-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart key={scatterData.length}><XAxis dataKey="x" name={COL.giaSoSanh} tickFormatter={(v) => `${(v / 1e6).toFixed(1)}tr`} />
                <YAxis dataKey="y" name={COL.giaTbVtr} tickFormatter={(v) => `${(v / 1e6).toFixed(1)}tr`} />
                <ZAxis dataKey="z" range={[30, 400]} /><Tooltip cursor={{ strokeDasharray: "3 3" }} />
                <Scatter data={scatterData} fill="#003580" /></ScatterChart>
            </ResponsiveContainer>
            </div>
            )}
          </div>
        </div>
      )}

      {tab === "price" && (
        <div className="space-y-3">
          <SegmentsErrorBanner />
          <h3 className="font-semibold mb-2 text-sm inline-flex items-center">
            Bảng so sánh giá ({segmentsLoading ? "…" : segments?.total ?? summary?.segments_with_vietravel ?? 0} nhóm)
            <InfoTip text={GLOSSARY.giaSoSanh} />
          </h3>
          <PriceTable />
          <UnmatchedPanel />
        </div>
      )}

      {tab === "frequency" && (
        <div className="space-y-4">
          <SegmentsErrorBanner />
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

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="card p-5">
              <h3 className="font-semibold mb-1 text-sm inline-flex items-center gap-2">
                Tour VTR khởi hành thứ mấy
                <InfoTip text={GLOSSARY.tanSuatThu} />
              </h3>
              <p className="text-xs text-gray-500 mb-3">
                {weekdayDist?.vietravel_tour_count ?? 0} sản phẩm · ~{Math.round(weekdayDist?.vietravel_total ?? 0)} đoàn/tháng
              </p>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={weekdayDist?.vietravel ?? []}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="weekday" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: number, _n, p: any) => [`${v} đoàn/tháng (${p.payload.share_pct}%)`, COL.doanThang]} />
                  <Bar dataKey="departures_monthly" fill="#003580" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="card p-5">
              <h3 className="font-semibold mb-1 text-sm inline-flex items-center gap-2">
                Tour thị trường khởi hành thứ mấy
                <InfoTip text={GLOSSARY.tanSuatThu} />
              </h3>
              <p className="text-xs text-gray-500 mb-3">
                {weekdayDist?.market_tour_count ?? 0} sản phẩm · ~{Math.round(weekdayDist?.market_total ?? 0)} đoàn/tháng
              </p>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={weekdayDist?.market ?? []}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="weekday" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: number, _n, p: any) => [`${v} đoàn/tháng (${p.payload.share_pct}%)`, COL.doanThang]} />
                  <Bar dataKey="departures_monthly" fill="#64748b" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {weekdayCompareChart.some((r) => r.vtr > 0 || r.mkt > 0) && (
            <div className="card p-5">
              <h3 className="font-semibold mb-3 text-sm inline-flex items-center gap-2">
                So sánh phân bổ thứ KH — VTR vs thị trường
                <InfoTip text={GLOSSARY.tanSuatThu} />
              </h3>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={weekdayCompareChart}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="weekday" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: number) => [`${v} đoàn/tháng`, COL.doanThang]} />
                  <Legend />
                  <Bar dataKey="vtr" name="Vietravel" fill="#003580" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="mkt" name="Thị trường" fill="#94a3b8" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          <SegmentTable sortKey="freq" />
          <UnmatchedPanel />
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
                        [COL.tuyenTour, GLOSSARY.tuyenTour], [COL.diemKhoiHanh, GLOSSARY.diemKhoiHanh],
                        ["Giai đoạn VTR", "Theo lịch KH tour VTR"],
                        [COL.giaSoSanh + " ĐT", GLOSSARY.giaSoSanh], [COL.chenhPct, GLOSSARY.chenhGia],
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
                          <td className="px-2 py-2 text-[10px] text-gray-600">{s.vtr_comparison_period || "—"}</td>
                          <td className="px-2 py-2">{fmtVND(s.comp_compare_price)}</td>
                          <td className="px-2 py-2"><GapBadge pct={s.price_gap_pct} /></td>
                          <td className="px-2 py-2">{s.comp_avg_departures_per_month ?? s.comp_freq_monthly}</td>
                          <td className="px-2 py-2">{s.vtr_avg_departures_per_month ?? "—"}</td>
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

      {tab === "coverage" && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="kpi-card"><span className="text-xs text-gray-500">Cả VTR & TT</span><p className="text-xl font-bold text-green-700">{coverage?.summary?.both ?? "—"}</p></div>
            <div className="kpi-card"><span className="text-xs text-gray-500">Chỉ VTR</span><p className="text-xl font-bold text-blue-700">{coverage?.summary?.vtr_only ?? "—"}</p></div>
            <div className="kpi-card"><span className="text-xs text-gray-500">Chỉ thị trường</span><p className="text-xl font-bold text-gray-700">{coverage?.summary?.market_only ?? "—"}</p></div>
            <div className="kpi-card border-l-4 border-l-amber-500"><span className="text-xs text-gray-500 inline-flex items-center">Khoảng trống<InfoTip text="Tuyến đối thủ có SP, VTR chưa có" /></span><p className="text-xl font-bold text-amber-700">{coverage?.summary?.gap_opportunities ?? "—"}</p></div>
          </div>
          <div className="grid lg:grid-cols-2 gap-4">
            <div className="card overflow-auto max-h-[420px]">
              <div className="px-4 py-3 border-b font-semibold text-sm">Ma trận phủ sóng (top 80)</div>
              <table className="w-full text-xs">
                <thead className="bg-gray-50 sticky top-0"><tr>
                  {[COL.thiTruong, COL.tuyenTour, "VTR", "TT", "ĐT", "Trạng thái"].map((h) => (
                    <th key={h} className="px-2 py-2 text-left">{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {(coverage?.matrix ?? []).map((row: any) => (
                    <tr key={`${row.thi_truong}-${row.tuyen_tour}`} className="border-t hover:bg-gray-50">
                      <td className="px-2 py-2">{row.thi_truong}</td>
                      <td className="px-2 py-2 max-w-[120px] truncate" title={row.tuyen_tour}>{row.tuyen_tour}</td>
                      <td className="px-2 py-2 font-medium">{row.vtr_tours}</td>
                      <td className="px-2 py-2">{row.market_tours}</td>
                      <td className="px-2 py-2">{row.competitor_count}</td>
                      <td className="px-2 py-2">
                        <span className={cn("badge text-[10px]",
                          row.status === "both" && "bg-green-100 text-green-800",
                          row.status === "vtr_only" && "bg-blue-100 text-blue-800",
                          row.status === "market_only" && "bg-amber-100 text-amber-800",
                        )}>
                          {row.status === "both" ? "Cả hai" : row.status === "vtr_only" ? "Chỉ VTR" : "Chỉ TT"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card overflow-auto max-h-[420px]">
              <div className="px-4 py-3 border-b font-semibold text-sm text-amber-800">Cơ hội khoảng trống — VTR chưa có SP</div>
              <table className="w-full text-xs">
                <thead className="bg-amber-50 sticky top-0"><tr>
                  {[COL.thiTruong, COL.tuyenTour, "SP đối thủ", "Số ĐT"].map((h) => (
                    <th key={h} className="px-2 py-2 text-left">{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {(coverage?.gaps ?? []).map((g: any) => (
                    <tr key={`${g.thi_truong}-${g.tuyen_tour}`} className="border-t">
                      <td className="px-2 py-2">{g.thi_truong}</td>
                      <td className="px-2 py-2 font-medium">{g.tuyen_tour}</td>
                      <td className="px-2 py-2">{g.market_tours}</td>
                      <td className="px-2 py-2">{g.companies}</td>
                    </tr>
                  ))}
                  {!(coverage?.gaps?.length) && (
                    <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-400">Không có khoảng trống lớn</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {tab === "matcher" && (
        <div className="grid lg:grid-cols-3 gap-4">
          <div className="card overflow-auto max-h-[520px]">
            <div className="px-4 py-3 border-b font-semibold text-sm">Chọn tour Vietravel</div>
            <div className="divide-y">
              {(matcherSuggest?.items ?? []).map((t: any) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setSelectedMatcherTour(t.id)}
                  className={cn("w-full text-left px-4 py-3 hover:bg-blue-50 text-xs", selectedMatcherTour === t.id && "bg-blue-50 border-l-4 border-l-primary-600")}
                >
                  <p className="font-medium line-clamp-2">{t.ten_tour}</p>
                  <p className="text-gray-500 mt-1">{t.thi_truong} · {t.tuyen_tour} · {fmtVND(t.gia)}</p>
                </button>
              ))}
            </div>
          </div>
          <div className="lg:col-span-2 space-y-4">
            {!selectedMatcherTour && (
              <div className="card p-12 text-center text-gray-400">
                <Building2 size={40} className="mx-auto mb-3 opacity-40" />
                <p>Chọn tour VTR để xem gợi ý ghép cặp với đối thủ</p>
              </div>
            )}
            {matcherDetail?.found && (
              <>
                <div className="card p-4 bg-blue-50 border border-blue-200">
                  <h3 className="font-semibold text-sm text-blue-900">{matcherDetail.vtr_tour?.ten_tour}</h3>
                  <p className="text-xs text-blue-700 mt-1">
                    {matcherDetail.vtr_tour?.thi_truong} · {matcherDetail.vtr_tour?.tuyen_tour} · {matcherDetail.vtr_tour?.diem_kh} · {matcherDetail.vtr_tour?.thoi_gian}
                  </p>
                  <div className="flex gap-4 mt-2 text-xs">
                    <span>Giá: <strong>{fmtVND(matcherDetail.vtr_tour?.gia)}</strong></span>
                    <span>Giá/ngày: <strong>{fmtVND(matcherDetail.vtr_tour?.price_day)}</strong></span>
                    {matcherDetail.vtr_tour?.link_url && (
                      <a href={matcherDetail.vtr_tour.link_url} target="_blank" rel="noopener noreferrer" className="text-primary-600 flex items-center gap-1"><ExternalLink size={12} /> Link</a>
                    )}
                  </div>
                </div>
                <div className="card overflow-auto">
                  <div className="px-4 py-3 border-b font-semibold text-sm">Tour đối thủ gợi ý (theo điểm khớp)</div>
                  <table className="w-full text-xs">
                    <thead className="bg-gray-50"><tr>
                      {["Điểm", COL.congTy, COL.tenTour, COL.gia, COL.giaTbNgay, "Chênh %", COL.tbDoanThang, ""].map((h) => (
                        <th key={h || "link"} className="px-2 py-2 text-left">{h}</th>
                      ))}
                    </tr></thead>
                    <tbody>
                      {(matcherDetail.matches ?? []).map((m: any) => (
                        <tr key={m.tour_id} className="border-t hover:bg-gray-50">
                          <td className="px-2 py-2 font-bold text-primary-700">{(m.match_score * 100).toFixed(0)}%</td>
                          <td className="px-2 py-2">{m.cong_ty}</td>
                          <td className="px-2 py-2 max-w-[180px] truncate" title={m.ten_tour}>{m.ten_tour}</td>
                          <td className="px-2 py-2">{m.gia_raw || fmtVND(m.gia)}</td>
                          <td className="px-2 py-2">{fmtVND(m.price_day)}</td>
                          <td className="px-2 py-2"><GapBadge pct={m.price_gap_pct} /></td>
                          <td className="px-2 py-2">{m.departures_monthly}</td>
                          <td className="px-2 py-2">{m.link_url && <a href={m.link_url} target="_blank" rel="noopener noreferrer"><ExternalLink size={12} /></a>}</td>
                        </tr>
                      ))}
                      {!(matcherDetail.matches?.length) && (
                        <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">Không tìm thấy tour khớp đủ điểm</td></tr>
                      )}
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
              <p className="text-xs text-gray-500 mt-1">{detail.segment?.tuyen_tour} · {detail.segment?.diem_kh} · {fmtDays(detail.segment?.so_ngay)} · {detail.segment?.thi_truong}</p>
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
