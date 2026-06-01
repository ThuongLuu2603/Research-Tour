import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { triggerScrape, getScrapeJobs, getSchedule, updateSchedule, getDataStatus, syncSheetData, ScrapeJob } from "@/lib/api";
import { fmtDate, statusColor, cn } from "@/lib/utils";
import { Play, Clock, CheckCircle, XCircle, Loader2, RefreshCw, Database } from "lucide-react";

interface ProgressEvent { pct: number; msg: string; done: boolean; added?: number; updated?: number; error?: boolean }

function JobStatusBadge({ status }: { status: string }) {
  const icons: Record<string, React.ReactNode> = {
    success: <CheckCircle size={12} />,
    failed: <XCircle size={12} />,
    running: <Loader2 size={12} className="animate-spin" />,
    pending: <Clock size={12} />,
  };
  return (
    <span className={cn("badge flex items-center gap-1", statusColor(status))}>
      {icons[status] ?? null}
      {status}
    </span>
  );
}

function ScraperCard({ scraper, label, desc }: { scraper: "vietravel" | "findtourgo"; label: string; desc: string }) {
  const qc = useQueryClient();
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const trigger = useMutation({
    mutationFn: () => triggerScrape(scraper),
    onSuccess: (job) => {
      setActiveJobId(job.id);
      setProgress({ pct: 0, msg: "Đang khởi động...", done: false });
      const token = localStorage.getItem("access_token");
      const es = new EventSource(`/api/scraper/jobs/${job.id}/stream?token=${token}`);
      esRef.current = es;
      es.onmessage = (e) => {
        try {
          const ev: ProgressEvent = JSON.parse(e.data);
          setProgress(ev);
          if (ev.done) {
            es.close();
            qc.invalidateQueries({ queryKey: ["scrape-jobs"] });
            qc.invalidateQueries({ queryKey: ["kpi"] });
            qc.invalidateQueries({ queryKey: ["tours"] });
          }
        } catch {}
      };
      es.onerror = () => {
        setProgress((p) => p ? { ...p, msg: "Kết nối bị gián đoạn — kiểm tra Job History", done: true } : p);
        es.close();
      };
    },
    onError: (err: any) => {
      setProgress({ pct: 0, msg: err.response?.data?.detail ?? "Lỗi không xác định", done: true, error: true });
    },
  });

  const isRunning = trigger.isPending || (progress && !progress.done);

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-semibold text-gray-900">{label}</h3>
          <p className="text-xs text-gray-500 mt-0.5">{desc}</p>
        </div>
        <button
          onClick={() => trigger.mutate()}
          disabled={!!isRunning}
          className="btn-primary text-xs"
        >
          {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
          {isRunning ? "Đang chạy..." : "Chạy ngay"}
        </button>
      </div>

      {/* Progress */}
      {progress && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className={cn("font-medium", progress.error ? "text-red-600" : progress.done ? "text-green-600" : "text-primary-600")}>
              {progress.msg}
            </span>
            <span className="text-gray-500">{progress.pct}%</span>
          </div>
          <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
            <div
              className={cn("h-full rounded-full transition-all duration-300", progress.error ? "bg-red-500" : progress.done ? "bg-green-500" : "bg-primary-600")}
              style={{ width: `${progress.pct}%` }}
            />
          </div>
          {progress.done && !progress.error && (
            <p className="text-xs text-green-600 font-medium">
              ✓ Thêm {progress.added ?? 0} tour mới · Cập nhật {progress.updated ?? 0} tour
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function addMinutes(h: number, m: number, offset: number) {
  const total = h * 60 + m + offset;
  return { h: Math.floor(total / 60) % 24, m: total % 60 };
}

export default function ScraperHub() {
  const qc = useQueryClient();
  const [schedHour, setSchedHour] = useState(7);
  const [schedMin, setSchedMin] = useState(0);
  const [savedSched, setSavedSched] = useState(false);

  const { data: jobs, refetch: refetchJobs } = useQuery({
    queryKey: ["scrape-jobs"],
    queryFn: getScrapeJobs,
    refetchInterval: 5000,
  });

  const { data: schedule } = useQuery({
    queryKey: ["schedule"],
    queryFn: getSchedule,
  });

  const { data: dataStatus, refetch: refetchDataStatus } = useQuery({
    queryKey: ["data-status"],
    queryFn: getDataStatus,
    refetchInterval: (query) =>
      query.state.data?.import?.running ? 2000 : false,
  });

  const syncData = useMutation({
    mutationFn: syncSheetData,
    onSuccess: () => {
      refetchDataStatus();
    },
  });

  useEffect(() => {
    if (dataStatus?.import?.running) return;
    if (dataStatus?.complete) {
      qc.invalidateQueries({ queryKey: ["kpi"] });
      qc.invalidateQueries({ queryKey: ["tours"] });
      qc.invalidateQueries({ queryKey: ["by-market"] });
      qc.invalidateQueries({ queryKey: ["by-company"] });
      qc.invalidateQueries({ queryKey: ["by-segment"] });
    }
  }, [dataStatus?.import?.running, dataStatus?.complete, qc]);

  useEffect(() => {
    if (schedule) {
      setSchedHour(schedule.hour);
      setSchedMin(schedule.minute);
    }
  }, [schedule]);

  const saveSchedule = async () => {
    await updateSchedule(schedHour, schedMin);
    setSavedSched(true);
    setTimeout(() => setSavedSched(false), 2000);
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Scraper Hub</h1>
          <p className="text-sm text-gray-500">Quản lý thu thập dữ liệu tự động từ Vietravel và FindTourGo</p>
        </div>
        <button onClick={() => refetchJobs()} className="btn-secondary text-xs">
          <RefreshCw size={14} /> Làm mới
        </button>
      </div>

      {/* Data import — no Render Shell needed on free tier */}
      <div className={cn("card p-5 border-2", dataStatus?.complete ? "border-green-200 bg-green-50/40" : "border-amber-300 bg-amber-50/50")}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h3 className="font-semibold text-gray-800 flex items-center gap-2">
              <Database size={18} className="text-primary-600" />
              Dữ liệu thị trường trong hệ thống
            </h3>
            <p className="text-xs text-gray-500 mt-1">
              Tổng: <strong>{(dataStatus?.total ?? 0).toLocaleString("vi-VN")}</strong> tour
              {dataStatus && !dataStatus.complete && (
                <span className="text-amber-700 ml-2">— thiếu dữ liệu tab Main (~8.410 tour). Bấm nút bên phải để import.</span>
              )}
            </p>
            {dataStatus && (
              <div className="flex flex-wrap gap-3 mt-3 text-xs">
                {Object.entries(dataStatus.breakdown).map(([src, n]) => {
                  const ok = n >= (dataStatus.expected_min[src] ?? 1);
                  return (
                    <span key={src} className={cn("badge", ok ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-800")}>
                      {src}: {n.toLocaleString("vi-VN")}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
          <button
            onClick={() => syncData.mutate()}
            disabled={syncData.isPending || dataStatus?.import?.running}
            className="btn-primary text-sm shrink-0"
          >
            {syncData.isPending || dataStatus?.import?.running ? (
              <><Loader2 size={16} className="animate-spin" /> {dataStatus?.import?.message || "Đang import..."}</>
            ) : (
              <><Database size={16} /> Import dữ liệu Sheet</>
            )}
          </button>
        </div>
        {dataStatus?.import?.running && (
          <p className="text-sm text-blue-700 mt-3">
            ⏳ {dataStatus.import.message} — tab Main có ~8.410 tour, cần 2–5 phút. Không tắt trang.
          </p>
        )}
        {dataStatus?.import?.error && (
          <p className="text-sm text-red-600 mt-3">Lỗi import: {dataStatus.import.error}</p>
        )}
        {!dataStatus?.import?.running && dataStatus?.complete && syncData.isSuccess && (
          <p className="text-sm text-green-700 mt-3">
            ✓ Import xong — tổng {dataStatus.total.toLocaleString("vi-VN")} tour. Refresh Dashboard để xem.
          </p>
        )}
        {syncData.isError && !dataStatus?.import?.running && (
          <p className="text-sm text-red-600 mt-3">{(syncData.error as Error)?.message || "Import thất bại."}</p>
        )}
      </div>

      {/* Scraper cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ScraperCard
          scraper="vietravel"
          label="Vietravel — travel.com.vn"
          desc="DB trước → xuất tab Sheet Vietravel"
        />
        <ScraperCard
          scraper="findtourgo"
          label="FindTourGo — OTA Aggregator"
          desc="Chỉ ghi Google Sheet (không lưu database)"
        />
      </div>

      {/* Auto schedule */}
      <div className="card p-5 space-y-4">
        <div>
          <h3 className="font-semibold text-gray-800 mb-1">Lịch tự động</h3>
          <p className="text-xs text-gray-500">
            Tất cả giờ theo <strong>{schedule?.timezone_label ?? "Giờ Việt Nam (UTC+7)"}</strong>
            {schedule?.timezone ? ` — ${schedule.timezone}` : ""}
          </p>
        </div>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-gray-500 border-b">
              <th className="pb-2 font-medium">Tác vụ</th>
              <th className="pb-2 font-medium">Giờ VN</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {(schedule?.jobs ?? [
              { label: "Sync Main → DB", time_vn: "06:30" },
              { label: "Scrape Vietravel → DB → Sheet", time_vn: `${String(schedHour).padStart(2, "0")}:${String(schedMin).padStart(2, "0")}` },
              { label: "Scrape FindTourGo → Sheet", time_vn: (() => { const t = addMinutes(schedHour, schedMin, 20); return `${String(t.h).padStart(2, "0")}:${String(t.m).padStart(2, "0")}`; })() },
              { label: "Snapshot", time_vn: "08:30" },
              { label: "Sync Main + Vietravel → DB", time_vn: "09:00" },
            ]).map((j) => (
              <tr key={j.label}>
                <td className="py-2 text-gray-800">{j.label}</td>
                <td className="py-2 font-mono text-gray-600">{j.time_vn}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="border-t border-gray-100 pt-4">
          <p className="text-xs text-gray-600 mb-2">Chỉnh giờ 2 scraper (Vietravel + FindTourGo +20 phút):</p>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Giờ VN</label>
              <input type="number" min={0} max={23} className="input w-20 text-center text-sm" value={schedHour} onChange={(e) => setSchedHour(Number(e.target.value))} />
            </div>
            <span className="text-gray-400 font-bold mt-4">:</span>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Phút</label>
              <input type="number" min={0} max={59} className="input w-20 text-center text-sm" value={schedMin} onChange={(e) => setSchedMin(Number(e.target.value))} />
            </div>
            <button type="button" onClick={saveSchedule} className={cn("btn-primary text-xs mt-4", savedSched && "bg-green-600 border-green-600")}>
              {savedSched ? "✓ Đã lưu" : "Lưu lịch scraper"}
            </button>
          </div>
        </div>
      </div>

      {/* Job history */}
      <div className="card overflow-auto">
        <div className="px-5 py-3 border-b border-gray-200">
          <h3 className="font-semibold text-gray-800">Job History (30 gần nhất)</h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              {["#", "Scraper", "Trạng thái", "Mới", "Cập nhật", "Tổng", "Bắt đầu", "Kết thúc", "Ghi chú"].map((h) => (
                <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600 whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {(jobs ?? []).map((job: ScrapeJob) => (
              <tr key={job.id} className="hover:bg-blue-50 transition-colors">
                <td className="px-4 py-2.5 text-xs text-gray-400">{job.id}</td>
                <td className="px-4 py-2.5 text-xs font-medium text-gray-700 capitalize">{job.scraper_name}</td>
                <td className="px-4 py-2.5"><JobStatusBadge status={job.status} /></td>
                <td className="px-4 py-2.5 text-xs text-green-600 font-medium">+{job.tours_added}</td>
                <td className="px-4 py-2.5 text-xs text-blue-600 font-medium">~{job.tours_updated}</td>
                <td className="px-4 py-2.5 text-xs text-gray-600">{job.tours_total}</td>
                <td className="px-4 py-2.5 text-xs text-gray-500 whitespace-nowrap">{fmtDate(job.started_at)}</td>
                <td className="px-4 py-2.5 text-xs text-gray-500 whitespace-nowrap">{job.finished_at ? fmtDate(job.finished_at) : <span className="text-blue-500 animate-pulse">Đang chạy</span>}</td>
                <td className="px-4 py-2.5 text-xs text-gray-400 max-w-xs truncate">{job.message || `by ${job.triggered_by}`}</td>
              </tr>
            ))}
            {(jobs ?? []).length === 0 && (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-gray-400 text-sm">Chưa có job nào. Bấm "Chạy ngay" để bắt đầu.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
