import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  triggerScrape, getScrapeJobs, getScrapeJob, getSchedule, updateSchedule, getDataStatus, syncMainSheetLive,
  syncVietravelFromSheet,
  cancelScrapeJob, reconcileStaleScrapeJobs, ScrapeJob,
} from "@/lib/api";
import { fmtDate, parseAppDate, statusColor, cn } from "@/lib/utils";
import { Play, Clock, CheckCircle, XCircle, Loader2, RefreshCw, Database, Square, ArrowDownToLine } from "lucide-react";

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

function ScraperCard({
  scraper,
  label,
  desc,
  showSyncFromSheet,
}: {
  scraper: "vietravel" | "findtourgo";
  label: string;
  desc: string;
  /** Nếu true: hiển thị thêm nút "Sync từ Sheet → DB" (chỉ áp dụng cho Vietravel —
   *  cho phép user edit thủ công tab Vietravel của Sheet rồi sync ngược về DB).
   *  Auto-chain KHÔNG dùng bước này vì Vietravel scrape đã ghi DB trước. */
  showSyncFromSheet?: boolean;
}) {
  const qc = useQueryClient();
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [syncErr, setSyncErr] = useState<string | null>(null);
  const syncFromSheet = useMutation({
    mutationFn: syncVietravelFromSheet,
    onMutate: () => {
      setSyncMsg(null);
      setSyncErr(null);
    },
    onSuccess: (r: unknown) => {
      const d = (r ?? {}) as { inserted?: number; updated?: number; deleted?: number };
      setSyncMsg(
        `Đã sync Vietravel Sheet → DB: +${d.inserted ?? 0} mới · ~${d.updated ?? 0} cập nhật · −${d.deleted ?? 0} xóa`,
      );
      qc.invalidateQueries({ queryKey: ["scrape-jobs"] });
      qc.invalidateQueries({ queryKey: ["kpi"] });
      qc.invalidateQueries({ queryKey: ["tours"] });
    },
    onError: (e: unknown) => {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e as Error)?.message
        || "Sync thất bại";
      setSyncErr(msg);
    },
  });
  // Khoá "đã xong": một khi job kết thúc, BỎ QUA mọi event cũ (SSE trễ) để card không bị
  // kẹt lại ở 84% "đang ghi…". SSE và polling chạy song song → tránh ghi đè ngược trạng thái.
  const doneRef = useRef(false);

  const stopWatchers = () => {
    esRef.current?.close();
    esRef.current = null;
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const pollJobStatus = (jobId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      if (doneRef.current) { stopWatchers(); return; }
      try {
        const job = await getScrapeJob(jobId);
        const running = job.status === "running" || job.status === "pending";
        if (doneRef.current) { stopWatchers(); return; }
        setProgress({
          pct: !running ? 100 : job.progress_pct,
          msg: job.message || (running ? "Đang chạy…" : job.status),
          done: !running,
          error: job.status === "failed",
          added: job.tours_added,
          updated: job.tours_updated,
        });
        if (!running) {
          doneRef.current = true;            // chốt "đã xong" — event SSE trễ sẽ bị bỏ qua
          stopWatchers();
          qc.invalidateQueries({ queryKey: ["scrape-jobs"] });
          qc.invalidateQueries({ queryKey: ["kpi"] });
          qc.invalidateQueries({ queryKey: ["tours"] });
        }
      } catch {
        /* retry */
      }
    }, 3000);
  };

  const trigger = useMutation({
    mutationFn: () => triggerScrape(scraper),
    onSuccess: (job) => {
      stopWatchers();
      doneRef.current = false;             // job mới → mở lại khoá
      setActiveJobId(job.id);
      setProgress({ pct: 0, msg: "Đang khởi động...", done: false });
      const token = localStorage.getItem("access_token") || "";
      const es = new EventSource(
        `/api/scraper/jobs/${job.id}/stream?token=${encodeURIComponent(token)}`,
      );
      esRef.current = es;
      es.onmessage = (e) => {
        try {
          const ev: ProgressEvent = JSON.parse(e.data);
          if (doneRef.current) return;     // đã xong → bỏ qua event SSE trễ
          setProgress(ev);
          if (ev.done) {
            doneRef.current = true;
            stopWatchers();
            qc.invalidateQueries({ queryKey: ["scrape-jobs"] });
            qc.invalidateQueries({ queryKey: ["kpi"] });
            qc.invalidateQueries({ queryKey: ["tours"] });
          }
        } catch { /* ping */ }
      };
      es.onerror = () => {
        es.close();
        esRef.current = null;
        if (doneRef.current) return;
        setProgress((p) => ({
          pct: p?.pct ?? 0,
          msg: "Theo dõi tiến độ qua polling (SSE không kết nối được)…",
          done: false,
        }));
        pollJobStatus(job.id);
      };
      pollJobStatus(job.id);
    },
    onError: (err: any) => {
      setProgress({ pct: 0, msg: err.response?.data?.detail ?? "Lỗi không xác định", done: true, error: true });
    },
  });

  const isRunning = trigger.isPending || (progress && !progress.done);

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold text-gray-900">{label}</h3>
          <p className="text-xs text-gray-500 mt-0.5">{desc}</p>
        </div>
        <div className="flex flex-col gap-2 shrink-0">
          <button
            onClick={() => trigger.mutate()}
            disabled={!!isRunning}
            className="btn-primary text-xs"
          >
            {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {isRunning ? "Đang chạy..." : "Chạy ngay"}
          </button>
          {showSyncFromSheet && (
            <button
              type="button"
              onClick={() => syncFromSheet.mutate()}
              disabled={syncFromSheet.isPending || !!isRunning}
              className="btn-secondary text-xs"
              title="Kéo edit thủ công từ tab Vietravel của Sheet ngược về DB. Auto-chain KHÔNG chạy bước này."
            >
              {syncFromSheet.isPending
                ? <Loader2 size={14} className="animate-spin" />
                : <ArrowDownToLine size={14} />}
              {syncFromSheet.isPending ? "Đang sync..." : "Sync từ Sheet"}
            </button>
          )}
        </div>
      </div>
      {showSyncFromSheet && (syncMsg || syncErr) && (
        <p className={cn("text-xs", syncErr ? "text-red-600" : "text-green-700")}>
          {syncErr ?? syncMsg}
        </p>
      )}

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

function jobAgeHours(job: ScrapeJob): number {
  const t = parseAppDate(job.started_at).getTime();
  if (Number.isNaN(t)) return 0;
  return (Date.now() - t) / 3_600_000;
}

function isJobLikelyStale(job: ScrapeJob): boolean {
  if (job.status !== "running" && job.status !== "pending") return false;
  const limitH =
    job.scraper_name === "vietravel" ? 3 : job.scraper_name === "sync_main" ? 2 : 2;
  return jobAgeHours(job) >= limitH;
}

function scraperLabel(name: string): string {
  if (name === "sync_main") return "Sync Main → DB";
  return name;
}

function fmtRunningDuration(job: ScrapeJob): string {
  const h = jobAgeHours(job);
  if (h < 1) return `${Math.round(h * 60)} phút`;
  return `${h.toFixed(1)} giờ`;
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

  const cancelJob = useMutation({
    mutationFn: cancelScrapeJob,
    onSuccess: () => refetchJobs(),
  });

  const reconcileStale = useMutation({
    mutationFn: reconcileStaleScrapeJobs,
    onSuccess: (r) => {
      refetchJobs();
      setReconcileMsg(r.message);
      window.setTimeout(() => setReconcileMsg(""), 4000);
    },
  });

  const [reconcileMsg, setReconcileMsg] = useState("");

  useEffect(() => {
    reconcileStaleScrapeJobs()
      .then(() => refetchJobs())
      .catch(() => { /* ignore */ });
  }, []);

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
    mutationFn: syncMainSheetLive,
    onSuccess: () => {
      refetchDataStatus();
      refetchJobs();
    },
  });

  const sheetSyncRunning = dataStatus?.import?.running;
  const sheetPct = dataStatus?.import?.progress_pct ?? 0;
  const sheetDone = dataStatus?.import?.rows_done ?? 0;
  const sheetTotal = dataStatus?.import?.rows_total ?? 0;

  useEffect(() => {
    if (sheetSyncRunning) return;
    if (dataStatus?.complete) {
      qc.invalidateQueries({ queryKey: ["kpi"] });
      qc.invalidateQueries({ queryKey: ["tours"] });
      qc.invalidateQueries({ queryKey: ["by-market"] });
      qc.invalidateQueries({ queryKey: ["by-company"] });
      qc.invalidateQueries({ queryKey: ["by-segment"] });
    }
    if (!sheetSyncRunning && syncData.isSuccess) {
      refetchJobs();
    }
  }, [sheetSyncRunning, dataStatus?.complete, qc, syncData.isSuccess, refetchJobs]);

  useEffect(() => {
    if (schedule) {
      setSchedHour(schedule.hour);
      setSchedMin(schedule.minute);
    }
  }, [schedule]);

  const [schedErr, setSchedErr] = useState("");
  const saveSchedule = async () => {
    setSchedErr("");
    try {
      await updateSchedule(schedHour, schedMin);
      setSavedSched(true);
      await qc.invalidateQueries({ queryKey: ["schedule"] }); // refetch bảng Lịch tự động với giờ mới
      setTimeout(() => setSavedSched(false), 2000);
    } catch (e) {
      setSchedErr(
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "Lưu lịch thất bại — thử lại."
      );
    }
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
                <span className="text-amber-700 ml-2">
                  — tab Main mới có{" "}
                  <strong>{(dataStatus.breakdown?.Main ?? 0).toLocaleString("vi-VN")}</strong>/
                  {(dataStatus.expected_min?.Main ?? 0).toLocaleString("vi-VN")} tour. Bấm
                  <strong> Đồng bộ Sheet Main → DB</strong> để cập nhật đủ từ Google Sheet.
                </span>
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
              <><Loader2 size={16} className="animate-spin" /> {dataStatus?.import?.message || "Đang đồng bộ..."}</>
            ) : (
              <><Database size={16} /> Đồng bộ Sheet Main → DB</>
            )}
          </button>
        </div>
        {sheetSyncRunning && (
          <div className="mt-3 space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-blue-700 font-medium">{dataStatus?.import?.message}</span>
              <span className="text-gray-500">
                {sheetTotal > 0
                  ? `${sheetDone.toLocaleString("vi-VN")}/${sheetTotal.toLocaleString("vi-VN")} (${sheetPct}%)`
                  : `${sheetPct}%`}
              </span>
            </div>
            <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full bg-primary-600 transition-all duration-300"
                style={{ width: `${Math.min(100, sheetPct)}%` }}
              />
            </div>
          </div>
        )}
        {dataStatus?.import?.error && (
          <p className="text-sm text-red-600 mt-3">Lỗi: {dataStatus.import.error}</p>
        )}
        {!sheetSyncRunning && dataStatus?.complete && syncData.isSuccess && (
          <p className="text-sm text-green-700 mt-3">
            ✓ Đồng bộ xong — tổng {dataStatus.total.toLocaleString("vi-VN")} tour.
          </p>
        )}
        {syncData.isError && !dataStatus?.import?.running && (
          <p className="text-sm text-red-600 mt-3">{(syncData.error as Error)?.message || "Đồng bộ thất bại."}</p>
        )}
      </div>

      {/* Scraper cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ScraperCard
          scraper="vietravel"
          label="Vietravel — travel.com.vn"
          desc="DB trước → xuất tab Sheet Vietravel"
          showSyncFromSheet
        />
        <ScraperCard
          scraper="findtourgo"
          label="FindTourGo — OTA Aggregator"
          desc="Phân loại thị trường/tuyến → ghi tab FindTourGo (không lưu DB)"
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
        <div className="rounded-md bg-primary-50/60 border border-primary-100 px-3 py-2 text-[11px] text-primary-700 mb-2">
          <strong>Chế độ chuỗi tự động:</strong> chỉ bước 1 chạy theo giờ cố định. Các bước sau tự kích hoạt
          ngay khi bước trước hoàn tất → tiết kiệm thời gian chờ, hoàn tất sớm vào ban đêm.
        </div>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-gray-500 border-b">
              <th className="pb-2 font-medium">Tác vụ</th>
              <th className="pb-2 font-medium">Giờ VN</th>
              <th className="pb-2 font-medium">Lần chạy gần nhất</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {(schedule?.jobs ?? [
              { label: "1. Scrape Vietravel", time_vn: `${String(schedHour).padStart(2, "0")}:${String(schedMin).padStart(2, "0")}`, is_trigger: true },
              { label: "2. Scrape FindTourGo → Sheet", time_vn: "→ sau bước trước", is_trigger: false },
              { label: "3. Sync Main → DB", time_vn: "→ sau bước trước", is_trigger: false },
              { label: "4. Sync All Sheets → DB", time_vn: "→ sau bước trước", is_trigger: false },
              { label: "5. Snapshot BGĐ", time_vn: "→ sau bước trước", is_trigger: false },
            ]).map((j) => {
              const isTrigger = "is_trigger" in j ? (j as { is_trigger?: boolean }).is_trigger : true;
              return (
                <tr key={j.label}>
                  <td className="py-2 text-gray-800">{j.label}</td>
                  <td className={cn("py-2 font-mono", isTrigger ? "text-primary-700 font-semibold" : "text-gray-400 italic")}>{j.time_vn}</td>
                  <td className="py-2 text-gray-500 whitespace-nowrap">
                    {"last_run_at" in j && j.last_run_at ? fmtDate(String(j.last_run_at)) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="border-t border-gray-100 pt-4">
          <p className="text-xs text-gray-600 mb-2">Giờ kích hoạt chuỗi (các bước sau tự chạy theo thứ tự):</p>
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
            {schedErr && <span className="text-xs text-red-600 mt-4">{schedErr}</span>}
          </div>
        </div>
      </div>

      {reconcileMsg && (
        <p className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2">{reconcileMsg}</p>
      )}
      {(jobs ?? []).some(isJobLikelyStale) && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="btn-secondary text-xs"
            disabled={reconcileStale.isPending}
            onClick={() => reconcileStale.mutate()}
          >
            {reconcileStale.isPending ? "Đang dọn…" : "Dọn job treo"}
          </button>
        </div>
      )}

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
            {(jobs ?? []).map((job: ScrapeJob) => {
              const stale = isJobLikelyStale(job);
              return (
              <tr key={job.id} className={cn("hover:bg-blue-50 transition-colors", stale && "bg-amber-50/80")}>
                <td className="px-4 py-2.5 text-xs text-gray-400">{job.id}</td>
                <td className="px-4 py-2.5 text-xs font-medium text-gray-700">{scraperLabel(job.scraper_name)}</td>
                <td className="px-4 py-2.5">
                  <JobStatusBadge status={job.status} />
                  {stale && job.status === "running" && (
                    <span className="block text-[10px] text-amber-700 mt-0.5">có thể treo {fmtRunningDuration(job)}</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-xs text-green-600 font-medium">+{job.tours_added}</td>
                <td className="px-4 py-2.5 text-xs text-blue-600 font-medium">~{job.tours_updated}</td>
                <td className="px-4 py-2.5 text-xs text-gray-600">{job.tours_total}</td>
                <td className="px-4 py-2.5 text-xs text-gray-500 whitespace-nowrap">{fmtDate(job.started_at)}</td>
                <td className="px-4 py-2.5 text-xs text-gray-500 whitespace-nowrap">
                  {job.finished_at ? fmtDate(job.finished_at) : (
                    <span className={cn(stale ? "text-amber-700" : "text-blue-500 animate-pulse")}>
                      {stale ? `Treo ~${fmtRunningDuration(job)}` : "Đang chạy"}
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-xs text-gray-400 max-w-xs">
                  <span className="truncate block">{job.message || `by ${job.triggered_by}`}</span>
                  {(job.status === "running" || job.status === "pending") && (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 text-[11px] text-red-600 hover:text-red-800 font-semibold mt-1 disabled:opacity-50"
                      disabled={cancelJob.isPending}
                      onClick={() => { if (window.confirm("Dừng job này? Các dữ liệu đã ghi vẫn được giữ.")) cancelJob.mutate(job.id); }}
                    >
                      <Square size={10} fill="currentColor" /> {cancelJob.isPending ? "Đang dừng…" : stale ? "Dừng (treo)" : "Dừng"}
                    </button>
                  )}
                </td>
              </tr>
            );
            })}
            {(jobs ?? []).length === 0 && (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-gray-400 text-sm">Chưa có job nào. Bấm "Chạy ngay" để bắt đầu.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
