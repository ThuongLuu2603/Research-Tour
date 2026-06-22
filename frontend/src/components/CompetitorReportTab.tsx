import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, lazy, Suspense } from "react";
import {
  fetchCompetitorReportHtml, getCompetitorDepartures,
  fetchCompetitorDepartureHtml, saveCompetitorDepartureHtml,
} from "@/lib/api";
import { Printer, Download, RefreshCw, Pencil, X } from "lucide-react";

const ReportEditor = lazy(() => import("@/components/ReportEditor"));

export default function CompetitorReportTab({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const { data: html } = useQuery({
    queryKey: ["competitor-report-html"],
    queryFn: () => fetchCompetitorReportHtml(false),
    staleTime: 30 * 60_000,
  });
  const { data: depList } = useQuery({
    queryKey: ["competitor-departures"],
    queryFn: getCompetitorDepartures,
    enabled: canEdit,
    staleTime: 30 * 60_000,
  });

  const [editDep, setEditDep] = useState<string | null>(null); // đầu KH đang sửa
  const [depHtml, setDepHtml] = useState<string | null>(null);
  const [busy, setBusy] = useState<"refresh" | "load" | "save" | null>(null);
  const [msg, setMsg] = useState("");

  const doRefresh = async () => {
    setBusy("refresh"); setMsg("");
    try {
      const fresh = await fetchCompetitorReportHtml(true);
      qc.setQueryData(["competitor-report-html"], fresh);
      setEditDep(null); setDepHtml(null);
      setMsg("Đã dựng lại theo dữ liệu mới (xoá chỉnh sửa tay).");
    } finally { setBusy(null); }
  };

  const startEdit = async (dep: string) => {
    setBusy("load"); setMsg(""); setEditDep(dep); setDepHtml(null);
    try { setDepHtml(await fetchCompetitorDepartureHtml(dep)); }
    finally { setBusy(null); }
  };

  const handleSave = async (fullHtml: string) => {
    if (!editDep) return;
    setBusy("save"); setMsg("");
    try {
      await saveCompetitorDepartureHtml(editDep, fullHtml);
      const fresh = await fetchCompetitorReportHtml(false);
      qc.setQueryData(["competitor-report-html"], fresh);
      setEditDep(null); setDepHtml(null);
      setMsg(`Đã lưu chỉnh sửa cho "${editDep}".`);
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

  // Chế độ SỬA 1 đầu khởi hành (doc nhỏ → TinyMCE mượt).
  if (editDep) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-gray-800">Sửa: Khách từ {editDep}</span>
          {msg && <span className="text-xs text-green-700">{msg}</span>}
          <button onClick={() => { setEditDep(null); setDepHtml(null); }} className="btn-secondary text-xs flex items-center gap-1 ml-auto">
            <X size={13} /> Đóng (không lưu)
          </button>
        </div>
        {busy === "load" || !depHtml ? (
          <div className="flex items-center gap-2 text-sm text-gray-500 p-4"><RefreshCw size={16} className="animate-spin" /> Đang nạp phần “{editDep}”…</div>
        ) : (
          <div className="card p-3">
            <Suspense fallback={<div className="flex items-center gap-2 text-sm text-gray-500 p-4"><RefreshCw size={16} className="animate-spin" /> Đang nạp trình soạn thảo…</div>}>
              <ReportEditor html={depHtml} onSave={handleSave} onCancel={() => { setEditDep(null); setDepHtml(null); }} saving={busy === "save"} />
            </Suspense>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end gap-2 flex-wrap">
        {msg && <span className="text-xs text-green-700 mr-auto">{msg}</span>}
        {canEdit && (depList?.departures?.length ?? 0) > 0 && (
          <div className="flex items-center gap-1 mr-auto">
            <Pencil size={13} className="text-gray-500" />
            <span className="text-xs text-gray-500">Sửa theo đầu KH:</span>
            <select
              className="text-xs border rounded px-2 py-1 max-w-[200px]"
              defaultValue=""
              onChange={(e) => { if (e.target.value) startEdit(e.target.value); e.target.value = ""; }}
            >
              <option value="">— chọn đầu khởi hành —</option>
              {depList!.departures.map((d) => (
                <option key={d.diem_kh} value={d.diem_kh}>{d.diem_kh} ({d.markets} TT)</option>
              ))}
            </select>
          </div>
        )}
        <button onClick={doRefresh} disabled={busy !== null} className="btn-secondary text-xs flex items-center gap-1">
          <RefreshCw size={14} className={busy === "refresh" ? "animate-spin" : ""} /> Làm mới
        </button>
        <button onClick={printReport} disabled={!html} className="btn-primary text-xs flex items-center gap-1">
          <Printer size={14} /> In / PDF
        </button>
        <button onClick={downloadHtml} disabled={!html} className="btn-secondary text-xs flex items-center gap-1">
          <Download size={14} /> Tải HTML
        </button>
      </div>

      <div className="card overflow-hidden p-0 bg-white">
        {html ? (
          <iframe title="Competitor Report" srcDoc={html} className="w-full border-0"
            style={{ height: "calc(100vh - 210px)", minHeight: "640px" }} />
        ) : (
          <div className="flex items-center justify-center h-64 text-gray-400 text-sm">Đang dựng báo cáo so sánh đối thủ…</div>
        )}
      </div>
      <p className="text-xs text-gray-400">
        Menu “Đầu khởi hành” ở đầu báo cáo — bấm để nhảy tới mục.
        {canEdit && " Admin chọn 1 đầu khởi hành ở ô “Sửa theo đầu KH” để chỉnh phần đó (mượt, không lag) rồi Lưu."}
      </p>
    </div>
  );
}
