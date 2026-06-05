import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend,
} from "recharts";
import { getHomeBrief, getDataQuality } from "@/lib/api";
import { fmtVND } from "@/lib/utils";
import { COL, GLOSSARY } from "@/lib/glossary";
import { InfoTip, PageTitle } from "@/components/InfoTip";
import { CountUp } from "@/components/CountUp";
import {
  TrendingUp, TrendingDown, AlertTriangle, ArrowRight, Database,
  Scale, FileText, RefreshCw, Bell, CheckCircle,
} from "lucide-react";

const SEV_COLOR: Record<string, string> = {
  critical: "border-red-400 bg-red-50",
  warning:  "border-amber-400 bg-amber-50",
  info:     "border-blue-200 bg-blue-50",
};

const CAT_LABEL: Record<string, string> = {
  price:    "Giá",
  frequency:"Tần suất",
  coverage: "Phủ sóng",
  quality:  "Chất lượng",
};
const CAT_COLOR: Record<string, string> = {
  price:    "text-red-700 bg-red-100",
  frequency:"text-amber-700 bg-amber-100",
  coverage: "text-emerald-700 bg-emerald-100",
  quality:  "text-gray-600 bg-gray-100",
};

function DeltaChip({ val, inverse = false }: { val: number | null | undefined; inverse?: boolean }) {
  if (val == null) return null;
  const good = inverse ? val < 0 : val > 0;
  return (
    <span className={`text-xs flex items-center gap-0.5 ${good ? "text-green-600" : "text-red-600"}`}>
      {val > 0 ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
      {val > 0 ? "+" : ""}{val} vs hôm qua
    </span>
  );
}

export default function IntelligenceHome() {
  const { data, refetch, isFetching } = useQuery({
    queryKey: ["home-brief"],
    queryFn: getHomeBrief,
    staleTime: 60_000,
  });
  const { data: quality } = useQuery({ queryKey: ["data-quality"], queryFn: getDataQuality });

  const kpis = data?.kpis;
  const delta = data?.delta;
  const unreadAlerts = (data?.alerts ?? []).length;

  // Group insights by category
  const insightsByCategory = (data?.insights ?? []).reduce<Record<string, typeof data.insights>>((acc, ins) => {
    const cat = ins.category || "other";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(ins);
    return acc;
  }, {});
  const catOrder = ["price", "frequency", "coverage", "quality"];

  // Summary 1 câu cho BGĐ
  const summaryText = (() => {
    if (!kpis) return null;
    const exp = kpis.expensive_segments ?? 0;
    const cheap = kpis.cheaper_segments ?? 0;
    const freqLag = kpis.freq_lagging ?? 0;
    const gap = kpis.avg_gap_pct;
    const parts: string[] = [];
    if (gap != null) parts.push(`Chênh giá TB ${gap > 0 ? "+" : ""}${gap}%`);
    if (exp > 0) parts.push(`${exp} tuyến đắt hơn TT`);
    if (cheap > 0) parts.push(`${cheap} tuyến rẻ hơn TT`);
    if (freqLag > 0) parts.push(`${freqLag} tuyến thiếu lịch KH`);
    return parts.join(" · ");
  })();

  return (
    <div className="p-6 space-y-6 max-w-7xl">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle title="Vietravel Intelligence Hub" tip="Brief hàng ngày — ưu tiên Giá → Tần suất → Phủ sóng" />
          <p className="text-sm text-gray-500 mt-1">
            Snapshot {data?.snapshot_date ?? "—"} · {(kpis?.total_tours ?? 0).toLocaleString("vi-VN")} sản phẩm tour
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => refetch()} className="btn-secondary text-xs flex items-center gap-1">
            <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} /> Làm mới
          </button>
          <Link to="/reports" className="btn-primary text-xs flex items-center gap-1">
            <FileText size={14} /> Báo cáo BGĐ
          </Link>
        </div>
      </div>

      {/* Summary 1 câu */}
      {summaryText && (
        <div className="card p-4 bg-primary-50 border border-primary-200">
          <p className="text-sm font-medium text-primary-900">
            <span className="font-semibold">Tóm tắt hôm nay: </span>{summaryText}
          </p>
        </div>
      )}

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 stagger">
        <div className="kpi-card hover-lift border-l-4 border-l-primary-600">
          <span className="text-xs text-gray-500 inline-flex items-center">{COL.chenhPct}<InfoTip text={GLOSSARY.chenhGia} /></span>
          <p className="text-2xl font-bold tabular-nums">{kpis?.avg_gap_pct != null ? <CountUp value={kpis.avg_gap_pct} decimals={1} suffix="%" /> : "—"}</p>
          <DeltaChip val={delta?.avg_gap_pct_delta as number | null} inverse />
        </div>
        <div className="kpi-card hover-lift">
          <span className="text-xs text-red-600">Đắt hơn TT</span>
          <p className="text-2xl font-bold text-red-700 tabular-nums"><CountUp value={kpis?.expensive_segments} /></p>
          {delta?.expensive_delta != null && <DeltaChip val={delta.expensive_delta as number} inverse />}
        </div>
        <div className="kpi-card hover-lift">
          <span className="text-xs text-green-600">Rẻ hơn TT</span>
          <p className="text-2xl font-bold text-green-700 tabular-nums"><CountUp value={kpis?.cheaper_segments} /></p>
          {delta?.cheaper_delta != null && <DeltaChip val={delta.cheaper_delta as number} />}
        </div>
        <div className="kpi-card hover-lift">
          <span className="text-xs text-gray-500">Nhóm so sánh</span>
          <p className="text-2xl font-bold tabular-nums"><CountUp value={kpis?.segment_count} /></p>
        </div>
        <div className="kpi-card hover-lift">
          <span className="text-xs text-gray-500 inline-flex items-center">TS dẫn/kém<InfoTip text={GLOSSARY.tanSuat} /></span>
          <p className="text-2xl font-bold tabular-nums">
            <span className="text-emerald-700"><CountUp value={kpis?.freq_leading ?? 0} /></span>
            <span className="text-gray-300 mx-1">/</span>
            <span className="text-amber-700"><CountUp value={kpis?.freq_lagging ?? 0} /></span>
          </p>
        </div>
        <div className="kpi-card hover-lift">
          <span className="text-xs text-gray-500">Chưa phân loại</span>
          <p className="text-2xl font-bold text-amber-700 tabular-nums"><CountUp value={kpis?.unclassified_tours} /></p>
          {delta?.unclassified_delta != null && <DeltaChip val={delta.unclassified_delta as number} inverse />}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Insights — grouped by category */}
        <div className="lg:col-span-2 card p-5">
          <h2 className="font-semibold mb-4 flex items-center gap-2">
            <Scale size={18} /> Insight hôm nay
            <InfoTip text="Tự động từ so sánh giá, tần suất, phủ sóng & chất lượng dữ liệu" />
          </h2>
          {(data?.insights ?? []).length === 0 && (
            <p className="text-sm text-gray-400">Chưa có insight — thử làm mới snapshot</p>
          )}
          <div className="space-y-5 max-h-[420px] overflow-auto pr-1">
            {catOrder.filter((c) => insightsByCategory[c]?.length).map((cat) => (
              <div key={cat}>
                <div className="flex items-center gap-2 mb-2">
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${CAT_COLOR[cat] ?? "bg-gray-100 text-gray-600"}`}>
                    {CAT_LABEL[cat] ?? cat}
                  </span>
                  <span className="text-xs text-gray-400">{insightsByCategory[cat].length} điểm</span>
                </div>
                <div className="space-y-1.5 pl-2">
                  {insightsByCategory[cat].map((ins) => (
                    <Link
                      key={ins.id}
                      to={ins.link_path + (ins.link_params?.tab ? `?tab=${ins.link_params.tab}` : "")}
                      className={`block p-2.5 rounded-lg border hover:shadow-sm transition-shadow ${SEV_COLOR[ins.severity] ?? SEV_COLOR.info}`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <p className="text-sm font-medium text-gray-900">{ins.title}</p>
                          <p className="text-xs text-gray-600 mt-0.5">{ins.description}</p>
                        </div>
                        <ArrowRight size={14} className="text-gray-400 shrink-0 mt-0.5" />
                      </div>
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right column */}
        <div className="space-y-4">
          {/* Alerts với unread badge */}
          <div className="card p-4">
            <h3 className="font-semibold text-sm mb-3 flex items-center gap-2">
              <AlertTriangle size={16} /> Cảnh báo
              {unreadAlerts > 0 && (
                <span className="ml-auto bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                  {unreadAlerts}
                </span>
              )}
            </h3>
            <ul className="space-y-2 max-h-[180px] overflow-auto text-xs">
              {(data?.alerts ?? []).slice(0, 8).map((a) => (
                <li key={a.id} className={`border-l-2 pl-2 ${a.severity === "critical" ? "border-red-500" : a.severity === "warning" ? "border-amber-400" : "border-blue-300"}`}>
                  {a.link_path ? (
                    <Link to={a.link_path} className="block hover:text-primary-600">
                      <p className="font-medium">{a.title}</p>
                      <p className="text-gray-500">{a.message}</p>
                    </Link>
                  ) : (
                    <>
                      <p className="font-medium">{a.title}</p>
                      <p className="text-gray-500">{a.message}</p>
                    </>
                  )}
                </li>
              ))}
              {(data?.alerts ?? []).length === 0 && (
                <li className="flex items-center gap-2 text-gray-400">
                  <CheckCircle size={14} className="text-green-500" /> Không có cảnh báo mới
                </li>
              )}
            </ul>
          </div>

          {/* Data quality — với progress bar */}
          <div className="card p-4">
            <h3 className="font-semibold text-sm mb-3 flex items-center gap-1">
              <Database size={16} /> Chất lượng dữ liệu
            </h3>
            {quality && (
              <div className="space-y-3 text-xs">
                <div>
                  <div className="flex justify-between mb-1">
                    <span className="text-gray-600">Phân loại OK</span>
                    <span className="font-bold text-gray-900">{quality.classified_pct}%</span>
                  </div>
                  <div className="w-full bg-gray-100 rounded-full h-1.5">
                    <div
                      className={`h-1.5 rounded-full ${quality.classified_pct >= 90 ? "bg-green-500" : quality.classified_pct >= 70 ? "bg-amber-500" : "bg-red-500"}`}
                      style={{ width: `${quality.classified_pct}%` }}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-gray-500">
                  <div className="bg-gray-50 rounded p-2">
                    <p className="font-medium text-gray-700">{quality.no_price_count}</p>
                    <p>Thiếu giá</p>
                  </div>
                  <div className="bg-gray-50 rounded p-2">
                    <p className="font-medium text-gray-700">{quality.no_departure_count}</p>
                    <p>Thiếu điểm KH</p>
                  </div>
                  <div className="bg-gray-50 rounded p-2">
                    <p className="font-medium text-amber-700">{quality.flagged_count}</p>
                    <p>Flagged</p>
                  </div>
                  <div className="bg-gray-50 rounded p-2">
                    <p className="font-medium text-gray-700">{quality.vtr_tours ?? "—"}</p>
                    <p>Tour VTR</p>
                  </div>
                </div>
              </div>
            )}
            <Link to="/data" className="text-xs text-primary-600 mt-2 inline-block">Mở Sản phẩm & Data →</Link>
          </div>
        </div>
      </div>

      {/* Trend — multi-metric */}
      {(data?.trend ?? []).length > 1 && (
        <div className="card p-5">
          <h2 className="font-semibold mb-1">Xu hướng 14 ngày</h2>
          <p className="text-xs text-gray-500 mb-4">Chênh giá TB (%) · Số nhóm đắt hơn / rẻ hơn thị trường</p>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data?.trend}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v) => v.slice(5)} />
              <YAxis yAxisId="pct" tickFormatter={(v) => `${v}%`} tick={{ fontSize: 10 }} width={36} />
              <YAxis yAxisId="count" orientation="right" tick={{ fontSize: 10 }} width={28} />
              <Tooltip
                labelFormatter={(v) => `Ngày ${v}`}
                formatter={(val: number, name: string) => [
                  name === "avg_gap_pct" ? `${val}%` : val,
                  name === "avg_gap_pct" ? "Chênh TB" : name === "expensive_segments" ? "Đắt hơn TT" : "Rẻ hơn TT",
                ]}
              />
              <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }}
                formatter={(v) => v === "avg_gap_pct" ? "Chênh giá TB (%)" : v === "expensive_segments" ? "Đắt hơn TT" : "Rẻ hơn TT"} />
              <Line yAxisId="pct" type="monotone" dataKey="avg_gap_pct" stroke="#003580" strokeWidth={2} dot={false} />
              <Line yAxisId="count" type="monotone" dataKey="expensive_segments" stroke="#dc2626" strokeWidth={1.5} dot={false} strokeDasharray="4 2" />
              <Line yAxisId="count" type="monotone" dataKey="cheaper_segments" stroke="#16a34a" strokeWidth={1.5} dot={false} strokeDasharray="4 2" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Quick links với KPI mini */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          {
            to: "/market-lab",
            label: "Market Lab",
            sub: "Cơ hội tuyến · lịch cung · triển vọng tuần",
            kpi: null,
          },
          {
            to: "/compare?tab=price",
            label: "So sánh giá",
            sub: "Chi tiết từng segment",
            kpi: kpis?.expensive_segments != null ? `${kpis.expensive_segments} tuyến đắt hơn TT` : null,
            kpiColor: "text-red-600",
          },
          {
            to: "/compare?tab=frequency",
            label: "Tần suất KH",
            sub: "TB đoàn/tháng",
            kpi: kpis?.freq_lagging != null ? `${kpis.freq_lagging} tuyến thiếu lịch` : null,
            kpiColor: "text-amber-600",
          },
          {
            to: "/compare?tab=coverage",
            label: "Phủ sóng",
            sub: "Khoảng trống tuyến",
            kpi: null,
          },
        ].map(({ to, label, sub, kpi, kpiColor }) => (
          <Link key={to} to={to} className="card p-4 hover:border-primary-400 border border-transparent transition-colors">
            <p className="font-semibold text-sm">{label}</p>
            <p className="text-xs text-gray-500 mt-0.5">{sub}</p>
            {kpi && <p className={`text-xs font-bold mt-1.5 ${kpiColor ?? "text-gray-700"}`}>{kpi}</p>}
          </Link>
        ))}
      </div>
    </div>
  );
}
