import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { getHomeBrief, getDataQuality } from "@/lib/api";
import { fmtVND } from "@/lib/utils";
import { COL, GLOSSARY } from "@/lib/glossary";
import { InfoTip, PageTitle } from "@/components/InfoTip";
import {
  TrendingUp, TrendingDown, AlertTriangle, ArrowRight, Database, Scale, FileText, RefreshCw,
} from "lucide-react";

const SEV_COLOR: Record<string, string> = {
  critical: "border-red-400 bg-red-50",
  warning: "border-amber-400 bg-amber-50",
  info: "border-blue-200 bg-blue-50",
};

export default function IntelligenceHome() {
  const { data, refetch, isFetching } = useQuery({ queryKey: ["home-brief"], queryFn: getHomeBrief, staleTime: 60000 });
  const { data: quality } = useQuery({ queryKey: ["data-quality"], queryFn: getDataQuality });

  const kpis = data?.kpis;
  const delta = data?.delta;

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

      {/* KPI row — Giá first */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <div className="kpi-card border-l-4 border-l-primary-600">
          <span className="text-xs text-gray-500 inline-flex items-center">{COL.chenhPct}<InfoTip text={GLOSSARY.chenhGia} /></span>
          <p className="text-2xl font-bold">{kpis?.avg_gap_pct != null ? `${kpis.avg_gap_pct}%` : "—"}</p>
          {delta?.avg_gap_pct_delta != null && (
            <p className={`text-xs mt-1 flex items-center gap-0.5 ${(delta.avg_gap_pct_delta as number) > 0 ? "text-red-600" : "text-green-600"}`}>
              {(delta.avg_gap_pct_delta as number) > 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
              {delta.avg_gap_pct_delta}% vs hôm qua
            </p>
          )}
        </div>
        <div className="kpi-card"><span className="text-xs text-red-600">Đắt hơn TT</span><p className="text-2xl font-bold text-red-700">{kpis?.expensive_segments ?? "—"}</p></div>
        <div className="kpi-card"><span className="text-xs text-green-600">Rẻ hơn TT</span><p className="text-2xl font-bold text-green-700">{kpis?.cheaper_segments ?? "—"}</p></div>
        <div className="kpi-card"><span className="text-xs text-gray-500">Nhóm so sánh</span><p className="text-2xl font-bold">{kpis?.segment_count ?? "—"}</p></div>
        <div className="kpi-card"><span className="text-xs text-gray-500 inline-flex items-center">Tần suất +<InfoTip text={GLOSSARY.tanSuat} /></span><p className="text-2xl font-bold text-emerald-700">{kpis?.freq_leading ?? "—"}</p><p className="text-xs text-gray-400">/ {kpis?.freq_lagging ?? 0} kém</p></div>
        <div className="kpi-card"><span className="text-xs text-gray-500">Chưa phân loại</span><p className="text-2xl font-bold text-amber-700">{kpis?.unclassified_tours ?? "—"}</p></div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Insights */}
        <div className="lg:col-span-2 card p-5">
          <h2 className="font-semibold mb-4 flex items-center gap-2">
            <Scale size={18} /> Insight hôm nay
            <InfoTip text="Tự động từ so sánh giá, tần suất, phủ sóng & chất lượng dữ liệu" />
          </h2>
          <div className="space-y-2 max-h-[360px] overflow-auto">
            {(data?.insights ?? []).length === 0 && <p className="text-sm text-gray-400">Chưa có insight — thử làm mới snapshot</p>}
            {(data?.insights ?? []).map((ins) => (
              <Link
                key={ins.id}
                to={ins.link_path + (ins.link_params?.tab ? `?tab=${ins.link_params.tab}` : "")}
                className={`block p-3 rounded-lg border hover:shadow-sm transition-shadow ${SEV_COLOR[ins.severity] ?? SEV_COLOR.info}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <span className="text-[10px] uppercase font-semibold text-gray-500">{ins.category}</span>
                    <p className="text-sm font-medium text-gray-900">{ins.title}</p>
                    <p className="text-xs text-gray-600 mt-0.5">{ins.description}</p>
                  </div>
                  <ArrowRight size={16} className="text-gray-400 shrink-0 mt-1" />
                </div>
              </Link>
            ))}
          </div>
        </div>

        {/* Alerts + quality */}
        <div className="space-y-4">
          <div className="card p-4">
            <h3 className="font-semibold text-sm mb-3 flex items-center gap-1"><AlertTriangle size={16} /> Cảnh báo</h3>
            <ul className="space-y-2 max-h-[160px] overflow-auto text-xs">
              {(data?.alerts ?? []).slice(0, 6).map((a) => (
                <li key={a.id} className="border-l-2 border-amber-400 pl-2">
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
              {(data?.alerts ?? []).length === 0 && <li className="text-gray-400">Không có cảnh báo mới</li>}
            </ul>
          </div>
          <div className="card p-4">
            <h3 className="font-semibold text-sm mb-2 flex items-center gap-1"><Database size={16} /> Chất lượng dữ liệu</h3>
            {quality && (
              <ul className="text-xs space-y-1 text-gray-600">
                <li>Phân loại OK: <strong>{quality.classified_pct}%</strong></li>
                <li>Thiếu giá: {quality.no_price_count} · Thiếu điểm KH: {quality.no_departure_count}</li>
                <li>Flagged: {quality.flagged_count}</li>
              </ul>
            )}
            <Link to="/data" className="text-xs text-primary-600 mt-2 inline-block">Mở Sản phẩm & Data →</Link>
          </div>
        </div>
      </div>

      {/* Trend */}
      {(data?.trend ?? []).length > 1 && (
        <div className="card p-5">
          <h2 className="font-semibold mb-3">Xu hướng chênh giá TB (14 ngày)</h2>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={data?.trend}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v) => v.slice(5)} />
              <YAxis tickFormatter={(v) => `${v}%`} tick={{ fontSize: 10 }} />
              <Tooltip formatter={(v: number) => [`${v}%`, "Chênh TB"]} />
              <Line type="monotone" dataKey="avg_gap_pct" stroke="#003580" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Quick links */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { to: "/market-lab", label: "Market Lab", sub: "Cơ hội tuyến · lịch cung · triển vọng tuần" },
          { to: "/compare?tab=price", label: "So sánh giá", sub: "Chi tiết segment" },
          { to: "/compare?tab=frequency", label: "Tần suất KH", sub: "TB đoàn/tháng" },
          { to: "/compare?tab=coverage", label: "Phủ sóng", sub: "Khoảng trống tuyến" },
        ].map(({ to, label, sub }) => (
          <Link key={to} to={to} className="card p-4 hover:border-primary-400 border border-transparent transition-colors">
            <p className="font-semibold text-sm">{label}</p>
            <p className="text-xs text-gray-500">{sub}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
