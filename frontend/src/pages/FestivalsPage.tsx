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
import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listFestivals, getFestivalStats, refreshFestivals,
  listFestivalTours, getFestivalSummary, getCoverageGap, retagFestivals,
  getPricingPremium, getDemandForecast, getMarketingCalendar,
  getRegionHeatmap, getLunarPlanner, lunarSeed,
  Festival, FestivalRegion, FestivalCategory, FestivalFilters,
  FestivalTourLite, CoverageGapItem,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Calendar, List, MapPin, RefreshCw, Loader2, ExternalLink,
  Music, Utensils, Trophy, Sparkles, Building, ChevronLeft, ChevronRight,
  X, AlertTriangle, TrendingUp, TrendingDown, Megaphone, Map as MapIcon, Moon,
  LucideIcon,
} from "lucide-react";

const REGION_LABEL: Record<FestivalRegion, string> = {
  bac: "Bắc", trung: "Trung", nam: "Nam", "": "Chưa rõ",
};
const REGION_COLOR: Record<FestivalRegion, string> = {
  bac: "bg-blue-100 text-blue-800 border-blue-200",
  trung: "bg-amber-100 text-amber-800 border-amber-200",
  nam: "bg-emerald-100 text-emerald-800 border-emerald-200",
  "": "bg-gray-100 text-gray-700 border-gray-200",
};
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

type TabKey = "timeline" | "coverage" | "premium" | "forecast" | "marketing" | "heatmap" | "lunar";
const TABS: { key: TabKey; label: string; Icon: LucideIcon }[] = [
  { key: "timeline",  label: "Lịch & Timeline",   Icon: Calendar },
  { key: "coverage",  label: "Coverage Gap",       Icon: AlertTriangle },
  { key: "premium",   label: "Pricing Premium",    Icon: TrendingUp },
  { key: "forecast",  label: "Demand Forecast",    Icon: TrendingDown },
  { key: "marketing", label: "Marketing",          Icon: Megaphone },
  { key: "heatmap",   label: "Heatmap Vùng",       Icon: MapIcon },
  { key: "lunar",     label: "Lễ Âm Lịch",         Icon: Moon },
];

export default function FestivalsPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<TabKey>("timeline");
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
            <a className="text-primary-600 hover:underline" href="https://vietnam.travel/event" target="_blank" rel="noreferrer">vietnam.travel/event</a> + lễ âm lịch.
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

      {/* Tabs */}
      <div className="border-b border-gray-200 overflow-x-auto">
        <div className="flex gap-1 min-w-max">
          {TABS.map((t) => (
            <button key={t.key} type="button" onClick={() => setTab(t.key)}
              className={cn(
                "px-3 py-2 text-sm font-medium border-b-2 transition-colors flex items-center gap-1.5 whitespace-nowrap",
                tab === t.key ? "border-primary-600 text-primary-700" : "border-transparent text-gray-600 hover:text-gray-900"
              )}>
              <t.Icon size={14} /> {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab body */}
      <div>
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

// ── Tab 1: Timeline ──────────────────────────────────────────────────────

function TimelineTab({ onPickFestival }: { onPickFestival: (slug: string) => void }) {
  const [view, setView] = useState<"timeline" | "calendar">("timeline");
  const [filters, setFilters] = useState<FestivalFilters>({});
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

  return (
    <div className="space-y-4">
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Tổng số sự kiện" value={stats.total} />
          <StatCard label="Sắp diễn ra (30 ngày)" value={stats.upcoming_30d} accent="primary" />
          <StatCard label="Sắp diễn ra (90 ngày)" value={stats.upcoming_90d} />
          <StatCard label="Vùng nhiều lễ nhất" isText value={
            (() => {
              const top = Object.entries(stats.by_region).sort((a, b) => b[1] - a[1])[0]?.[0];
              return top === "bac" ? "Miền Bắc" : top === "trung" ? "Miền Trung" : top === "nam" ? "Miền Nam" : "—";
            })()
          } />
        </div>
      )}
      <div className="card p-4 flex flex-wrap gap-3 items-end">
        <FilterSelect label="Vùng" value={filters.region ?? ""}
          onChange={(v) => setFilters((f) => ({ ...f, region: (v || undefined) as FestivalRegion | undefined }))}
          options={[
            { value: "", label: "Tất cả vùng" }, { value: "bac", label: "Miền Bắc" },
            { value: "trung", label: "Miền Trung" }, { value: "nam", label: "Miền Nam" },
          ]} />
        <FilterSelect label="Loại lễ" value={filters.category ?? ""}
          onChange={(v) => setFilters((f) => ({ ...f, category: (v || undefined) as FestivalCategory | undefined }))}
          options={[
            { value: "", label: "Tất cả loại" }, { value: "cultural", label: "Văn hóa" },
            { value: "religious", label: "Tâm linh" }, { value: "music", label: "Âm nhạc" },
            { value: "food", label: "Ẩm thực" }, { value: "sport", label: "Thể thao" },
            { value: "other", label: "Khác" },
          ]} />
        <div className="ml-auto flex gap-1 bg-gray-100 p-1 rounded-md">
          <ViewButton active={view === "timeline"} onClick={() => setView("timeline")}>
            <List size={14} /> Timeline
          </ViewButton>
          <ViewButton active={view === "calendar"} onClick={() => setView("calendar")}>
            <Calendar size={14} /> Calendar
          </ViewButton>
        </div>
      </div>

      {isLoading && (
        <div className="card p-12 text-center text-gray-400">
          <Loader2 size={32} className="animate-spin mx-auto mb-3" /> Đang tải lễ hội…
        </div>
      )}
      {error && <div className="card p-6 text-red-600 text-sm">Lỗi tải: {(error as Error).message}</div>}
      {!isLoading && festivals && festivals.length === 0 && (
        <div className="card p-12 text-center text-gray-400 space-y-3">
          <Calendar size={40} className="mx-auto" />
          <p className="text-sm">Chưa có dữ liệu lễ hội.</p>
          <p className="text-xs">Bấm <strong>Refresh scrape</strong> để crawl, hoặc <strong>Seed lễ âm</strong> để có Tết/Trung Thu.</p>
        </div>
      )}
      {!isLoading && festivals && festivals.length > 0 && view === "timeline" && (
        <TimelineView festivals={festivals} onPick={onPickFestival} />
      )}
      {!isLoading && festivals && festivals.length > 0 && view === "calendar" && (
        <CalendarView festivals={festivals} month={calendarMonth} onPick={onPickFestival}
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
                  Miền {REGION_LABEL[f.region]}
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

// ── Tab 2: Coverage Gap ──────────────────────────────────────────────────

function CoverageGapTab({ onPickFestival }: { onPickFestival: (slug: string) => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["festival-coverage-gap"],
    queryFn: () => getCoverageGap(30),
    staleTime: 60 * 60 * 1000,
  });
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox msg={(error as Error).message} />;
  if (!data || data.length === 0) return (
    <EmptyState>
      Chưa có dữ liệu. Bấm <strong>Re-tag tour</strong> để map tour với lễ hội trước.
    </EmptyState>
  );
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 sticky top-0">
          <tr>
            <th className="px-3 py-2 text-left">Lễ hội</th>
            <th className="px-3 py-2 text-left">Ngày</th>
            <th className="px-3 py-2 text-left">Vùng</th>
            <th className="px-3 py-2 text-right">VTR</th>
            <th className="px-3 py-2 text-right">Đối thủ</th>
            <th className="px-3 py-2 text-left">Top đối thủ</th>
            <th className="px-3 py-2 text-right">Gap</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row: CoverageGapItem) => (
            <tr key={row.slug} className="border-t hover:bg-gray-50">
              <td className="px-3 py-2">
                <button type="button" className="text-primary-600 hover:underline text-left" onClick={() => onPickFestival(row.slug)}>
                  {row.name}
                </button>
              </td>
              <td className="px-3 py-2 text-xs text-gray-600">{formatDateRange(row.date_start, row.date_end)}</td>
              <td className="px-3 py-2">
                {row.region && (
                  <span className={cn("text-[10px] px-1.5 py-0.5 rounded border", REGION_COLOR[row.region as FestivalRegion])}>
                    {REGION_LABEL[row.region as FestivalRegion]}
                  </span>
                )}
              </td>
              <td className={cn("px-3 py-2 text-right font-mono", row.vtr_tours === 0 && "text-red-600 font-bold")}>
                {row.vtr_tours}
              </td>
              <td className="px-3 py-2 text-right font-mono">{row.competitor_tours}</td>
              <td className="px-3 py-2 text-xs text-gray-700">
                {Object.entries(row.top_competitors).slice(0, 3).map(([co, cnt]) => (
                  <span key={co} className="inline-block mr-2">
                    {co}: <strong>{cnt}</strong>
                  </span>
                ))}
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
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Tab 3: Pricing Premium ───────────────────────────────────────────────

function PricingPremiumTab() {
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
      <p className="text-xs text-gray-600">
        Forecast 6 tháng tới — số lễ + recommendation inventory + tour hiện đã gắn.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {data.forecast.map((m) => (
          <div key={m.month_label} className={cn(
            "card p-4 border-l-4",
            m.inventory_recommendation === "high" ? "border-red-500" :
            m.inventory_recommendation === "medium" ? "border-amber-500" : "border-gray-300",
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
                {m.top_festivals.slice(0, 3).map((f) => (
                  <p key={f.slug} className="text-[11px] text-gray-700 truncate" title={f.name}>
                    • {f.name}
                  </p>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
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
                    Miền {REGION_LABEL[item.region as FestivalRegion]}
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
  const { data, isLoading, error } = useQuery({
    queryKey: ["festival-heatmap"],
    queryFn: getRegionHeatmap,
    staleTime: 60 * 60 * 1000,
  });
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox msg={(error as Error).message} />;
  if (!data) return null;
  const max = Math.max(...data.regions.map((r) => Math.max(r.festival_count, r.tour_with_festival)), 1);
  return (
    <div className="space-y-4">
      <div className="card p-4">
        <p className="text-xs text-gray-600 mb-3">
          Mật độ lễ × mật độ tour theo vùng. Vùng under-served = có lễ nhưng ít tour cover.
        </p>
        <div className="space-y-3">
          {data.regions.map((r) => (
            <div key={r.region} className={cn(
              "rounded-lg border p-3",
              r.is_under_served && "border-amber-300 bg-amber-50",
            )}>
              <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
                <h3 className="font-bold text-gray-900">Miền {r.region_label}</h3>
                {r.is_under_served && (
                  <span className="badge bg-amber-200 text-amber-900 text-[10px]">
                    <AlertTriangle size={10} /> Under-served — cơ hội mở tour
                  </span>
                )}
              </div>
              <div className="grid grid-cols-3 gap-3 text-xs">
                <BarStat label="Số lễ" value={r.festival_count} max={max} color="bg-primary-500" />
                <BarStat label="Tour gắn lễ" value={r.tour_with_festival} max={max} color="bg-emerald-500" />
                <div className="text-center">
                  <p className="font-bold text-2xl text-gray-900">{r.festival_coverage_ratio.toFixed(2)}</p>
                  <p className="text-gray-500 text-[10px]">Tỉ lệ tour/lễ</p>
                </div>
              </div>
            </div>
          ))}
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
  const { data: summary, isLoading } = useQuery({
    queryKey: ["festival-summary", slug],
    queryFn: () => getFestivalSummary(slug),
    enabled: !!slug,
  });
  const { data: tours } = useQuery({
    queryKey: ["festival-tours", slug],
    queryFn: () => listFestivalTours(slug),
    enabled: !!slug,
  });

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl max-w-3xl w-full max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-lg font-bold text-gray-900">{summary?.name ?? "Lễ hội"}</h2>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700">
            <X size={20} />
          </button>
        </div>
        <div className="overflow-auto p-4 space-y-4">
          {isLoading && <Loading />}
          {summary && (
            <div className="grid grid-cols-3 gap-3">
              <StatCard label="Tour gắn" value={summary.total_tours} accent="primary" />
              <StatCard label="VTR cover" value={summary.vtr_tours} />
              <StatCard label="Đối thủ" value={summary.competitor_tours} />
            </div>
          )}
          {tours && tours.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">Tour gắn lễ ({tours.length})</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-2 py-1.5 text-left">Công ty</th>
                      <th className="px-2 py-1.5 text-left">Tên tour</th>
                      <th className="px-2 py-1.5 text-right">Giá</th>
                      <th className="px-2 py-1.5 text-right">Ngày</th>
                      <th className="px-2 py-1.5 text-right">Cách lễ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tours.map((t: FestivalTourLite) => (
                      <tr key={t.id} className="border-t hover:bg-gray-50">
                        <td className="px-2 py-1.5">
                          <span className={cn(
                            "px-1 py-0.5 rounded text-[10px] font-medium",
                            t.cong_ty.toLowerCase().includes("vietravel") ? "bg-primary-100 text-primary-800" : "bg-gray-100 text-gray-700",
                          )}>
                            {t.cong_ty}
                          </span>
                        </td>
                        <td className="px-2 py-1.5 max-w-[300px] truncate" title={t.ten_tour}>
                          {t.ten_tour}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono">{fmtVND(t.gia)}</td>
                        <td className="px-2 py-1.5 text-right text-gray-500">{t.so_ngay ? `${t.so_ngay}N` : "—"}</td>
                        <td className="px-2 py-1.5 text-right text-gray-600">
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
          )}
          {tours && tours.length === 0 && (
            <p className="text-center text-gray-500 text-sm py-8">Chưa có tour nào gắn lễ này.</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Shared atoms ──────────────────────────────────────────────────────────

function StatCard({ label, value, accent, isText }: { label: string; value: number | string; accent?: "primary"; isText?: boolean }) {
  return (
    <div className={cn("card p-4", accent === "primary" && "border-primary-200 bg-primary-50/40")}>
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={cn(
        "font-bold tracking-tight",
        isText ? "text-base" : "text-2xl",
        accent === "primary" && "text-primary-700",
      )}>{value}</p>
    </div>
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
