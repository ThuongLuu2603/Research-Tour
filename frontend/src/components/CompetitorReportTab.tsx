import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, lazy, Suspense } from "react";
import { fetchCompetitorReportHtml, saveCompetitorReportHtml } from "@/lib/api";
import { Printer, Download, RefreshCw, Pencil } from "lucide-react";

const ReportEditor = lazy(() => import("@/components/ReportEditor"));

export default function CompetitorReportTab({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const { data: html } = useQuery({
    queryKey: ["competitor-report-html"],
    queryFn: () => fetchCompetitorReportHtml(false),
    staleTime: 30 * 60_000,
  });

  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<"refresh" | "save" | null>(null);
  const [msg, setMsg] = useState("");

  const doRefresh = async () => {
    setBusy("refresh"); setMsg("");
    try {
      const fresh = await fetchCompetitorReportHtml(true);
      qc.setQueryData(["competitor-report-html"], fresh);
      setEditing(false);
      setMsg("Đã dựng lại theo dữ liệu mới.");
    } finally { setBusy(null); }
  };

  const handleSave = async (fullHtml: string) => {
    setBusy("save"); setMsg("");
    try {
      await saveCompetitorReportHtml(fullHtml);
      qc.setQueryData(["competitor-report-html"], fullHtml);
      setEditing(false);
      setMsg("Đã lưu chỉnh sửa vào hệ thống.");
    } catch { setMsg("Lưu thất bại — thử lại."); }
    finally { setBusy(null); }
  };

  const printReport = () => {
    const w = window.open("", "_blank");
    if (!w || !html) return;
    w.document.write(html); w.document.close(); w.focus(); w.print();
  };
  const downloadHtml = () => {
    if (!html) return;
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `vietravel-so-sanh-doi-thu-${new Date().toISOString().slice(0, 10)}.html`;
    a.click();
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end gap-2 flex-wrap">
        {msg && <span className="text-xs text-green-700 mr-auto">{msg}</span>}
        <button onClick={doRefresh} disabled={busy !== null} className="btn-secondary text-xs flex items-center gap-1">
          <RefreshCw size={14} className={busy === "refresh" ? "animate-spin" : ""} /> Làm mới
        </button>
        {canEdit && !editing && (
          <button onClick={() => { setEditing(true); setMsg(""); }} disabled={!html} className="btn-secondary text-xs flex items-center gap-1">
            <Pencil size={14} /> Sửa trực tiếp
          </button>
        )}
        <button onClick={printReport} disabled={!html || editing} className="btn-primary text-xs flex items-center gap-1">
          <Printer size={14} /> In / PDF
        </button>
        <button onClick={downloadHtml} disabled={!html || editing} className="btn-secondary text-xs flex items-center gap-1">
          <Download size={14} /> Tải HTML
        </button>
      </div>

      {editing && html ? (
        <div className="card p-3">
          <Suspense fallback={<div className="flex items-center gap-2 text-sm text-gray-500 p-4"><RefreshCw size={16} className="animate-spin" /> Đang nạp trình soạn thảo…</div>}>
            <ReportEditor html={html} onSave={handleSave} onCancel={() => setEditing(false)} saving={busy === "save"} />
          </Suspense>
        </div>
      ) : (
        <div className="card overflow-hidden p-0 bg-white">
          {html ? (
            <iframe title="Competitor Report" srcDoc={html} className="w-full border-0"
              style={{ height: "calc(100vh - 210px)", minHeight: "640px" }} />
          ) : (
            <div className="flex items-center justify-center h-64 text-gray-400 text-sm">Đang dựng báo cáo so sánh đối thủ…</div>
          )}
        </div>
      )}
      <p className="text-xs text-gray-400">
        Menu “Đầu khởi hành” ở đầu báo cáo — bấm để nhảy tới mục.
        {canEdit && " Admin bấm “Sửa trực tiếp” để chỉnh TOÀN BỘ (chữ/bảng/giá/nhận định) như Word rồi Lưu."}
      </p>
    </div>
  );
}
