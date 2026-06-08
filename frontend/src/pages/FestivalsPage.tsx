/**
 * Sự kiện & Lễ hội — Phase 1
 *
 * Vertical Timeline + Calendar Grid dual-view toggle.
 * Filter: tháng × vùng miền × loại lễ.
 * Data từ vietnam.travel/event (weekly cron + manual refresh button cho admin).
 */
import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listFestivals, getFestivalStats, refreshFestivals,
  Festival, FestivalRegion, FestivalCategory, FestivalFilters,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Calendar, List, MapPin, RefreshCw, Loader2, ExternalLink,
  Music, Utensils, Trophy, Sparkles, Building, ChevronLeft, ChevronRight,
  LucideIcon,
} from "lucide-react";

const REGION_LABEL: Record<FestivalRegion, string> = {
  bac: "Bắc",
  trung: "Trung",
  nam: "Nam",
  "": "Chưa rõ",
};

const REGION_COLOR: Record<FestivalRegion, string> = {
  bac: "bg-blue-100 text-blue-800 border-blue-200",
  trung: "bg-amber-100 text-amber-800 border-amber-200",
  nam: "bg-emerald-100 text-emerald-800 border-emerald-200",
  "": "bg-gray-100 text-gray-700 border-gray-200",
};

const CATEGORY_META: Record<FestivalCategory, { label: string; Icon: LucideIcon }> = {
  cultural:  { label: "Văn hóa",     Icon: Sparkles },
  religious: { label: "Tâm linh",   Icon: Building },
  music:     { label: "Âm nhạc",    Icon: Music },
  food:      { label: "Ẩm thực",    Icon: Utensils },
  sport:     { label: "Thể thao",   Icon: Trophy },
  other:     { label: "Khác",        Icon: Sparkles },
};

function formatDateRange(start: string, end: string): string {
  const s = new Date(start);
  const e = new Date(end);
  const fmt = (d: Date) => d.toLocaleDateString("vi-VN", { day: "2-digit", month: "short" });
  if (start === end) return `${fmt(s)}, ${s.getFullYear()}`;
  if (s.getMonth() === e.getMonth() && s.getFullYear() === e.getFullYear()) {
    return `${s.getDate()} – ${fmt(e)}, ${e.getFullYear()}`;
  }
  return `${fmt(s)} – ${fmt(e)}, ${e.getFullYear()}`;
}

function daysUntil(dateStr: string): number {
  const d = new Date(dateStr);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.ceil((d.getTime() - today.getTime()) / 86400000);
}

export default function FestivalsPage() {
  const qc = useQueryClient();
  const [view, setView] = useState<"timeline" | "calendar">("timeline");
  const [filters, setFilters] = useState<FestivalFilters>({});
  const [calendarMonth, setCalendarMonth] = useState<Date>(() => {
    const d = new Date();
    d.setDate(1);
    return d;
  });

  const { data: festivals, isLoading, error } = useQuery({
    queryKey: ["festivals", filters],
    queryFn: () => listFestivals(filters),
    staleTime: 6 * 60 * 60 * 1000, // 6h
  });

  const { data: stats } = useQuery({
    queryKey: ["festival-stats"],
    queryFn: getFestivalStats,
    staleTime: 6 * 60 * 60 * 1000,
  });

  const refresh = useMutation({
    mutationFn: refreshFestivals,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["festivals"] });
      qc.invalidateQueries({ queryKey: ["festival-stats"] });
    },
  });

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Sự kiện & Lễ hội Việt Nam</h1>
          <p className="text-sm text-gray-500 mt-1">
            Lịch lễ hội VN — dữ liệu từ <a className="text-primary-600 hover:underline" href="https://vietnam.travel/event" target="_blank" rel="noreferrer">vietnam.travel/event</a> (cập nhật hàng tuần).
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary text-xs"
          disabled={refresh.isPending}
          onClick={() => refresh.mutate()}
          title="Crawl lại từ vietnam.travel (admin only)"
        >
          {refresh.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          {refresh.isPending ? "Đang quét..." : "Refresh"}
        </button>
      </div>

      {/* Stats bar */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Tổng số sự kiện" value={stats.total} />
          <StatCard label="Sắp diễn ra (30 ngày)" value={stats.upcoming_30d} accent="primary" />
          <StatCard label="Sắp diễn ra (90 ngày)" value={stats.upcoming_90d} />
          <StatCard label="Vùng nhiều lễ nhất" value={
            Object.entries(stats.by_region).sort((a, b) => b[1] - a[1])[0]?.[0] === "bac"
              ? "Miền Bắc"
              : Object.entries(stats.by_region).sort((a, b) => b[1] - a[1])[0]?.[0] === "trung"
              ? "Miền Trung"
              : Object.entries(stats.by_region).sort((a, b) => b[1] - a[1])[0]?.[0] === "nam"
              ? "Miền Nam" : "—"
          } isText />
        </div>
      )}

      {/* Filter + View toggle */}
      <div className="card p-4 flex flex-wrap gap-3 items-end">
        <FilterSelect
          label="Vùng"
          value={filters.region ?? ""}
          onChange={(v) => setFilters((f) => ({ ...f, region: (v || undefined) as FestivalRegion | undefined }))}
          options={[
            { value: "", label: "Tất cả vùng" },
            { value: "bac", label: "Miền Bắc" },
            { value: "trung", label: "Miền Trung" },
            { value: "nam", label: "Miền Nam" },
          ]}
        />
        <FilterSelect
          label="Loại lễ"
          value={filters.category ?? ""}
          onChange={(v) => setFilters((f) => ({ ...f, category: (v || undefined) as FestivalCategory | undefined }))}
          options={[
            { value: "", label: "Tất cả loại" },
            { value: "cultural", label: "Văn hóa" },
            { value: "religious", label: "Tâm linh" },
            { value: "music", label: "Âm nhạc" },
            { value: "food", label: "Ẩm thực" },
            { value: "sport", label: "Thể thao" },
            { value: "other", label: "Khác" },
          ]}
        />
        <div className="ml-auto flex gap-1 bg-gray-100 p-1 rounded-md">
          <ViewButton active={view === "timeline"} onClick={() => setView("timeline")}>
            <List size={14} /> Timeline
          </ViewButton>
          <ViewButton active={view === "calendar"} onClick={() => setView("calendar")}>
            <Calendar size={14} /> Calendar
          </ViewButton>
        </div>
      </div>

      {/* Body */}
      {isLoading && (
        <div className="card p-12 text-center text-gray-400">
          <Loader2 size={32} className="animate-spin mx-auto mb-3" /> Đang tải lễ hội…
        </div>
      )}
      {error && (
        <div className="card p-6 text-red-600 text-sm">
          Lỗi tải: {(error as Error).message}
        </div>
      )}
      {!isLoading && festivals && festivals.length === 0 && (
        <div className="card p-12 text-center text-gray-400 space-y-3">
          <Calendar size={40} className="mx-auto" />
          <p className="text-sm">Chưa có dữ liệu lễ hội.</p>
          <p className="text-xs">Bấm <strong>Refresh</strong> để crawl từ vietnam.travel/event (admin only).</p>
        </div>
      )}
      {!isLoading && festivals && festivals.length > 0 && view === "timeline" && (
        <TimelineView festivals={festivals} />
      )}
      {!isLoading && festivals && festivals.length > 0 && view === "calendar" && (
        <CalendarView
          festivals={festivals}
          month={calendarMonth}
          onPrev={() => setCalendarMonth((d) => new Date(d.getFullYear(), d.getMonth() - 1, 1))}
          onNext={() => setCalendarMonth((d) => new Date(d.getFullYear(), d.getMonth() + 1, 1))}
        />
      )}
    </div>
  );
}

function StatCard({ label, value, accent, isText }: {
  label: string;
  value: number | string;
  accent?: "primary";
  isText?: boolean;
}) {
  return (
    <div className={cn(
      "card p-4",
      accent === "primary" && "border-primary-200 bg-primary-50/40",
    )}>
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
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "px-3 py-1.5 rounded text-xs font-medium flex items-center gap-1.5 transition-colors",
        active ? "bg-white text-gray-900 shadow-sm" : "text-gray-600 hover:text-gray-900",
      )}
    >
      {children}
    </button>
  );
}

function FilterSelect({ label, value, onChange, options }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div>
      <label className="text-xs text-gray-500 block mb-0.5">{label}</label>
      <select
        className="input text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}

function TimelineView({ festivals }: { festivals: Festival[] }) {
  // Group theo tháng
  const groups = useMemo(() => {
    const byMonth = new Map<string, Festival[]>();
    for (const f of festivals) {
      const k = f.date_start.slice(0, 7); // "2026-06"
      if (!byMonth.has(k)) byMonth.set(k, []);
      byMonth.get(k)!.push(f);
    }
    return Array.from(byMonth.entries()).sort((a, b) => a[0].localeCompare(b[0]));
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
            {items.map((f) => <TimelineCard key={f.id} festival={f} />)}
          </div>
        </div>
      ))}
    </div>
  );
}

function TimelineCard({ festival: f }: { festival: Festival }) {
  const { Icon, label: catLabel } = CATEGORY_META[f.category] ?? CATEGORY_META.other;
  const days = daysUntil(f.date_start);
  return (
    <div className="relative">
      {/* Dot trên timeline */}
      <div className="absolute -left-[27px] top-3 w-3 h-3 rounded-full bg-primary-500 ring-4 ring-white" />
      <div className="card p-4 hover:shadow-md transition-shadow">
        <div className="flex gap-4">
          {f.image_url && (
            <div className="hidden sm:block shrink-0">
              <img
                src={f.image_url}
                alt={f.name_vi}
                className="w-24 h-24 rounded-lg object-cover bg-gray-100"
                loading="lazy"
              />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2 mb-1">
              <h3 className="font-semibold text-gray-900 leading-tight">{f.name_vi}</h3>
              {days >= 0 && days <= 30 && (
                <span className="badge bg-primary-100 text-primary-800 text-[10px] shrink-0">
                  Còn {days} ngày
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500 mb-2 flex items-center gap-1">
              <Calendar size={12} /> {formatDateRange(f.date_start, f.date_end)}
              {f.location_text && (
                <>
                  <span className="mx-1">·</span>
                  <MapPin size={12} /> {f.location_text}
                </>
              )}
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
            </div>
            {f.description && (
              <p className="text-xs text-gray-600 line-clamp-2">{f.description}</p>
            )}
            {f.source_url && (
              <a
                href={f.source_url}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-primary-600 hover:underline inline-flex items-center gap-1 mt-2"
              >
                Xem chi tiết <ExternalLink size={10} />
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function CalendarView({ festivals, month, onPrev, onNext }: {
  festivals: Festival[];
  month: Date;
  onPrev: () => void;
  onNext: () => void;
}) {
  // Map theo ngày YYYY-MM-DD
  const eventsByDay = useMemo(() => {
    const m = new Map<string, Festival[]>();
    for (const f of festivals) {
      const start = new Date(f.date_start);
      const end = new Date(f.date_end);
      for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        const k = d.toISOString().slice(0, 10);
        if (!m.has(k)) m.set(k, []);
        m.get(k)!.push(f);
      }
    }
    return m;
  }, [festivals]);

  // Build grid days
  const days = useMemo(() => {
    const firstDow = new Date(month.getFullYear(), month.getMonth(), 1).getDay(); // 0=Sun
    const daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    const cells: (Date | null)[] = [];
    // Pad start (calendar weeks start Mon = treat Sun as 7, Mon=1)
    const padStart = firstDow === 0 ? 6 : firstDow - 1;
    for (let i = 0; i < padStart; i++) cells.push(null);
    for (let d = 1; d <= daysInMonth; d++) {
      cells.push(new Date(month.getFullYear(), month.getMonth(), d));
    }
    while (cells.length % 7) cells.push(null);
    return cells;
  }, [month]);

  return (
    <div className="card overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b">
        <button type="button" className="btn-secondary text-xs" onClick={onPrev}>
          <ChevronLeft size={14} />
        </button>
        <h2 className="font-semibold text-gray-900">
          {month.toLocaleDateString("vi-VN", { month: "long", year: "numeric" })}
        </h2>
        <button type="button" className="btn-secondary text-xs" onClick={onNext}>
          <ChevronRight size={14} />
        </button>
      </div>
      {/* Weekday header */}
      <div className="grid grid-cols-7 bg-gray-50 border-b text-xs font-medium text-gray-600">
        {["T2", "T3", "T4", "T5", "T6", "T7", "CN"].map((d) => (
          <div key={d} className="py-2 px-2 text-center">{d}</div>
        ))}
      </div>
      {/* Days */}
      <div className="grid grid-cols-7">
        {days.map((d, i) => {
          if (!d) return <div key={i} className="aspect-square border-r border-b bg-gray-50/30" />;
          const k = d.toISOString().slice(0, 10);
          const evts = eventsByDay.get(k) ?? [];
          const isToday = d.toDateString() === new Date().toDateString();
          return (
            <div key={i} className={cn(
              "min-h-[80px] border-r border-b p-1.5 text-xs",
              isToday && "bg-primary-50",
            )}>
              <p className={cn(
                "text-[10px] mb-1 font-semibold",
                isToday ? "text-primary-700" : "text-gray-500",
              )}>
                {d.getDate()}
              </p>
              <div className="space-y-1">
                {evts.slice(0, 3).map((f) => (
                  <div
                    key={f.id}
                    className={cn(
                      "text-[10px] px-1.5 py-0.5 rounded truncate border",
                      REGION_COLOR[f.region],
                    )}
                    title={f.name_vi}
                  >
                    {f.name_vi}
                  </div>
                ))}
                {evts.length > 3 && (
                  <p className="text-[10px] text-gray-500">+{evts.length - 3} lễ</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
