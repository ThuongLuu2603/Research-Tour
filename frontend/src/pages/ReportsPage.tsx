import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, lazy, Suspense } from "react";
import { fetchReportHtml, saveReportHtml } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { PageTitle } from "@/components/InfoTip";
import { Download, Printer, RefreshCw, Pencil } from "lucide-react";

const ReportEditor = lazy(() => import("@/components/ReportEditor"));

export default function ReportsPage() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "super_admin";
  const qc = useQueryClient();

  const { data: html } = useQuery({
    queryKey: ["report-html"],
    queryFn: () => fetchReportHtml(false),
    staleTime: 30 * 60_000, // báo cáo lưu sẵn — không tự dựng lại mỗi lần vào
  });

  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<"refresh" | "save" | null>(null);
  const [msg, setMsg] = useState("");

  // "Làm mới" = DỰNG LẠI từ dữ liệu mới nhất (xoá chỉnh sửa tay).
  const doRefresh = async () => {
    setBusy("refresh"); setMsg("");
    try {
      const fresh = await fetchReportHtml(true);
      qc.setQueryData(["report-html"], fresh);
      setEditing(false);
      setMsg("Đã dựng lại báo cáo theo dữ liệu mới.");
    } finally { setBusy(null); }
  };

  // ReportEditor (TinyMCE) gọi khi bấm Lưu — ghi đè vào hệ thống + thoát chế độ sửa.
  const handleSave = async (fullHtml: string) => {
    setBusy("save"); setMsg("");
    try {
      await saveReportHtml(fullHtml);
      qc.setQueryData(["report-html"], fullHtml);
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
    a.download = `vietravel-ci-${new Date().toISOString().slice(0, 10)}.html`;
    a.click();
  };

  return (
    <div className="p-6 space-y-4 flex flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <PageTitle title="Báo cáo CI Vietravel" tip="Báo cáo trình bày cho BGĐ — xem online hoặc in/PDF offline" />
          <p className="text-sm text-gray-500 mt-1">Ưu tiên: Giá → Tần suất → Phủ sóng · Lưu sẵn, chỉ dựng lại khi “Làm mới” hoặc snapshot ngày tự chạy</p>
        </div>
        <div className="flex gap-2 items-center">
          {msg && <span className="text-xs text-green-700">{msg}</span>}
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
            <Download size={14} /> Tải HTML offline
          </button>
        </div>
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
            <iframe
              title="CI Report"
              srcDoc={html}
              className="w-full border-0"
              style={{ height: "calc(100vh - 150px)", minHeight: "640px" }}
            />
          ) : (
            <div className="flex items-center justify-center h-64 text-gray-400 text-sm">Đang tải báo cáo...</div>
          )}
        </div>
      )}

      <p className="text-xs text-gray-400">
        Mẹo: In/PDF → chọn &quot;Save as PDF&quot; để gửi file offline cho BGĐ.
        {canEdit && " Admin bấm “Sửa trực tiếp” để chỉnh chữ/bảng/ghi chú (như Word) rồi Lưu."}
      </p>
    </div>
  );
}
