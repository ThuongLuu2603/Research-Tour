/**
 * Sự kiện & Lễ hội — Phase 1 + 2 + 3 unified.
 *
 * Tabs:
 *   - Lịch & Timeline  (Phase 1)
 *   - Coverage Gap     (Phase 2: VTR vs đối thủ)
 *   - Pricing Premium  (Phase 3 UC#2)
 *   - Demand Forecast  (Phase 3 UC#3)
 *   - Marketing        (Phase 3 UC#5)
 *   - Heatmap          (Phase 3 UC#6)
 *   - Lunar Planner    (Phase 3 UC#7)
 */
import { Fragment, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listFestivals, getFestivalStats, refreshFestivals,
  listFestivalTours, getFestival, getFestivalSummary, getCoverageGap, retagFestivals,
  getPricingPremium, getDemandForecast, getMarketingCalendar,
  getRegionHeatmap, getLunarPlanner, lunarSeed,
  getFestivalDashboardSummary,
  getFilterOptions,
  getFestivalMappingSummary, getFestivalMappingSuggestions, bulkCreateFestivalMappingRules,
  createFestivalMappingRule, applyFestivalMappingRules,
  Festival, FestivalRegion, FestivalCategory, FestivalFilters,
  FestivalTourLite, CoverageGapItemExt,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useNavigate } from "react-router-dom";
import {
  Calendar, List, MapPin, RefreshCw, Loader2, ExternalLink,
  Music, Utensils, Trophy, Sparkles, Building, ChevronLeft, ChevronRight,
  X, AlertTriangle, TrendingUp, TrendingDown, Megaphone, Map as MapIcon, Moon,
  LayoutDashboard, Bell, Target, BadgeCheck,
  Plus, Check, Wand2,
  LucideIcon,
} from "lucide-react";

const REGION_LABEL: Record<FestivalRegion, string> = {
  bac: "Bắc", trung: "Trung", nam: "Nam", intl: "Quốc tế", "": "Chưa rõ",
};
const REGION_COLOR: Record<FestivalRegion, string> = {
  bac: "bg-blue-100 text-blue-800 border-blue-200",
  trung: "bg-amber-100 text-amber-800 border-amber-200",
  nam: "bg-emerald-100 text-emerald-800 border-emerald-200",
  intl: "bg-purple-100 text-purple-800 border-purple-200",
  "": "bg-gray-100 text-gray-700 border-gray-200",
};
/**
 * Cho intl events, ưu tiên show country name thực thay vì generic "Quốc tế".
 * Festival.location_text có dạng "Seoul, Hàn Quốc" hoặc "Hàn Quốc" → extract.
 */
function regionDisplay(region: FestivalRegion, location_text?: string): string {
  if (region === "intl" && location_text) {
    // Lấy phần cuối của location_text (thường là country)
    const parts = location_text.split(",").map(s => s.trim()).filter(Boolean);
    const last = parts[parts.length - 1] || location_text;
    return last;
  }
  return REGION_LABEL[region];
}

const CATEGORY_META: Record<FestivalCategory, { label: string; Icon: LucideIcon }> = {
  cultural:  { label: "Văn hóa",   Icon: Sparkles },
  religious: { label: "Tâm linh",  Icon: Building },
  music:     { label: "Âm nhạc",   Icon: Music },
  food:      { label: "Ẩm thực",   Icon: Utensils },
  sport:     { label: "Thể thao",  Icon: Trophy },
  other:     { label: "Khác",      Icon: Sparkles },
};

function formatDateRange(start: string, end: string): string {
  const s = new Date(start), e = new Date(end);
  const fmt = (d: Date) => d.toLocaleDateString("vi-VN", { day: "2-digit", month: "short" });
  if (start === end) return `${fmt(s)}, ${s.getFullYear()}`;
  if (s.getMonth() === e.getMonth() && s.getFullYear() === e.getFullYear()) return `${s.getDate()} – ${fmt(e)}, ${e.getFullYear()}`;
  return `${fmt(s)} – ${fmt(e)}, ${e.getFullYear()}`;
}
function daysUntil(dateStr: string): number {
  const d = new Date(dateStr), today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.ceil((d.getTime() - today.getTime()) / 86400000);
}
function fmtVND(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("vi-VN", { maximumFractionDigits: 0 }) + "₫";
}

type TabKey = "dashboard" | "timeline" | "coverage" | "premium" | "forecast" | "marketing" | "heatmap" | "lunar";
const TABS: { key: TabKey; label: string; Icon: LucideIcon; group?: "discovery" | "analytics" | "action" }[] = [
  { key: "dashboard", label: "Tổng quan",           Icon: LayoutDashboard },
  { key: "timeline",  label: "Lịch & Timeline",     Icon: Calendar,     group: "discovery" },
  { key: "lunar",     label: "Lễ Âm Lịch",          Icon: Moon,         group: "discovery" },
  { key: "coverage",  label: "Coverage Gap",        Icon: AlertTriangle, group: "analytics" },
  { key: "premium",   label: "Pricing Premium",     Icon: TrendingUp,   group: "analytics" },
  { key: "heatmap",   label: "Heatmap tỉnh",        Icon: MapIcon,      group: "analytics" },
  { key: "forecast",  label: "Demand Forecast",     Icon: TrendingDown, group: "action" },
  { key: "marketing", label: "Marketing",           Icon: Megaphone,    group: "action" },
];

export default function FestivalsPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<TabKey>("dashboard");
  const [detailSlug, setDetailSlug] = useState<string | null>(null);

  const refresh = useMutation({
    mutationFn: refreshFestivals,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["festivals"] });
      qc.invalidateQueries({ queryKey: ["festival-stats"] });
    },
  });
  const retag = useMutation({
    mutationFn: () => retagFestivals(false),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["festivals"] });
      qc.invalidateQueries({ queryKey: ["festival-coverage-gap"] });
      qc.invalidateQueries({ queryKey: ["festival-premium"] });
    },
  });
  const seedLunar = useMutation({
    mutationFn: lunarSeed,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["festivals"] });
      qc.invalidateQueries({ queryKey: ["lunar-planner"] });
    },
  });

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Sự kiện & Lễ hội Việt Nam</h1>
          <p className="text-sm text-gray-500 mt-1">
            Lịch lễ hội + insight cross-ref tour. Data từ{" "}
            <a className="text-primary-600 hover:underline" href="https://lehoivietnam.com.vn/vi/kham-pha" target="_blank" rel="noreferrer">lehoivietnam.com.vn</a> + lễ âm lịch.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button type="button" className="btn-secondary text-xs"
            disabled={refresh.isPending} onClick={() => refresh.mutate()}
            title="Crawl từ vietnam.travel (admin)">
            {refresh.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {refresh.isPending ? "Đang quét..." : "Refresh scrape"}
          </button>
          <button type="button" className="btn-secondary text-xs"
            disabled={seedLunar.isPending} onClick={() => seedLunar.mutate()}
            title="Seed lễ âm lịch 6 năm (Tết, Trung Thu, Vu Lan, ...) (admin)">
            {seedLunar.isPending ? <Loader2 size={14} className="animate-spin" /> : <Moon size={14} />}
            Seed lễ âm
          </button>
          <button type="button" className="btn-secondary text-xs"
            disabled={retag.isPending} onClick={() => retag.mutate()}
            title="Re-tag tour theo lễ (admin)">
            {retag.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            Re-tag tour
          </button>
        </div>
      </div>

      {/* Tabs with subtle group dividers */}
      <div className="border-b border-gray-200 overflow-x-auto">
        <div className="flex items-end gap-1 min-w-max">
          {TABS.map((t, idx) => {
            const prevGroup = idx > 0 ? TABS[idx - 1].group : undefined;
            const showDivider = !!t.group && t.group !== prevGroup && idx > 0;
            return (
              <Fragment key={t.key}>
                {showDivider && <div className="self-stretch w-px bg-gray-200 mx-1" />}
                <button type="button" onClick={() => setTab(t.key)}
                  className={cn(
                    "px-3 py-2 text-sm font-medium border-b-2 transition-colors flex items-center gap-1.5 whitespace-nowrap",
                    tab === t.key ? "border-primary-600 text-primary-700" : "border-transparent text-gray-600 hover:text-gray-900"
                  )}>
                  <t.Icon size={14} /> {t.label}
                </button>
              </Fragment>
            );
          })}
        </div>
      </div>

      {/* Tab body */}
      <div>
        {tab === "dashboard" && <DashboardTab onJumpTab={setTab} onPickFestival={setDetailSlug} />}
        {tab === "timeline" && <TimelineTab onPickFestival={setDetailSlug} />}
        {tab === "coverage" && <CoverageGapTab onPickFestival={setDetailSlug} />}
        {tab === "premium" && <PricingPremiumTab />}
        {tab === "forecast" && <DemandForecastTab />}
        {tab === "marketing" && <MarketingTab />}
        {tab === "heatmap" && <HeatmapTab />}
        {tab === "lunar" && <LunarTab />}
      </div>

      {/* Detail modal */}
      {detailSlug && <FestivalDetailModal slug={detailSlug} onClose={() => setDetailSlug(null)} />}
    </div>
  );
}

// ── Tab 0: Smart Dashboard (default landing) ─────────────────────────────

function DashboardTab({ onJumpTab, onPickFestival }: {
  onJumpTab: (k: TabKey) => void;
  onPickFestival: (slug: string) => void;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["festival-dashboard"],
    queryFn: getFestivalDashboardSummary,
    staleTime: 5 * 60 * 1000,
  });
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox msg={(error as Error).message} />;
  if (!data) return null;
  const { alerts, quick_stats, data_quality } = data;

  // Data quality overall score (0-100)
  const dqScore = Math.round((
    data_quality.festivals_with_location_pct +
    data_quality.festivals_with_province_pct +
    data_quality.tours_with_province_pct +
    data_quality.tours_tagged_festival_pct
  ) / 4);
  const dqColor = dqScore >= 75 ? "emerald" : dqScore >= 50 ? "amber" : "red";

  return (
    <div className="space-y-4">
      {/* Hero quick stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard label="Lễ 30 ngày tới" value={quick_stats.upcoming_30d} accent="primary" />
        <StatCard label="Lễ 90 ngày tới" value={quick_stats.upcoming_90d} />
        <StatCard label="Tour gắn lễ" value={quick_stats.tours_tagged_festival.toLocaleString("vi-VN")} isText />
        <StatCard label="VTR cover" value={quick_stats.vtr_tours_tagged_festival.toLocaleString("vi-VN")} isText />
        <StatCard
          label="VTR / tổng"
          value={`${Math.round((quick_stats.vtr_cover_ratio || 0) * 100)}%`}
          isText
          accent={quick_stats.vtr_cover_ratio >= 0.3 ? "primary" : undefined}
        />
      </div>

      {/* SMART ALERTS — 3 priority cards */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        {/* Alert 1: Critical 30d */}
        <AlertCard
          icon={<Bell size={16} />}
          tone={alerts.critical_30d_count > 0 ? "red" : "gray"}
          title="Lễ sắp tới VTR chưa cover"
          count={alerts.critical_30d_count}
          subtitle={alerts.critical_30d_count > 0
            ? `${alerts.critical_30d_count} lễ trong 30 ngày tới mà VTR chưa có tour nào`
            : "Không có lễ nào VTR thiếu cover trong 30 ngày tới"}
          actionLabel="Xem timeline"
          onAction={() => onJumpTab("timeline")}
        >
          {alerts.critical_30d.slice(0, 5).map((f) => (
            <button key={f.slug} type="button"
              onClick={() => onPickFestival(f.slug)}
              className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-red-100/60 transition-colors border-t border-red-100 first:border-t-0">
              <p className="font-medium text-red-900 truncate" title={f.name}>{f.name}</p>
              <p className="text-[10px] text-red-700">
                Còn {f.days_until}d · {regionDisplay(f.region, f.location_text)}
              </p>
            </button>
          ))}
        </AlertCard>

        {/* Alert 2: Under-served provinces */}
        <AlertCard
          icon={<Target size={16} />}
          tone={alerts.under_served_count > 0 ? "amber" : "gray"}
          title="Tỉnh có lễ nhưng VTR=0"
          count={alerts.under_served_count}
          subtitle={alerts.under_served_count > 0
            ? `${alerts.under_served_count} tỉnh có ≥2 lễ trong 90 ngày tới mà VTR chưa có tour`
            : "Tất cả tỉnh có lễ đều đã có tour VTR"}
          actionLabel="Xem heatmap"
          onAction={() => onJumpTab("heatmap")}
        >
          {alerts.under_served.slice(0, 5).map((p) => (
            <div key={p.province_code}
              className="text-xs px-2 py-1.5 border-t border-amber-100 first:border-t-0 flex items-center justify-between gap-2">
              <span className="font-medium text-amber-900 truncate flex items-center gap-1">
                <MapPin size={11} /> {p.province_name}
              </span>
              <span className="text-amber-700 text-[10px] shrink-0">
                {p.festival_count} lễ · VTR=0
              </span>
            </div>
          ))}
        </AlertCard>

        {/* Alert 3: Top coverage gaps */}
        <AlertCard
          icon={<AlertTriangle size={16} />}
          tone={alerts.top_gaps_count > 0 ? "orange" : "gray"}
          title="Đối thủ cover nhiều, VTR thiếu"
          count={alerts.top_gaps_count}
          subtitle={alerts.top_gaps_count > 0
            ? `Top ${alerts.top_gaps_count} lễ competitor mạnh nhất mà VTR chưa cạnh tranh`
            : "Không có gap đáng kể"}
          actionLabel="Xem Coverage Gap"
          onAction={() => onJumpTab("coverage")}
        >
          {alerts.top_gaps.slice(0, 5).map((g) => (
            <button key={g.slug} type="button"
              onClick={() => onPickFestival(g.slug)}
              className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-orange-100/60 transition-colors border-t border-orange-100 first:border-t-0">
              <p className="font-medium text-orange-900 truncate" title={g.name}>{g.name}</p>
              <p className="text-[10px] text-orange-700">
                Đối thủ: <strong>{g.competitor_tours}</strong> · VTR: <strong>{g.vtr_tours}</strong> · gap {g.gap_score.toFixed(1)}
              </p>
            </button>
          ))}
        </AlertCard>
      </div>

      {/* Data Quality + Quick actions */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Data Quality */}
        <div className="card p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-1.5">
              <BadgeCheck size={14} /> Chất lượng dữ liệu
            </h3>
            <span className={cn(
              "text-xs font-bold px-2 py-0.5 rounded-full",
              dqColor === "emerald" ? "bg-emerald-100 text-emerald-800" :
              dqColor === "amber" ? "bg-amber-100 text-amber-800" : "bg-red-100 text-red-800"
            )}>
              {dqScore}/100
            </span>
          </div>
          <div className="space-y-2 text-xs">
            <QualityBar label="Lễ có địa điểm" value={data_quality.festivals_with_location_pct} />
            <QualityBar label="Lễ có province_code" value={data_quality.festivals_with_province_pct} />
            <QualityBar label="Tour có province_code" value={data_quality.tours_with_province_pct} />
            <QualityBar label="Tour đã tag lễ" value={data_quality.tours_tagged_festival_pct} />
          </div>
          <p className="text-[10px] text-gray-500 mt-3 italic">
            Tổng: {data_quality.festivals_total.toLocaleString("vi-VN")} lễ upcoming ·{" "}
            {data_quality.tours_total.toLocaleString("vi-VN")} tour
          </p>
        </div>

        {/* Quick actions */}
        <div className="card p-4">
          <h3 className="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-1.5">
            <Sparkles size={14} /> Quick actions
          </h3>
          <div className="grid grid-cols-2 gap-2">
            <QuickAction Icon={Calendar} label="Xem lịch lễ 90 ngày" onClick={() => onJumpTab("timeline")} />
            <QuickAction Icon={TrendingUp} label="Phân tích Premium %" onClick={() => onJumpTab("premium")} />
            <QuickAction Icon={Megaphone} label="Marketing 12 tháng" onClick={() => onJumpTab("marketing")} />
            <QuickAction Icon={MapIcon} label="Heatmap tỉnh" onClick={() => onJumpTab("heatmap")} />
            <QuickAction Icon={Moon} label="Lễ âm lịch" onClick={() => onJumpTab("lunar")} />
            <QuickAction Icon={TrendingDown} label="Demand forecast 6 tháng" onClick={() => onJumpTab("forecast")} />
          </div>
        </div>
      </div>
    </div>
  );
}

function AlertCard({ icon, tone, title, count, subtitle, actionLabel, onAction, children }: {
  icon: React.ReactNode;
  tone: "red" | "amber" | "orange" | "gray";
  title: string;
  count: number;
  subtitle: string;
  actionLabel: string;
  onAction: () => void;
  children?: React.ReactNode;
}) {
  const toneClass = {
    red: "border-red-200 bg-red-50/40",
    amber: "border-amber-200 bg-amber-50/40",
    orange: "border-orange-200 bg-orange-50/40",
    gray: "border-gray-200 bg-gray-50/40",
  }[tone];
  const accentText = {
    red: "text-red-700",
    amber: "text-amber-700",
    orange: "text-orange-700",
    gray: "text-gray-500",
  }[tone];
  return (
    <div className={cn("card overflow-hidden border", toneClass)}>
      <div className="p-3 border-b border-current/10">
        <div className="flex items-start justify-between gap-2 mb-1">
          <div className={cn("font-semibold text-sm flex items-center gap-1.5", accentText)}>
            {icon} {title}
          </div>
          <span className={cn("text-xl font-bold leading-none", accentText)}>
            {count}
          </span>
        </div>
        <p className="text-[11px] text-gray-600">{subtitle}</p>
      </div>
      {count > 0 && children && (
        <div className="bg-white/40 max-h-56 overflow-y-auto">
          {children}
        </div>
      )}
      <button type="button" onClick={onAction}
        className={cn(
          "w-full px-3 py-2 text-xs font-medium border-t flex items-center justify-center gap-1 transition-colors hover:bg-white/60",
          accentText
        )}>
        {actionLabel} <ChevronRight size={12} />
      </button>
    </div>
  );
}

function QualityBar({ label, value }: { label: string; value: number }) {
  const color = value >= 75 ? "bg-emerald-500" : value >= 50 ? "bg-amber-500" : "bg-red-500";
  return (
    <div>
      <div className="flex justify-between text-gray-700 mb-0.5">
        <span>{label}</span>
        <span className="font-semibold">{value}%</span>
      </div>
      <div className="h-1.5 bg-gray-100 rounded overflow-hidden">
        <div className={cn("h-full transition-all", color)} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

function QuickAction({ Icon, label, onClick }: { Icon: LucideIcon; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 hover:border-primary-300 hover:bg-primary-50/40 transition-colors text-left">
      <Icon size={16} className="text-primary-600 shrink-0" />
      <span className="text-xs text-gray-700 font-medium">{label}</span>
    </button>
  );
}

// ── Tab 1: Timeline ──────────────────────────────────────────────────────

function _isoDateAdd(days: number): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function TimelineTab({ onPickFestival }: { onPickFestival: (slug: string) => void }) {
  const [view, setView] = useState<"timeline" | "calendar">("timeline");
  const [filters, setFilters] = useState<FestivalFilters>({});
  const [search, setSearch] = useState("");
  const [calendarMonth, setCalendarMonth] = useState<Date>(() => {
    const d = new Date(); d.setDate(1); return d;
  });

  const { data: festivals, isLoading, error } = useQuery({
    queryKey: ["festivals", filters],
    queryFn: () => listFestivals(filters),
    staleTime: 6 * 60 * 60 * 1000,
  });
  const { data: stats } = useQuery({
    queryKey: ["festival-stats"],
    queryFn: getFestivalStats,
    staleTime: 6 * 60 * 60 * 1000,
  });

  // Filter client-side bằng search keyword (tránh re-fetch API mỗi keystroke)
  const filteredFestivals = useMemo(() => {
    if (!festivals) return [];
    if (!search.trim()) return festivals;
    const kw = search.toLowerCase().trim();
    return festivals.filter((f) =>
      (f.name_vi || "").toLowerCase().includes(kw)
      || (f.location_text || "").toLowerCase().includes(kw)
      || (f.description || "").toLowerCase().includes(kw)
    );
  }, [festivals, search]);

  // Helpers cho stat card click
  const setRangeUpcoming = (days: number) => {
    setFilters((f) => ({ ...f, from: _isoDateAdd(0), to: _isoDateAdd(days) }));
  };
  const resetRange = () => {
    setFilters((f) => ({ ...f, from: undefined, to: undefined }));
  };

  return (
    <div className="space-y-4">
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Tổng số sự kiện" value={stats.total}
            onClick={resetRange}
            active={!filters.from && !filters.to}
          />
          <StatCard label="Sắp diễn ra (30 ngày)" value={stats.upcoming_30d} accent="primary"
            onClick={() => setRangeUpcoming(30)}
            active={filters.to === _isoDateAdd(30)}
          />
          <StatCard label="Sắp diễn ra (90 ngày)" value={stats.upcoming_90d}
            onClick={() => setRangeUpcoming(90)}
            active={filters.to === _isoDateAdd(90)}
          />
          <StatCard label="Vùng nhiều lễ nhất" isText value={
            (() => {
              const top = Object.entries(stats.by_region).sort((a, b) => b[1] - a[1])[0]?.[0];
              return top === "bac" ? "Miền Bắc" : top === "trung" ? "Miền Trung" : top === "nam" ? "Miền Nam" : "—";
            })()
          } />
        </div>
      )}
      <div className="card p-4 space-y-3">
        <div className="flex flex-wrap gap-3 items-end">
          <FilterSelect label="Vùng" value={filters.region ?? ""}
            onChange={(v) => setFilters((f) => ({ ...f, region: (v || undefined) as FestivalRegion | undefined }))}
            options={[
              { value: "", label: "Tất cả vùng" }, { value: "bac", label: "Miền Bắc" },
              { value: "trung", label: "Miền Trung" }, { value: "nam", label: "Miền Nam" },
              { value: "intl", label: "Quốc tế" },
            ]} />
          <FilterSelect label="Loại lễ" value={filters.category ?? ""}
            onChange={(v) => setFilters((f) => ({ ...f, category: (v || undefined) as FestivalCategory | undefined }))}
            options={[
              { value: "", label: "Tất cả loại" }, { value: "cultural", label: "Văn hóa" },
              { value: "religious", label: "Tâm linh" }, { value: "music", label: "Âm nhạc" },
              { value: "food", label: "Ẩm thực" }, { value: "sport", label: "Thể thao" },
              { value: "other", label: "Khác" },
            ]} />
          <div>
            <label className="text-xs text-gray-500 block mb-0.5">Giai đoạn từ</label>
            <input type="date" className="input text-sm"
              value={filters.from ?? ""}
              onChange={(e) => setFilters((f) => ({ ...f, from: e.target.value || undefined }))} />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-0.5">Đến</label>
            <input type="date" className="input text-sm"
              value={filters.to ?? ""}
              onChange={(e) => setFilters((f) => ({ ...f, to: e.target.value || undefined }))} />
          </div>
          {(filters.from || filters.to) && (
            <button type="button" className="text-xs text-gray-500 hover:text-gray-900 underline"
              onClick={() => setFilters((f) => ({ ...f, from: undefined, to: undefined }))}>
              Xóa giai đoạn
            </button>
          )}
          <div className="ml-auto flex gap-1 bg-gray-100 p-1 rounded-md">
            <ViewButton active={view === "timeline"} onClick={() => setView("timeline")}>
              <List size={14} /> Timeline
            </ViewButton>
            <ViewButton active={view === "calendar"} onClick={() => setView("calendar")}>
              <Calendar size={14} /> Calendar
            </ViewButton>
          </div>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-0.5">Tìm tên sự kiện</label>
          <input type="text" className="input text-sm w-full"
            placeholder="Vd: Festival Huế, Đắk Lắk, Sầu riêng..."
            value={search}
            onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>

      {isLoading && (
        <div className="card p-12 text-center text-gray-400">
          <Loader2 size={32} className="animate-spin mx-auto mb-3" /> Đang tải lễ hội…
        </div>
      )}
      {error && <div className="card p-6 text-red-600 text-sm">Lỗi tải: {(error as Error).message}</div>}
      {!isLoading && filteredFestivals.length === 0 && (
        <div className="card p-12 text-center text-gray-400 space-y-3">
          <Calendar size={40} className="mx-auto" />
          <p className="text-sm">
            {search ? `Không có sự kiện nào khớp "${search}".` : "Chưa có dữ liệu lễ hội."}
          </p>
          {!search && (
            <p className="text-xs">Bấm <strong>Refresh scrape</strong> để crawl, hoặc <strong>Seed lễ âm</strong> để có Tết/Trung Thu.</p>
          )}
        </div>
      )}
      {!isLoading && filteredFestivals.length > 0 && (
        <p className="text-xs text-gray-500">
          Hiển thị <strong>{filteredFestivals.length}</strong> sự kiện
          {festivals && filteredFestivals.length < festivals.length && (
            <span> · lọc từ {festivals.length}</span>
          )}
        </p>
      )}
      {!isLoading && filteredFestivals.length > 0 && view === "timeline" && (
        <TimelineView festivals={filteredFestivals} onPick={onPickFestival} />
      )}
      {!isLoading && filteredFestivals.length > 0 && view === "calendar" && (
        <CalendarView festivals={filteredFestivals} month={calendarMonth} onPick={onPickFestival}
          onPrev={() => setCalendarMonth((d) => new Date(d.getFullYear(), d.getMonth() - 1, 1))}
          onNext={() => setCalendarMonth((d) => new Date(d.getFullYear(), d.getMonth() + 1, 1))} />
      )}
    </div>
  );
}

function TimelineView({ festivals, onPick }: { festivals: Festival[]; onPick: (slug: string) => void }) {
  const groups = useMemo(() => {
    const m = new Map<string, Festival[]>();
    for (const f of festivals) {
      const k = f.date_start.slice(0, 7);
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(f);
    }
    return Array.from(m.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [festivals]);
  return (
    <div className="space-y-8">
      {groups.map(([month, items]) => (
        <div key={month}>
          <div className="sticky top-0 bg-gray-50/95 backdrop-blur z-10 py-2 mb-3 -mx-6 px-6">
            <h2 className="text-sm font-bold text-gray-700 uppercase tracking-wide">
              {new Date(month + "-01").toLocaleDateString("vi-VN", { month: "long", year: "numeric" })}
              <span className="text-gray-400 font-normal ml-2">· {items.length} lễ hội</span>
            </h2>
          </div>
          <div className="space-y-3 relative pl-6 border-l-2 border-gray-200">
            {items.map((f) => <TimelineCard key={f.id} festival={f} onClick={() => onPick(f.slug)} />)}
          </div>
        </div>
      ))}
    </div>
  );
}

function TimelineCard({ festival: f, onClick }: { festival: Festival; onClick: () => void }) {
  const { Icon, label: catLabel } = CATEGORY_META[f.category] ?? CATEGORY_META.other;
  const days = daysUntil(f.date_start);
  return (
    <div className="relative">
      <div className="absolute -left-[27px] top-3 w-3 h-3 rounded-full bg-primary-500 ring-4 ring-white" />
      <button type="button" onClick={onClick} className="card p-4 hover:shadow-md transition-shadow text-left w-full">
        <div className="flex gap-4">
          {f.image_url && (
            <div className="hidden sm:block shrink-0">
              <img src={f.image_url} alt={f.name_vi} className="w-24 h-24 rounded-lg object-cover bg-gray-100" loading="lazy" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2 mb-1">
              <h3 className="font-semibold text-gray-900 leading-tight">{f.name_vi}</h3>
              {days >= 0 && days <= 30 && (
                <span className="badge bg-primary-100 text-primary-800 text-[10px] shrink-0">Còn {days} ngày</span>
              )}
            </div>
            <p className="text-xs text-gray-500 mb-2 flex items-center gap-1 flex-wrap">
              <Calendar size={12} /> {formatDateRange(f.date_start, f.date_end)}
              {f.location_text && (<><span className="mx-1">·</span><MapPin size={12} /> {f.location_text}</>)}
            </p>
            <div className="flex items-center gap-1.5 flex-wrap mb-2">
              {f.region && (
                <span className={cn("inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border", REGION_COLOR[f.region])}>
                  {f.region === "intl" ? regionDisplay(f.region, f.location_text) : `Miền ${REGION_LABEL[f.region]}`}
                </span>
              )}
              <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-700 border border-gray-200">
                <Icon size={10} /> {catLabel}
              </span>
              {f.is_lunar && (
                <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-800 border border-purple-200">
                  <Moon size={10} /> Âm lịch
                </span>
              )}
            </div>
            {f.description && <p className="text-xs text-gray-600 line-clamp-2">{f.description}</p>}
          </div>
        </div>
      </button>
    </div>
  );
}

function CalendarView({ festivals, month, onPrev, onNext, onPick }: {
  festivals: Festival[]; month: Date; onPrev: () => void; onNext: () => void; onPick: (slug: string) => void;
}) {
  const eventsByDay = useMemo(() => {
    const m = new Map<string, Festival[]>();
    for (const f of festivals) {
      const start = new Date(f.date_start), end = new Date(f.date_end);
      for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        const k = d.toISOString().slice(0, 10);
        if (!m.has(k)) m.set(k, []);
        m.get(k)!.push(f);
      }
    }
    return m;
  }, [festivals]);
  const days = useMemo(() => {
    const firstDow = new Date(month.getFullYear(), month.getMonth(), 1).getDay();
    const daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    const cells: (Date | null)[] = [];
    const padStart = firstDow === 0 ? 6 : firstDow - 1;
    for (let i = 0; i < padStart; i++) cells.push(null);
    for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(month.getFullYear(), month.getMonth(), d));
    while (cells.length % 7) cells.push(null);
    return cells;
  }, [month]);
  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between p-3 border-b">
        <button type="button" className="btn-secondary text-xs" onClick={onPrev}><ChevronLeft size={14} /></button>
        <h2 className="font-semibold text-gray-900">
          {month.toLocaleDateString("vi-VN", { month: "long", year: "numeric" })}
        </h2>
        <button type="button" className="btn-secondary text-xs" onClick={onNext}><ChevronRight size={14} /></button>
      </div>
      <div className="grid grid-cols-7 bg-gray-50 border-b text-xs font-medium text-gray-600">
        {["T2", "T3", "T4", "T5", "T6", "T7", "CN"].map((d) => (
          <div key={d} className="py-2 px-2 text-center">{d}</div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {days.map((d, i) => {
          if (!d) return <div key={i} className="aspect-square border-r border-b bg-gray-50/30" />;
          const k = d.toISOString().slice(0, 10);
          const evts = eventsByDay.get(k) ?? [];
          const isToday = d.toDateString() === new Date().toDateString();
          return (
            <div key={i} className={cn("min-h-[80px] border-r border-b p-1.5 text-xs", isToday && "bg-primary-50")}>
              <p className={cn("text-[10px] mb-1 font-semibold", isToday ? "text-primary-700" : "text-gray-500")}>
                {d.getDate()}
              </p>
              <div className="space-y-1">
                {evts.slice(0, 3).map((f) => (
                  <button key={f.id} type="button" onClick={() => onPick(f.slug)}
                    className={cn("text-[10px] px-1.5 py-0.5 rounded truncate border w-full text-left", REGION_COLOR[f.region])}
                    title={f.name_vi}>
                    {f.name_vi}
                  </button>
                ))}
                {evts.length > 3 && <p className="text-[10px] text-gray-500">+{evts.length - 3} lễ</p>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Tab 2: Coverage Gap (Issue #5 Phase B redesign) ──────────────────────
//
// Major changes vs prev:
//   1. Header summary chip: X/Y festivals có mapping rule + click → /rules#festival
//      + button "🔮 Gợi ý mapping" → AutoSuggestModal.
//   2. Per-row badge "✓ Có rule" / "✗ Chưa rule" — click "Chưa rule" mở inline
//      MappingCreateModal.
//   3. Split VTR/Competitor counters thành tagged/implied columns (nếu backend
//      Phase A trả về extended fields).
//   4. Sort priority: chưa rule + gap cao → top. Visual hierarchy border-left:
//        red   = no rule + high gap   (priority cao nhất)
//        orange= có rule + high gap   (rule quá narrow)
//        green = fully covered (VTR ≥ competitor)
//        gray  = default
//
// Backend coord notes:
//   - getFestivalMappingSummary(): GET /festivals/insights/coverage-gap/mapping-summary
//   - getFestivalMappingSuggestions(): GET /festivals/insights/coverage-gap/mapping-suggestions
//   - bulkCreateFestivalMappingRules(): POST /admin/rules/festival-mapping/bulk
//   - CoverageGapItemExt extended fields (vtr_tours_tagged, has_rule…): backend
//     Phase A đang implement, FE fallback graceful nếu field undefined.

function CoverageGapTab({ onPickFestival }: { onPickFestival: (slug: string) => void }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [showSuggest, setShowSuggest] = useState(false);
  const [createModal, setCreateModal] = useState<{
    festival_slug: string;
    location_keyword: string;
    festival_name: string;
  } | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["festival-coverage-gap"],
    queryFn: () => getCoverageGap(30),
    staleTime: 60 * 60 * 1000,
  });

  // Mapping summary — graceful fallback nếu endpoint backend chưa sẵn sàng.
  const { data: summary } = useQuery({
    queryKey: ["festival-mapping-summary"],
    queryFn: getFestivalMappingSummary,
    staleTime: 60 * 60 * 1000,
    retry: false,
  });

  if (isLoading) return <Loading />;
  if (error) return <ErrorBox msg={(error as Error).message} />;
  if (!data || data.length === 0) return (
    <EmptyState>
      Chưa có dữ liệu. Bấm <strong>Re-tag tour</strong> để map tour với lễ hội trước.
    </EmptyState>
  );

  // Sort priority: no rule + high gap_score → top.
  // Có rule + low gap → bottom. Stable sort theo gap_score desc trong nhóm.
  const sorted = [...(data as CoverageGapItemExt[])].sort((a, b) => {
    const aNoRule = a.has_rule === false ? 1 : 0;
    const bNoRule = b.has_rule === false ? 1 : 0;
    if (aNoRule !== bNoRule) return bNoRule - aNoRule;
    return b.gap_score - a.gap_score;
  });

  const totalGap = data.filter((r) => r.vtr_tours === 0 && r.competitor_tours > 0).length;
  const partialGap = data.filter((r) => r.vtr_tours > 0 && r.vtr_tours < r.competitor_tours).length;

  return (
    <div className="space-y-3">
      {/* Header — Mapping coverage chip + actions */}
      <div className="card border-primary-100 bg-gradient-to-r from-primary-50/60 to-amber-50/40 p-3 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 flex-1 min-w-[240px]">
          <BadgeCheck size={18} className="text-primary-700 shrink-0" />
          {summary ? (
            <button
              type="button"
              onClick={() => navigate("/rules#festival")}
              className="text-left hover:underline"
              title="Mở Quy tắc phân loại → tab Lễ hội"
            >
              <p className="text-sm font-semibold text-primary-900">
                {summary.festivals_with_rule}/{summary.total_festivals} festival có mapping rule
                <span className="ml-2 text-xs text-primary-700">({summary.coverage_pct}%)</span>
              </p>
              <p className="text-[11px] text-gray-600 mt-0.5">
                Click để mở Quy tắc phân loại — tab Lễ hội ↗
              </p>
            </button>
          ) : (
            <p className="text-xs text-gray-600 italic">Đang tải mapping summary…</p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setShowSuggest(true)}
          className="btn-primary text-xs flex items-center gap-1.5"
        >
          <Wand2 size={14} /> Gợi ý mapping
        </button>
      </div>

      {/* Method hint */}
      <div className="card border-amber-100 bg-amber-50/40 p-3 text-xs text-gray-700">
        <p className="flex items-start gap-1.5">
          <AlertTriangle size={14} className="text-amber-600 shrink-0 mt-0.5" />
          <span>
            <strong>Coverage gap</strong> = lễ hội mà đối thủ có tour cover (cùng địa điểm tổ chức) nhưng VTR chưa có/ít.
            Cột <strong>Tagged</strong> = tour đã được tag festival qua mapping rule;
            cột <strong>Implied</strong> = tour cùng location nhưng chưa có rule cụ thể.
            Festival <span className="text-red-700 font-semibold">Chưa rule</span> + gap cao → ưu tiên tạo mapping ngay.
          </span>
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Tổng lễ phân tích" value={data.length} />
        <StatCard label="Hoàn toàn miss (VTR=0)" value={totalGap} accent="primary" />
        <StatCard label="Cover thiếu" value={partialGap} />
        <StatCard label="Lễ VTR đủ cover" value={data.length - totalGap - partialGap} />
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              <th className="px-3 py-2 text-left">Lễ hội</th>
              <th className="px-3 py-2 text-left">Ngày</th>
              <th className="px-3 py-2 text-left" title="Điểm tổ chức của lễ hội — dùng làm khóa khớp với Tuyến tour qua mapping rule">
                Điểm tổ chức
              </th>
              <th className="px-3 py-2 text-right">VTR (tagged / implied)</th>
              <th className="px-3 py-2 text-right">Đối thủ (tagged / implied)</th>
              <th className="px-3 py-2 text-left">Top đối thủ</th>
              <th className="px-3 py-2 text-center">Rule</th>
              <th className="px-3 py-2 text-right">Gap</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => {
              const hasRule = row.has_rule === true;
              const noRule = row.has_rule === false;
              const fullyCovered = row.vtr_tours > 0 && row.vtr_tours >= row.competitor_tours;
              // Visual hierarchy border-left:
              //   red  = no rule + high gap (priority)
              //   orange= có rule + still high gap (rule too narrow)
              //   green= fully covered
              const borderClass =
                noRule && row.gap_score > 2 ? "border-l-4 border-red-500" :
                hasRule && row.gap_score > 2 ? "border-l-4 border-orange-400" :
                fullyCovered ? "border-l-4 border-emerald-400" :
                "border-l-4 border-transparent";

              const vtrTagged = row.vtr_tours_tagged ?? row.vtr_tours;
              const vtrImplied = row.vtr_tours_implied ?? 0;
              const compTagged = row.competitor_tours_tagged ?? row.competitor_tours;
              const compImplied = row.competitor_tours_implied ?? 0;
              const locationText = row.location_text ?? row.location ?? "";

              return (
                <tr key={row.slug} className={cn("border-t hover:bg-gray-50", borderClass)}>
                  <td className="px-3 py-2">
                    <button type="button" className="text-primary-600 hover:underline text-left" onClick={() => onPickFestival(row.slug)}>
                      {row.name}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-600">{formatDateRange(row.date_start, row.date_end)}</td>
                  <td className="px-3 py-2">
                    {/* Điểm tổ chức = location_text scrape được. Đây là khóa khớp với
                        rule.location_keyword (substring) → suy ra tour có tuyen_tour
                        cùng khu vực. Vùng/region chỉ là badge phụ. */}
                    {locationText ? (
                      <div className="flex flex-col gap-0.5">
                        <span className="inline-flex items-center gap-1 text-xs text-gray-800 font-medium max-w-[200px]" title={locationText}>
                          <MapPin size={11} className="text-gray-500 shrink-0" />
                          <span className="truncate">{locationText}</span>
                        </span>
                        {row.region && row.region !== "intl" && (
                          <span className={cn("text-[9px] px-1.5 py-0.5 rounded border w-fit", REGION_COLOR[row.region as FestivalRegion])}>
                            Miền {regionDisplay(row.region as FestivalRegion, locationText)}
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="text-[10px] text-gray-400 italic">Chưa có điểm tổ chức</span>
                    )}
                  </td>
                  <td className={cn("px-3 py-2 text-right font-mono text-xs", row.vtr_tours === 0 && "text-red-600 font-bold")}>
                    <span>{vtrTagged}</span>
                    {row.vtr_tours_implied !== undefined && (
                      <span className="text-gray-400"> / {vtrImplied}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs">
                    <span>{compTagged}</span>
                    {row.competitor_tours_implied !== undefined && (
                      <span className="text-gray-400"> / {compImplied}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-700">
                    {Object.entries(row.top_competitors).slice(0, 3).map(([co, cnt]) => (
                      <span key={co} className="inline-block mr-2">
                        {co}: <strong>{cnt}</strong>
                      </span>
                    ))}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {row.has_rule === undefined ? (
                      <span className="text-[10px] text-gray-400">—</span>
                    ) : hasRule ? (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200">
                        <Check size={10} /> Có rule
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setCreateModal({
                          festival_slug: row.slug,
                          festival_name: row.name,
                          location_keyword: locationText,
                        })}
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded-full bg-red-100 text-red-800 border border-red-200 hover:bg-red-200 transition-colors"
                        title="Click để tạo mapping rule cho festival này"
                      >
                        <Plus size={10} /> Chưa rule
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span className={cn(
                      "inline-block px-2 py-0.5 rounded text-xs font-semibold",
                      row.gap_score > 5 ? "bg-red-100 text-red-800" : row.gap_score > 2 ? "bg-amber-100 text-amber-800" : "bg-gray-100 text-gray-700"
                    )}>
                      {row.gap_score.toFixed(1)}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {showSuggest && (
        <AutoSuggestModal
          onClose={() => setShowSuggest(false)}
          onCreated={() => {
            qc.invalidateQueries({ queryKey: ["festival-coverage-gap"] });
            qc.invalidateQueries({ queryKey: ["festival-mapping-summary"] });
            qc.invalidateQueries({ queryKey: ["festival-mapping-rules"] });
          }}
        />
      )}

      {createModal && (
        <MappingCreateModal
          festivalName={createModal.festival_name}
          initialLocationKeyword={createModal.location_keyword}
          onClose={() => setCreateModal(null)}
          onCreated={() => {
            setCreateModal(null);
            qc.invalidateQueries({ queryKey: ["festival-coverage-gap"] });
            qc.invalidateQueries({ queryKey: ["festival-mapping-summary"] });
            qc.invalidateQueries({ queryKey: ["festival-mapping-rules"] });
          }}
        />
      )}
    </div>
  );
}

// ── AutoSuggestModal — bulk-create mapping rules từ suggestions ──────────────

function AutoSuggestModal({
  onClose, onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["festival-mapping-suggestions"],
    queryFn: () => getFestivalMappingSuggestions(20),
    staleTime: 5 * 60 * 1000,
  });

  // Track checked state cho từng suggestion (key = festival_slug).
  // Pre-check theo confidence rule:
  //   > 0.8 → checked
  //   > 0.5 → unchecked (user review)
  //   < 0.5 → unchecked
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [initialized, setInitialized] = useState(false);

  // Initialize pre-checks 1 lần khi data load xong.
  useMemo(() => {
    if (!data || initialized) return;
    const next = new Set<string>();
    data.suggestions.forEach((s) => {
      if (s.confidence > 0.8) next.add(s.festival_slug);
    });
    setChecked(next);
    setInitialized(true);
  }, [data, initialized]);

  const createMut = useMutation({
    mutationFn: async (rules: Array<{ location_keyword: string; market_keyword?: string; route_keyword?: string }>) => {
      const res = await bulkCreateFestivalMappingRules(rules);
      // Áp dụng NGAY (tag tour thật) thay vì chỉ "chạy nền" → người dùng thấy kết quả liền.
      let tagged = 0;
      try { tagged = (await applyFestivalMappingRules()).tours_tagged ?? 0; } catch { /* ignore */ }
      return { ...res, tagged };
    },
    onSuccess: (res) => {
      onCreated();
      // eslint-disable-next-line no-alert
      alert(`Đã tạo ${res.inserted} rule · gắn ${res.tagged} tour vào lễ.`);
      onClose();
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      // eslint-disable-next-line no-alert
      alert(err.response?.data?.detail || err.message || "Lỗi tạo bulk mapping");
    },
  });

  const toggle = (slug: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug); else next.add(slug);
      return next;
    });
  };

  const handleSubmit = () => {
    if (!data) return;
    const rules = data.suggestions
      .filter((s) => checked.has(s.festival_slug))
      .map((s) => ({
        location_keyword: s.location_keyword,
        market_keyword: s.suggested_market || undefined,
        route_keyword: s.suggested_route || undefined,
      }));
    if (rules.length === 0) {
      // eslint-disable-next-line no-alert
      alert("Chọn ít nhất 1 mapping để tạo");
      return;
    }
    createMut.mutate(rules);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-2xl max-w-4xl w-full max-h-[90vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <h3 className="text-base font-bold flex items-center gap-2">
            <Wand2 size={16} className="text-primary-600" />
            Gợi ý mapping rules (Auto-suggest)
          </h3>
          <button type="button" onClick={onClose} className="text-gray-500 hover:text-gray-900">
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {isLoading && <Loading />}
          {error && <ErrorBox msg={(error as Error).message} />}
          {data && data.suggestions.length === 0 && (
            <EmptyState>Không có gợi ý nào. Có thể tất cả festival đã có rule hoặc location_text chưa parse được.</EmptyState>
          )}
          {data && data.suggestions.length > 0 && (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-center w-10">
                    <input
                      type="checkbox"
                      checked={data.suggestions.every((s) => checked.has(s.festival_slug))}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setChecked(new Set(data.suggestions.map((s) => s.festival_slug)));
                        } else {
                          setChecked(new Set());
                        }
                      }}
                    />
                  </th>
                  <th className="px-3 py-2 text-left">Lễ hội</th>
                  <th className="px-3 py-2 text-left">Location</th>
                  <th className="px-3 py-2 text-left">Thị trường</th>
                  <th className="px-3 py-2 text-left">Tuyến tour</th>
                  <th className="px-3 py-2 text-right">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {data.suggestions.map((s) => {
                  const isChecked = checked.has(s.festival_slug);
                  const confPct = Math.round(s.confidence * 100);
                  const confClass =
                    s.confidence > 0.8 ? "bg-emerald-100 text-emerald-800" :
                    s.confidence > 0.5 ? "bg-amber-100 text-amber-800" :
                    "bg-gray-100 text-gray-700";
                  return (
                    <tr key={s.festival_slug} className={cn("border-t hover:bg-gray-50", isChecked && "bg-primary-50/40")}>
                      <td className="px-3 py-2 text-center">
                        <input type="checkbox" checked={isChecked} onChange={() => toggle(s.festival_slug)} />
                      </td>
                      <td className="px-3 py-2 text-xs">
                        <span className="font-medium text-gray-900">{s.festival_name}</span>
                        {s.reason && <p className="text-[10px] text-gray-500 mt-0.5">{s.reason}</p>}
                      </td>
                      <td className="px-3 py-2 text-xs text-gray-700">
                        <span className="font-mono text-[11px] bg-gray-100 px-1 rounded">{s.location_keyword}</span>
                        {s.location_text && s.location_text !== s.location_keyword && (
                          <p className="text-[10px] text-gray-500 mt-0.5">{s.location_text}</p>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs">{s.suggested_market || <span className="text-gray-400">—</span>}</td>
                      <td className="px-3 py-2 text-xs">{s.suggested_route || <span className="text-gray-400">—</span>}</td>
                      <td className="px-3 py-2 text-right">
                        <span className={cn("inline-block px-2 py-0.5 rounded text-xs font-semibold", confClass)}>
                          {confPct}%
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer */}
        <div className="border-t px-4 py-3 flex items-center justify-between bg-gray-50 rounded-b-lg">
          <p className="text-xs text-gray-600">
            <strong>{checked.size}</strong> mapping đã chọn
            {data && ` / ${data.suggestions.length} gợi ý`}
            <span className="ml-3 text-gray-400">
              (✓ pre-check confidence &gt; 80%)
            </span>
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="btn-secondary text-xs">Huỷ</button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={createMut.isPending || checked.size === 0}
              className="btn-primary text-xs flex items-center gap-1.5 disabled:opacity-50"
            >
              {createMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Tạo {checked.size} mapping
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── MappingCreateModal — inline single-row create từ "Chưa rule" badge ───────

function MappingCreateModal({
  festivalName, initialLocationKeyword, onClose, onCreated,
}: {
  festivalName: string;
  initialLocationKeyword: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [locationKeyword, setLocationKeyword] = useState(initialLocationKeyword);
  const [marketKeyword, setMarketKeyword] = useState("");
  const [routeKeyword, setRouteKeyword] = useState("");
  const [note, setNote] = useState("");

  // Dropdown TT/Tuyến từ filter-options (DB-driven).
  const { data: opts } = useQuery({
    queryKey: ["filter-options"],
    queryFn: getFilterOptions,
    staleTime: 60_000,
  });
  const availableRoutes = useMemo(() => {
    if (!marketKeyword || !opts) return (opts?.tuyen_tour ?? []) as string[];
    return (opts.routes_by_market[marketKeyword] ?? []) as string[];
  }, [marketKeyword, opts]);

  const createMut = useMutation({
    mutationFn: () => createFestivalMappingRule({
      location_keyword: locationKeyword.trim(),
      market_keyword: marketKeyword.trim() || undefined,
      route_keyword: routeKeyword.trim() || undefined,
      note: note.trim() || undefined,
    }),
    onSuccess: onCreated,
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      // eslint-disable-next-line no-alert
      alert(err.response?.data?.detail || err.message || "Lỗi tạo mapping rule");
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-2xl max-w-md w-full" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <h3 className="text-sm font-bold flex items-center gap-2">
            <Plus size={14} className="text-primary-600" />
            Tạo mapping cho: <span className="text-primary-700">{festivalName}</span>
          </h3>
          <button type="button" onClick={onClose} className="text-gray-500 hover:text-gray-900">
            <X size={18} />
          </button>
        </div>

        <div className="p-4 space-y-3">
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1">
              Location keyword <span className="text-red-500">*</span>
            </label>
            <input
              autoFocus
              className="input text-sm w-full"
              value={locationKeyword}
              onChange={(e) => setLocationKeyword(e.target.value)}
              placeholder="vd: Đà Lạt, Hội An…"
            />
            <p className="text-[10px] text-gray-500 mt-0.5">
              Keyword tìm match trong tour.diem_kh / ten_tour. Prefilled từ location của festival.
            </p>
          </div>

          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1">Thị trường</label>
            <select
              className="input text-sm w-full"
              value={marketKeyword}
              onChange={(e) => {
                setMarketKeyword(e.target.value);
                // Reset route nếu không thuộc TT mới
                if (e.target.value && opts) {
                  const routes = (opts.routes_by_market[e.target.value] ?? []) as string[];
                  if (!routes.includes(routeKeyword)) setRouteKeyword("");
                }
              }}
            >
              <option value="">— bất kỳ —</option>
              {(opts?.thi_truong ?? []).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1">
              Tuyến tour {marketKeyword && <span className="text-gray-400 text-[10px]">(theo TT)</span>}
            </label>
            <select
              className="input text-sm w-full"
              value={routeKeyword}
              onChange={(e) => setRouteKeyword(e.target.value)}
            >
              <option value="">— bất kỳ —</option>
              {availableRoutes.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1">Ghi chú</label>
            <input
              className="input text-sm w-full"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="(tuỳ chọn)"
            />
          </div>
        </div>

        <div className="border-t px-4 py-3 flex items-center justify-end gap-2 bg-gray-50 rounded-b-lg">
          <button type="button" onClick={onClose} className="btn-secondary text-xs">Huỷ</button>
          <button
            type="button"
            onClick={() => createMut.mutate()}
            disabled={createMut.isPending || !locationKeyword.trim()}
            className="btn-primary text-xs flex items-center gap-1.5 disabled:opacity-50"
          >
            {createMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            Tạo mapping
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Tab 3: Pricing Premium ───────────────────────────────────────────────

function PricingPremiumTab() {
  const [showMethod, setShowMethod] = useState(false);
  const { data, isLoading, error } = useQuery({
    queryKey: ["festival-premium"],
    queryFn: () => getPricingPremium(20),
    staleTime: 60 * 60 * 1000,
  });
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox msg={(error as Error).message} />;
  if (!data || data.summary.routes_analyzed === 0) return (
    <EmptyState>Chưa đủ dữ liệu so sánh. Cần &gt;3 tour không lễ + &gt;2 tour có lễ trên cùng tuyến.</EmptyState>
  );
  return (
    <div className="space-y-4">
      {/* Method explanation — collapsible */}
      <div className="card border-primary-100 bg-primary-50/40 overflow-hidden">
        <button type="button" onClick={() => setShowMethod((v) => !v)}
          className="w-full px-3 py-2 flex items-center justify-between text-left hover:bg-primary-50/60">
          <span className="text-xs font-semibold text-primary-900 flex items-center gap-1.5">
            <TrendingUp size={13} /> Cách tính Premium %
          </span>
          <ChevronRight size={14} className={cn("text-primary-700 transition-transform", showMethod && "rotate-90")} />
        </button>
        {showMethod && (
          <div className="px-3 pb-3 text-xs text-gray-700 space-y-2 border-t border-primary-100">
            <p className="pt-2">
              <strong>Premium %</strong> = mức giá tăng (hoặc giảm) của tour gắn lễ so với tour cùng tuyến nhưng KHÔNG gắn lễ.
            </p>
            <p>
              <strong>Pipeline (6 bước):</strong>
            </p>
            <ol className="list-decimal list-inside space-y-1 pl-1">
              <li>Lọc tour có giá trong khoảng <strong>500K – 500M VND</strong> (loại outlier do scrape lỗi).</li>
              <li>Loại tour có thị trường "Không xác định" (rule toàn hệ thống).</li>
              <li>Gom nhóm theo <code className="bg-white px-1 rounded">(thị_trường, tuyến_tour, has_festival)</code>.</li>
              <li>Chỉ giữ nhóm có <strong>≥3 tour không lễ</strong> + <strong>≥2 tour có lễ</strong>.</li>
              <li>Dùng <strong>median</strong> (không phải mean) — robust với outlier.</li>
              <li>Premium % = (median_có_lễ − median_không_lễ) / median_không_lễ × 100. Bỏ qua nếu |premium| {`>`} 500%.</li>
            </ol>
            <p className="text-gray-600 italic">
              Ví dụ: tour "Nha Trang" có lễ median 8M, không lễ median 6M → Premium = +33%.
            </p>
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Tuyến phân tích" value={data.summary.routes_analyzed} />
        <StatCard label="Premium TB" value={`${data.summary.avg_premium_pct}%`} accent="primary" isText />
        <StatCard label="Tour gắn lễ" value={data.summary.tours_with_festival} />
        <StatCard label="Tour không lễ" value={data.summary.tours_without_festival} />
      </div>
      <div className="grid lg:grid-cols-2 gap-4">
        <PremiumTable title="Top tăng giá (Premium cao)" rows={data.top_premium_routes} positive />
        {data.top_discount_routes.length > 0 && (
          <PremiumTable title="Top giảm giá (Discount)" rows={data.top_discount_routes} positive={false} />
        )}
      </div>
    </div>
  );
}

function PremiumTable({ title, rows, positive }: {
  title: string; rows: import("@/lib/api").PremiumRoute[]; positive: boolean;
}) {
  return (
    <div className="card overflow-hidden">
      <div className="p-3 border-b bg-gray-50">
        <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-gray-50/50">
            <tr>
              <th className="px-2 py-1.5 text-left">Tuyến</th>
              <th className="px-2 py-1.5 text-right">N có lễ</th>
              <th className="px-2 py-1.5 text-right">Giá có lễ</th>
              <th className="px-2 py-1.5 text-right">Giá thường</th>
              <th className="px-2 py-1.5 text-right">Premium</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.thi_truong}-${r.tuyen_tour}-${i}`} className="border-t hover:bg-gray-50">
                <td className="px-2 py-1.5 max-w-[180px] truncate" title={`${r.thi_truong} / ${r.tuyen_tour}`}>
                  <span className="text-gray-500">{r.thi_truong}</span>{" "}
                  <span className="text-gray-900 font-medium">{r.tuyen_tour}</span>
                </td>
                <td className="px-2 py-1.5 text-right font-mono">{r.n_with_festival}</td>
                <td className="px-2 py-1.5 text-right font-mono">{fmtVND(r.avg_price_with_festival)}</td>
                <td className="px-2 py-1.5 text-right font-mono text-gray-500">{fmtVND(r.avg_price_without_festival)}</td>
                <td className={cn(
                  "px-2 py-1.5 text-right font-mono font-bold",
                  positive ? "text-emerald-700" : "text-red-700",
                )}>
                  {positive ? "+" : ""}{r.premium_pct}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Tab 4: Demand Forecast ───────────────────────────────────────────────

function DemandForecastTab() {
  const [expandedMonth, setExpandedMonth] = useState<string | null>(null);
  const [pickedSlug, setPickedSlug] = useState<string | null>(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ["festival-forecast"],
    queryFn: () => getDemandForecast(6),
    staleTime: 60 * 60 * 1000,
  });
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox msg={(error as Error).message} />;
  if (!data) return null;
  return (
    <div className="space-y-3">
      <div className="card border-primary-100 bg-primary-50/40 p-3 text-xs text-gray-700">
        <p className="flex items-start gap-1.5">
          <TrendingDown size={14} className="text-primary-600 shrink-0 mt-0.5" />
          <span>
            <strong>Mục đích:</strong> dự báo nhu cầu inventory theo tháng dựa trên số lễ + độ phủ tour hiện tại.
            Tháng <span className="text-red-700 font-semibold">đỏ (high)</span> = nhiều lễ, ít tour VTR → cơ hội mở tour mới.
            Tháng <span className="text-amber-700 font-semibold">vàng (medium)</span> = cần check cover.
            <strong> Click card</strong> để xem chi tiết lễ + tour và mở action.
          </span>
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {data.forecast.map((m) => {
          const isExpanded = expandedMonth === m.month_label;
          return (
            <button key={m.month_label} type="button"
              onClick={() => setExpandedMonth(isExpanded ? null : m.month_label)}
              className={cn(
                "card p-4 border-l-4 text-left w-full hover:shadow-md transition-all",
                m.inventory_recommendation === "high" ? "border-red-500" :
                m.inventory_recommendation === "medium" ? "border-amber-500" : "border-gray-300",
                isExpanded && "ring-2 ring-primary-300",
              )}>
              <div className="flex items-start justify-between mb-2">
                <h3 className="text-base font-bold text-gray-900">{m.month_label}</h3>
                <span className={cn(
                  "badge text-[10px]",
                  m.inventory_recommendation === "high" ? "bg-red-100 text-red-800" :
                  m.inventory_recommendation === "medium" ? "bg-amber-100 text-amber-800" : "bg-gray-100 text-gray-700",
                )}>
                  {m.inventory_label}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center mb-3 text-xs">
                <div>
                  <p className="font-bold text-lg text-primary-700">{m.festival_count}</p>
                  <p className="text-gray-500 text-[10px]">Lễ hội</p>
                </div>
                <div>
                  <p className="font-bold text-lg text-gray-900">{m.tour_count}</p>
                  <p className="text-gray-500 text-[10px]">Tour gắn</p>
                </div>
                <div>
                  <p className="font-bold text-lg text-emerald-700">{m.vtr_tour_count}</p>
                  <p className="text-gray-500 text-[10px]">VTR cover</p>
                </div>
              </div>
              {m.top_region && (
                <p className="text-xs text-gray-600 mb-2">
                  Vùng nhiều lễ: <strong>{REGION_LABEL[m.top_region as FestivalRegion] ?? m.top_region}</strong>
                </p>
              )}
              {m.top_festivals.length > 0 && (
                <div className="space-y-1 pt-2 border-t">
                  {m.top_festivals.slice(0, isExpanded ? 10 : 3).map((f) => (
                    <button key={f.slug} type="button"
                      onClick={(e) => { e.stopPropagation(); setPickedSlug(f.slug); }}
                      className="block text-left text-[11px] text-primary-700 hover:underline truncate w-full"
                      title={f.name}>
                      • {f.name}
                    </button>
                  ))}
                  {!isExpanded && m.top_festivals.length > 3 && (
                    <p className="text-[10px] text-gray-400 italic">+{m.top_festivals.length - 3} lễ khác — click để xem</p>
                  )}
                </div>
              )}
              {isExpanded && m.inventory_recommendation !== "low" && (
                <div className="mt-3 pt-2 border-t border-amber-200 bg-amber-50/40 -mx-4 -mb-4 px-4 pb-3 rounded-b">
                  <p className="text-[10px] font-semibold text-amber-800 uppercase tracking-wide mb-1">Suggested action</p>
                  <p className="text-xs text-amber-900">
                    {m.inventory_recommendation === "high"
                      ? `Tháng nhu cầu CAO — ${m.festival_count} lễ nhưng chỉ ${m.vtr_tour_count} tour VTR cover. Đề xuất mở thêm tour ${m.top_region ? REGION_LABEL[m.top_region as FestivalRegion] : "vùng tương ứng"}.`
                      : `Tháng nhu cầu trung bình — review tour ${m.top_region ? REGION_LABEL[m.top_region as FestivalRegion] : ""} để tăng cover.`}
                  </p>
                </div>
              )}
            </button>
          );
        })}
      </div>
      {pickedSlug && <FestivalDetailModal slug={pickedSlug} onClose={() => setPickedSlug(null)} />}
    </div>
  );
}

// ── Tab 5: Marketing ────────────────────────────────────────────────────

function MarketingTab() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["festival-marketing"],
    queryFn: () => getMarketingCalendar(12),
    staleTime: 60 * 60 * 1000,
  });
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox msg={(error as Error).message} />;
  if (!data || data.length === 0) return <EmptyState>Chưa có dữ liệu marketing.</EmptyState>;
  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-600">Marketing calendar 12 tháng — mỗi lễ kèm campaign hint + 3 tour VTR đề xuất push.</p>
      <div className="space-y-3">
        {data.map((item) => (
          <div key={item.slug} className="card p-4">
            <div className="flex items-start justify-between gap-3 mb-2 flex-wrap">
              <div>
                <h3 className="font-bold text-gray-900">{item.name}</h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  <Calendar size={11} className="inline mr-1" />
                  {formatDateRange(item.date_start, item.date_end)}
                </p>
              </div>
              <div className="flex gap-1.5 flex-wrap">
                {item.region && (
                  <span className={cn("text-[10px] px-1.5 py-0.5 rounded border", REGION_COLOR[item.region as FestivalRegion])}>
                    {item.region === "intl" ? regionDisplay(item.region as FestivalRegion, item.location_text) : `Miền ${REGION_LABEL[item.region as FestivalRegion]}`}
                  </span>
                )}
                {item.is_lunar && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-800 border border-purple-200">Âm lịch</span>
                )}
              </div>
            </div>
            <div className="rounded bg-primary-50 border border-primary-100 p-2 mb-3 text-xs text-primary-800">
              <Megaphone size={12} className="inline mr-1" />
              <strong>Campaign hint:</strong> {item.campaign_hint}
            </div>
            {item.suggested_tours.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-700 mb-1.5">Tour VTR đề xuất push:</p>
                <ul className="space-y-1">
                  {item.suggested_tours.map((t) => (
                    <li key={t.id} className="text-xs flex items-center gap-2">
                      <span className="text-gray-900 flex-1 truncate">{t.ten_tour}</span>
                      <span className="text-gray-500 shrink-0">{t.so_ngay ? `${t.so_ngay}N` : "?"}</span>
                      <span className="text-emerald-700 font-mono shrink-0">{fmtVND(t.gia)}</span>
                      {t.link_url && (
                        <a href={t.link_url} target="_blank" rel="noreferrer" className="text-primary-600">
                          <ExternalLink size={11} />
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Tab 6: Heatmap Vùng ─────────────────────────────────────────────────

function HeatmapTab() {
  const [filterRegion, setFilterRegion] = useState<"all" | "bac" | "trung" | "nam">("all");
  const [sortBy, setSortBy] = useState<"festival" | "tour" | "underserved">("underserved");
  const { data, isLoading, error } = useQuery({
    queryKey: ["festival-heatmap"],
    queryFn: getRegionHeatmap,
    staleTime: 60 * 60 * 1000,
  });
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox msg={(error as Error).message} />;
  if (!data) return null;

  const maxRegion = Math.max(...data.regions.map((r) => Math.max(r.festival_count, r.tour_with_festival)), 1);
  const filteredProvinces = data.provinces
    .filter((p) => filterRegion === "all" || p.region === filterRegion)
    .sort((a, b) => {
      if (sortBy === "underserved") return Number(b.is_under_served) - Number(a.is_under_served) || b.festival_count - a.festival_count;
      if (sortBy === "festival") return b.festival_count - a.festival_count;
      return b.tour_count - a.tour_count;
    });
  const maxProvFest = Math.max(...filteredProvinces.map((p) => p.festival_count), 1);
  const maxProvTour = Math.max(...filteredProvinces.map((p) => p.tour_count), 1);
  const underservedCount = data.provinces.filter((p) => p.is_under_served).length;

  return (
    <div className="space-y-4">
      {/* Method hint */}
      <div className="card border-primary-100 bg-primary-50/40 p-3 text-xs text-gray-700">
        <p className="flex items-start gap-1.5">
          <MapIcon size={14} className="text-primary-600 shrink-0 mt-0.5" />
          <span>
            <strong>Heatmap mật độ lễ × tour</strong> theo tỉnh + vùng. Tỉnh{" "}
            <span className="text-amber-700 font-semibold">under-served</span> = có ≥2 lễ nhưng VTR=0 hoặc ratio &lt;50%.
          </span>
        </p>
      </div>

      {/* Region rollup */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold text-gray-800 mb-3">Tổng quan 3 vùng</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {data.regions.map((r) => (
            <div key={r.region} className={cn(
              "rounded-lg border p-3",
              r.is_under_served ? "border-amber-300 bg-amber-50" : "border-gray-200",
            )}>
              <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
                <h4 className="font-bold text-gray-900">Miền {r.region_label}</h4>
                {r.is_under_served && (
                  <span className="badge bg-amber-200 text-amber-900 text-[10px]">
                    <AlertTriangle size={10} /> Under-served
                  </span>
                )}
              </div>
              <div className="grid grid-cols-4 gap-2 text-center mb-2 text-xs">
                <div>
                  <p className="font-bold text-base text-primary-700">{r.festival_count}</p>
                  <p className="text-gray-500 text-[10px]">Lễ</p>
                </div>
                <div>
                  <p className="font-bold text-base text-gray-900">{r.tour_count.toLocaleString("vi-VN")}</p>
                  <p className="text-gray-500 text-[10px]">Tour</p>
                </div>
                <div>
                  <p className="font-bold text-base text-emerald-700">{r.tour_with_festival}</p>
                  <p className="text-gray-500 text-[10px]">Tour gắn lễ</p>
                </div>
                <div>
                  <p className="font-bold text-base text-amber-700">{r.vtr_tour_count}</p>
                  <p className="text-gray-500 text-[10px]">VTR</p>
                </div>
              </div>
              <div className="space-y-1.5">
                <BarStat label="Lễ" value={r.festival_count} max={maxRegion} color="bg-primary-500" />
                <BarStat label="Tour gắn lễ" value={r.tour_with_festival} max={maxRegion} color="bg-emerald-500" />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Province detail */}
      <div className="card">
        <div className="p-3 border-b bg-gray-50 flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-gray-800">
            Chi tiết theo tỉnh thành ({filteredProvinces.length}/{data.total_provinces_with_data})
          </h3>
          <div className="flex flex-wrap gap-2 items-center">
            <FilterSelect label="Vùng" value={filterRegion} onChange={(v) => setFilterRegion(v as "all" | "bac" | "trung" | "nam")}
              options={[
                { value: "all", label: `Tất cả (${data.provinces.length})` },
                { value: "bac", label: "Miền Bắc" },
                { value: "trung", label: "Miền Trung" },
                { value: "nam", label: "Miền Nam" },
              ]} />
            <FilterSelect label="Sắp xếp" value={sortBy} onChange={(v) => setSortBy(v as "festival" | "tour" | "underserved")}
              options={[
                { value: "underserved", label: `Under-served trước (${underservedCount})` },
                { value: "festival", label: "Theo số lễ" },
                { value: "tour", label: "Theo số tour" },
              ]} />
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-gray-50/50">
              <tr>
                <th className="px-2 py-2 text-left">Tỉnh thành</th>
                <th className="px-2 py-2 text-left">Vùng</th>
                <th className="px-2 py-2 text-right whitespace-nowrap">Lễ</th>
                <th className="px-2 py-2 text-left min-w-[140px]">Mật độ lễ</th>
                <th className="px-2 py-2 text-right whitespace-nowrap">Tour</th>
                <th className="px-2 py-2 text-left min-w-[140px]">Mật độ tour</th>
                <th className="px-2 py-2 text-right whitespace-nowrap">VTR</th>
                <th className="px-2 py-2 text-right whitespace-nowrap">Tour gắn lễ</th>
                <th className="px-2 py-2 text-right whitespace-nowrap">Ratio</th>
                <th className="px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {filteredProvinces.map((p) => (
                <tr key={p.province_code} className={cn(
                  "border-t hover:bg-gray-50",
                  p.is_under_served && "bg-amber-50/40"
                )}>
                  <td className="px-2 py-1.5 font-medium text-gray-900 whitespace-nowrap">
                    <MapPin size={11} className="inline mr-1 text-gray-400" />
                    {p.province_name}
                  </td>
                  <td className="px-2 py-1.5">
                    <span className={cn("text-[10px] px-1.5 py-0.5 rounded border", REGION_COLOR[(p.region || "") as FestivalRegion])}>
                      {REGION_LABEL[(p.region || "") as FestivalRegion] ?? p.region}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono font-semibold text-primary-700">{p.festival_count}</td>
                  <td className="px-2 py-1.5">
                    <div className="bg-gray-100 rounded h-2 relative overflow-hidden">
                      <div className="bg-primary-500 h-full rounded" style={{ width: `${(p.festival_count / maxProvFest) * 100}%` }} />
                    </div>
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono text-gray-900">{p.tour_count.toLocaleString("vi-VN")}</td>
                  <td className="px-2 py-1.5">
                    <div className="bg-gray-100 rounded h-2 relative overflow-hidden">
                      <div className="bg-gray-700 h-full rounded" style={{ width: `${(p.tour_count / maxProvTour) * 100}%` }} />
                    </div>
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono text-amber-700">{p.vtr_tour_count}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-emerald-700">{p.tour_with_festival}</td>
                  <td className="px-2 py-1.5 text-right">
                    <span className={cn(
                      "inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold",
                      p.festival_coverage_ratio >= 1 ? "bg-emerald-100 text-emerald-800" :
                      p.festival_coverage_ratio >= 0.5 ? "bg-amber-100 text-amber-800" : "bg-red-100 text-red-800"
                    )}>
                      {p.festival_coverage_ratio.toFixed(2)}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    {p.is_under_served && (
                      <span className="badge bg-amber-200 text-amber-900 text-[10px] whitespace-nowrap">
                        <AlertTriangle size={10} /> Mở tour
                      </span>
                    )}
                  </td>
                </tr>
              ))}
              {filteredProvinces.length === 0 && (
                <tr><td colSpan={10} className="text-center text-gray-400 py-8">Không có tỉnh nào trong bộ lọc.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function BarStat({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div>
      <p className="text-gray-600 mb-1">{label}: <strong>{value}</strong></p>
      <div className="h-2 bg-gray-200 rounded overflow-hidden">
        <div className={cn("h-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ── Tab 7: Lunar ────────────────────────────────────────────────────────

function LunarTab() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["lunar-planner"],
    queryFn: () => getLunarPlanner(3),
    staleTime: 6 * 60 * 60 * 1000,
  });
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox msg={(error as Error).message} />;
  if (!data || data.events.length === 0) return (
    <EmptyState>
      Chưa seed lễ âm lịch. Bấm <strong>Seed lễ âm</strong> ở header để add Tết / Trung Thu / Vu Lan 6 năm.
    </EmptyState>
  );
  // Group theo năm
  const byYear: Record<number, typeof data.events> = {};
  for (const ev of data.events) {
    if (!byYear[ev.year]) byYear[ev.year] = [];
    byYear[ev.year].push(ev);
  }
  return (
    <div className="space-y-6">
      <p className="text-xs text-gray-600">
        Lễ âm lịch (Tết, Trung Thu, Vu Lan...) → dương lịch cho 3 năm tới. Dùng để long-range plan booking sớm 12 tháng.
      </p>
      {Object.entries(byYear).sort().map(([year, events]) => (
        <div key={year}>
          <h2 className="text-lg font-bold text-gray-900 mb-3">{year}</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {events.map((ev) => (
              <div key={ev.slug} className="card p-3 border-l-4 border-purple-400">
                <div className="flex items-start justify-between mb-1 gap-2">
                  <h3 className="font-semibold text-gray-900 text-sm leading-tight">{ev.name}</h3>
                  <Moon size={14} className="text-purple-500 shrink-0" />
                </div>
                <p className="text-xs text-gray-600 mb-1">
                  <Calendar size={11} className="inline mr-1" />
                  {formatDateRange(ev.date_start, ev.date_end)}
                </p>
                <p className="text-[10px] text-gray-500">
                  Âm: <strong>{ev.lunar_month}/{ev.lunar_day}</strong>
                </p>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Festival Detail Modal ────────────────────────────────────────────────

function FestivalDetailModal({ slug, onClose }: { slug: string; onClose: () => void }) {
  // 3 parallel queries: full festival meta + summary stats + tour list
  const { data: festival, isLoading: festLoading, error: festError } = useQuery({
    queryKey: ["festival-detail", slug],
    queryFn: () => getFestival(slug),
    enabled: !!slug,
  });
  const { data: summary, isLoading: sumLoading } = useQuery({
    queryKey: ["festival-summary", slug],
    queryFn: () => getFestivalSummary(slug),
    enabled: !!slug,
  });
  const { data: tours, isLoading: toursLoading } = useQuery({
    queryKey: ["festival-tours", slug],
    queryFn: () => listFestivalTours(slug),
    enabled: !!slug,
  });

  const cat = festival?.category;
  const catMeta = cat ? CATEGORY_META[cat] : null;
  const daysAway = festival ? daysUntil(festival.date_start) : null;
  const isLoading = festLoading || sumLoading || toursLoading;

  // Tần suất estimate: cùng category + cùng location_text trong DB → đếm lần xuất hiện qua năm
  // (simple heuristic: lễ âm lịch = hằng năm; lễ có "thường niên"/"hằng năm" trong tên = annual)
  const recurrenceHint = useMemo(() => {
    if (!festival) return null;
    if (festival.is_lunar) return "Lễ âm lịch — diễn ra hằng năm theo lịch âm";
    const nameLower = festival.name_vi.toLowerCase();
    if (/(hằng năm|thường niên|lần thứ|kỳ \d+|năm \d{4})/.test(nameLower)) {
      return "Sự kiện thường niên — lặp lại hằng năm";
    }
    return "Sự kiện diễn ra theo lịch tổ chức cụ thể (xem nguồn để biết tần suất chính xác)";
  }, [festival]);

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl w-full max-w-5xl max-h-[92vh] overflow-hidden flex flex-col shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        {/* Hero header with optional image */}
        {festival?.image_url ? (
          <div className="relative h-32 sm:h-40 bg-gradient-to-r from-primary-500 to-primary-700 shrink-0">
            <img src={festival.image_url} alt={festival.name_vi}
              className="w-full h-full object-cover opacity-90"
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
            <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
            <button type="button" onClick={onClose}
              className="absolute top-2 right-2 bg-black/40 hover:bg-black/60 text-white rounded-full p-1.5">
              <X size={18} />
            </button>
            <div className="absolute bottom-2 left-4 right-4 text-white">
              <h2 className="text-lg sm:text-xl font-bold drop-shadow truncate">
                {festival.name_vi}
              </h2>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-between p-4 border-b shrink-0 bg-gradient-to-r from-primary-50 to-white">
            <h2 className="text-lg font-bold text-gray-900 truncate pr-2">
              {festival?.name_vi ?? summary?.name ?? "Lễ hội"}
            </h2>
            <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700 shrink-0">
              <X size={20} />
            </button>
          </div>
        )}

        <div className="overflow-auto flex-1">
          {isLoading && <div className="p-8"><Loading /></div>}
          {festError && <div className="p-4"><ErrorBox msg={`Không tải được lễ hội: ${(festError as Error).message}`} /></div>}

          {festival && (
            <div className="p-4 space-y-4">
              {/* Metadata badges row */}
              <div className="flex flex-wrap gap-2 items-center">
                <span className={cn("text-xs px-2 py-1 rounded border font-medium", REGION_COLOR[festival.region])}>
                  {regionDisplay(festival.region, festival.location_text)}
                </span>
                {catMeta && (
                  <span className="text-xs px-2 py-1 rounded bg-gray-100 text-gray-700 border flex items-center gap-1">
                    <catMeta.Icon size={11} /> {catMeta.label}
                  </span>
                )}
                {festival.is_lunar && (
                  <span className="text-xs px-2 py-1 rounded bg-purple-100 text-purple-800 border border-purple-200 flex items-center gap-1">
                    <Moon size={11} /> Âm lịch
                  </span>
                )}
                {daysAway !== null && daysAway >= 0 && daysAway <= 365 && (
                  <span className={cn(
                    "text-xs px-2 py-1 rounded border font-semibold",
                    daysAway <= 7 ? "bg-red-100 text-red-800 border-red-200" :
                    daysAway <= 30 ? "bg-amber-100 text-amber-800 border-amber-200" :
                    "bg-emerald-50 text-emerald-700 border-emerald-200"
                  )}>
                    {daysAway === 0 ? "Hôm nay" : `Còn ${daysAway} ngày`}
                  </span>
                )}
                {daysAway !== null && daysAway < 0 && (
                  <span className="text-xs px-2 py-1 rounded bg-gray-100 text-gray-500 border">
                    Đã diễn ra {Math.abs(daysAway)}d trước
                  </span>
                )}
              </div>

              {/* Key info grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                <div className="rounded-lg border bg-gray-50/50 p-3">
                  <p className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Thời gian</p>
                  <p className="font-semibold text-gray-900 flex items-center gap-1.5">
                    <Calendar size={14} className="text-primary-600" />
                    {formatDateRange(festival.date_start, festival.date_end)}
                  </p>
                </div>
                <div className="rounded-lg border bg-gray-50/50 p-3">
                  <p className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Địa điểm</p>
                  <p className="font-semibold text-gray-900">
                    {festival.location_text || <span className="text-gray-400 italic">Chưa rõ</span>}
                  </p>
                </div>
                <div className="rounded-lg border bg-gray-50/50 p-3 sm:col-span-2">
                  <p className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Tần suất</p>
                  <p className="text-sm text-gray-800">{recurrenceHint}</p>
                </div>
              </div>

              {/* Description */}
              {festival.description && (
                <div className="rounded-lg border bg-white p-3">
                  <p className="text-[10px] uppercase tracking-wide text-gray-500 mb-1.5">Mô tả</p>
                  <p className="text-sm text-gray-700 whitespace-pre-line line-clamp-6">
                    {festival.description}
                  </p>
                </div>
              )}

              {/* Source link */}
              {festival.source_url && (
                <a href={festival.source_url} target="_blank" rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-primary-600 hover:underline">
                  <ExternalLink size={12} /> Xem nguồn gốc
                </a>
              )}

              {/* Coverage stats */}
              {summary && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-700 mb-2">Phủ tour ở đúng địa điểm lễ</h3>
                  <div className="grid grid-cols-3 gap-3">
                    <StatCard label="Tổng tour gắn" value={summary.total_tours} accent="primary" />
                    <StatCard label="VTR cover" value={summary.vtr_tours} />
                    <StatCard label="Đối thủ" value={summary.competitor_tours} />
                  </div>
                  {summary.avg_price && (
                    <p className="text-xs text-gray-500 mt-2">
                      Giá trung bình tour cùng location: <strong className="text-gray-800">{fmtVND(summary.avg_price)}</strong>
                    </p>
                  )}
                </div>
              )}

              {/* Tour table */}
              {tours && tours.length > 0 ? (
                <div>
                  <h3 className="text-sm font-semibold text-gray-700 mb-2">Tour gắn lễ ({tours.length})</h3>
                  <div className="overflow-x-auto -mx-4 px-4 border rounded-lg">
                    <table className="w-full text-xs min-w-[800px]">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-2 py-1.5 text-left whitespace-nowrap">Công ty</th>
                          <th className="px-2 py-1.5 text-left">Tên tour</th>
                          <th className="px-2 py-1.5 text-right whitespace-nowrap">Giá</th>
                          <th className="px-2 py-1.5 text-right whitespace-nowrap">Ngày</th>
                          <th className="px-2 py-1.5 text-right whitespace-nowrap">Cách lễ</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tours.map((t: FestivalTourLite) => (
                          <tr key={t.id} className="border-t hover:bg-gray-50">
                            <td className="px-2 py-1.5 whitespace-nowrap">
                              <span className={cn(
                                "px-1 py-0.5 rounded text-[10px] font-medium",
                                t.cong_ty.toLowerCase().includes("vietravel") ? "bg-primary-100 text-primary-800" : "bg-gray-100 text-gray-700",
                              )}>
                                {t.cong_ty}
                              </span>
                            </td>
                            <td className="px-2 py-1.5 max-w-[400px] truncate" title={t.ten_tour}>
                              {t.ten_tour}
                            </td>
                            <td className="px-2 py-1.5 text-right font-mono whitespace-nowrap">{fmtVND(t.gia)}</td>
                            <td className="px-2 py-1.5 text-right text-gray-500 whitespace-nowrap">{t.so_ngay ? `${t.so_ngay}N` : "—"}</td>
                            <td className="px-2 py-1.5 text-right text-gray-600 whitespace-nowrap">
                              {t.festival_distance_days === 0 ? "Trùng" :
                                t.festival_distance_days === null ? "—" :
                                t.festival_distance_days > 0 ? `${t.festival_distance_days}d trước` :
                                `${-t.festival_distance_days}d sau`}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div className="rounded-lg border bg-amber-50 border-amber-200 p-4 text-center">
                  <p className="text-sm text-amber-900 font-medium mb-1">Chưa có tour nào gắn lễ này</p>
                  <p className="text-xs text-amber-700">
                    Vào <strong>Quy tắc phân loại → Quy tắc Lễ hội</strong> để map lễ này với thị trường/tuyến tour cụ thể,
                    sau đó bấm <strong>Re-tag tour</strong>.
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Shared atoms ──────────────────────────────────────────────────────────

function StatCard({ label, value, accent, isText, onClick, active }: {
  label: string;
  value: number | string;
  accent?: "primary";
  isText?: boolean;
  onClick?: () => void;
  active?: boolean;
}) {
  const isClickable = !!onClick;
  const Tag = isClickable ? "button" : "div";
  return (
    <Tag
      type={isClickable ? "button" : undefined}
      onClick={onClick}
      className={cn(
        "card p-4 text-left w-full transition-all",
        accent === "primary" && "border-primary-200 bg-primary-50/40",
        active && "ring-2 ring-primary-500",
        isClickable && "hover:shadow-md cursor-pointer",
      )}
    >
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={cn(
        "font-bold tracking-tight",
        isText ? "text-base" : "text-2xl",
        accent === "primary" && "text-primary-700",
      )}>{value}</p>
    </Tag>
  );
}

function ViewButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className={cn(
      "px-3 py-1.5 rounded text-xs font-medium flex items-center gap-1.5 transition-colors",
      active ? "bg-white text-gray-900 shadow-sm" : "text-gray-600 hover:text-gray-900",
    )}>
      {children}
    </button>
  );
}

function FilterSelect({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div>
      <label className="text-xs text-gray-500 block mb-0.5">{label}</label>
      <select className="input text-sm" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

function Loading() {
  return (
    <div className="card p-12 text-center text-gray-400">
      <Loader2 size={32} className="animate-spin mx-auto mb-3" /> Đang tải…
    </div>
  );
}
function ErrorBox({ msg }: { msg: string }) {
  return <div className="card p-6 text-red-600 text-sm">Lỗi: {msg}</div>;
}
function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="card p-12 text-center text-gray-500 text-sm space-y-2">
      <Calendar size={40} className="mx-auto text-gray-300" />
      <p>{children}</p>
    </div>
  );
}
