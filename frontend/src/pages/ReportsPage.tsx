import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, lazy, Suspense } from "react";
import {
  fetchReportHtml, saveReportHtml,
  fetchCompetitorReportHtml, getCompetitorDepartures,
  fetchCompetitorDepartureHtml, saveCompetitorDepartureHtml,
} from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { PageTitle } from "@/components/InfoTip";
import { cn } from "@/lib/utils";
import { Download, Printer, RefreshCw, Pencil, X } from "lucide-react";

const ReportEditor = lazy(() => import("@/components/ReportEditor"));

type ReportTab = "ci" | "competitor";

export default function ReportsPage() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "super_admin";
  const qc = useQueryClient();
  const [tab, setTab] = useState<ReportTab>("ci");
  const [busy, setBusy] = useState<"refresh" | "save" | "load" | null>(null);
  const [msg, setMsg] = useState("");

  // ── Báo cáo CI ──────────────────────────────────────────────────────────
  const { data: html } = useQuery({
    queryKey: ["report-html"], queryFn: () => fetchReportHtml(false), staleTime: 30 * 60_000,
  });
  const [editing, setEditing] = useState(false);

  const ciRefresh = async () => {
    setBusy("refresh"); setMsg("");
    try { const f = await fetchReportHtml(true); qc.setQueryData(["report-html"], f); setEditing(false); setMsg("Đã dựng lại báo cáo."); }
    finally { setBusy(null); }
  };
  const ciSave = async (full: string) => {
    setBusy("save"); setMsg("");
    try { await saveReportHtml(full); qc.setQueryData(["report-html"], full); setEditing(false); setMsg("Đã lưu chỉnh sửa."); }
    catch { setMsg("Lưu thất bại."); } finally { setBusy(null); }
  };

  // ── So sánh đối thủ ─────────────────────────────────────────────────────
  const { data: compHtml } = useQuery({
    queryKey: ["competitor-report-html"], queryFn: () => fetchCompetitorReportHtml(false), staleTime: 30 * 60_000,
    enabled: tab === "competitor",
  });
  const { data: depList } = useQuery({
    queryKey: ["competitor-departures"], queryFn: getCompetitorDepartures, enabled: tab === "competitor" && canEdit, staleTime: 30 * 60_000,
  });
  const [editDep, setEditDep] = useState<string | null>(null);
  const [depHtml, setDepHtml] = useState<string | null>(null);

  const compRefresh = async () => {
    setBusy("refresh"); setMsg("");
    try { const f = await fetchCompetitorReportHtml(true); qc.setQueryData(["competitor-report-html"], f); setEditDep(null); setDepHtml(null); setMsg("Đã dựng lại theo dữ liệu mới."); }
    finally { setBusy(null); }
  };
  const compStartEdit = async (dep: string) => {
    setBusy("load"); setMsg(""); setEditDep(dep); setDepHtml(null);
    try { setDepHtml(await fetchCompetitorDepartureHtml(dep)); } finally { setBusy(null); }
  };
  const compSave = async (full: string) => {
    if (!editDep) return;
    setBusy("save"); setMsg("");
    try { await saveCompetitorDepartureHtml(editDep, full); const f = await fetchCompetitorReportHtml(false); qc.setQueryData(["competitor-report-html"], f); setEditDep(null); setDepHtml(null); setMsg(`Đã lưu "${editDep}".`); }
    catch { setMsg("Lưu thất bại."); } finally { setBusy(null); }
  };

  // ── Chung: in / tải theo tab ────────────────────────────────────────────
  const activeHtml = tab === "ci" ? html : compHtml;
  const printReport = () => { const w = window.open("", "_blank"); if (!w || !activeHtml) return; w.document.write(activeHtml); w.document.close(); w.focus(); w.print(); };
  const downloadHtml = () => {
    if (!activeHtml) return;
    const blob = new Blob([activeHtml], { type: "text/html;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `vietravel-${tab === "ci" ? "ci" : "so-sanh-doi-thu"}-${new Date().toISOString().slice(0, 10)}.html`;
    a.click();
  };

  const ciEditingNow = tab === "ci" && editing;
  const compEditingNow = tab === "competitor" && !!editDep;

  return (
    <div className="p-6 space-y-3 flex flex-col">
      {/* Header: tiêu đề + nút hành động của tab đang xem (đồng bộ 2 tab) */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <PageTitle title="Báo cáo BGĐ" tip="Báo cáo trình bày cho BGĐ — xem online hoặc in/PDF offline" />
          <p className="text-sm text-gray-500 mt-1">Lưu sẵn, chỉ dựng lại khi “Làm mới” hoặc snapshot ngày tự chạy</p>
        </div>
        <div className="flex gap-2 items-center">
          {msg && <span className="text-xs text-green-700">{msg}</span>}
          <button onClick={tab === "ci" ? ciRefresh : compRefresh} disabled={busy !== null} className="btn-secondary text-xs flex items-center gap-1">
            <RefreshCw size={14} className={busy === "refresh" ? "animate-spin" : ""} /> Làm mới
          </button>
          {tab === "ci" && canEdit && !editing && (
            <button onClick={() => { setEditing(true); setMsg(""); }} disabled={!html} className="btn-secondary text-xs flex items-center gap-1">
              <Pencil size={14} /> Sửa trực tiếp
            </button>
          )}
          <button onClick={printReport} disabled={!activeHtml || ciEditingNow || compEditingNow} className="btn-primary text-xs flex items-center gap-1">
            <Printer size={14} /> In / PDF
          </button>
          <button onClick={downloadHtml} disabled={!activeHtml || ciEditingNow || compEditingNow} className="btn-secondary text-xs flex items-center gap-1">
            <Download size={14} /> Tải HTML
          </button>
        </div>
      </div>

      {/* Tabs + (cho tab So sánh đối thủ) ô chọn đầu KH để sửa — cùng 1 hàng cho gọn */}
      <div className="border-b border-gray-200 flex items-center justify-between gap-2 flex-wrap">
        <div className="flex gap-1">
          {([["ci", "Báo cáo CI"], ["competitor", "So sánh đối thủ"]] as [ReportTab, string][]).map(([k, label]) => (
            <button key={k} type="button" onClick={() => setTab(k)}
              className={cn("px-4 py-2 text-sm font-medium border-b-2 transition-colors",
                tab === k ? "border-primary-600 text-primary-700" : "border-transparent text-gray-600 hover:text-gray-900")}>
              {label}
            </button>
          ))}
        </div>
        {tab === "competitor" && canEdit && !editDep && (depList?.departures?.length ?? 0) > 0 && (
          <div className="flex items-center gap-1 pb-1">
            <Pencil size={13} className="text-gray-500" />
            <span className="text-xs text-gray-500">Sửa theo đầu KH:</span>
            <select className="text-xs border rounded px-2 py-1 max-w-[200px]" value=""
              onChange={(e) => { if (e.target.value) compStartEdit(e.target.value); }}>
              <option value="">— chọn đầu khởi hành —</option>
              {depList!.departures.map((d) => <option key={d.diem_kh} value={d.diem_kh}>{d.diem_kh} ({d.markets} TT)</option>)}
            </select>
          </div>
        )}
        {compEditingNow && (
          <button onClick={() => { setEditDep(null); setDepHtml(null); }} className="btn-secondary text-xs flex items-center gap-1 mb-1">
            <X size={13} /> Đóng sửa “{editDep}”
          </button>
        )}
      </div>

      {/* Body */}
      {tab === "competitor" ? (
        compEditingNow ? (
          (busy === "load" || !depHtml) ? (
            <div className="flex items-center gap-2 text-sm text-gray-500 p-4"><RefreshCw size={16} className="animate-spin" /> Đang nạp phần “{editDep}”…</div>
          ) : (
            <div className="card p-3">
              <Suspense fallback={<div className="flex items-center gap-2 text-sm text-gray-500 p-4"><RefreshCw size={16} className="animate-spin" /> Đang nạp trình soạn thảo…</div>}>
                <ReportEditor html={depHtml} onSave={compSave} onCancel={() => { setEditDep(null); setDepHtml(null); }} saving={busy === "save"} />
              </Suspense>
            </div>
          )
        ) : (
          <div className="card overflow-hidden p-0 bg-white">
            {compHtml ? (
              <iframe title="Competitor Report" srcDoc={compHtml} className="w-full border-0" style={{ height: "calc(100vh - 170px)", minHeight: "640px" }} />
            ) : <div className="flex items-center justify-center h-64 text-gray-400 text-sm">Đang dựng báo cáo so sánh đối thủ…</div>}
          </div>
        )
      ) : ciEditingNow && html ? (
        <div className="card p-3">
          <Suspense fallback={<div className="flex items-center gap-2 text-sm text-gray-500 p-4"><RefreshCw size={16} className="animate-spin" /> Đang nạp trình soạn thảo…</div>}>
            <ReportEditor html={html} onSave={ciSave} onCancel={() => setEditing(false)} saving={busy === "save"} />
          </Suspense>
        </div>
      ) : (
        <div className="card overflow-hidden p-0 bg-white">
          {html ? (
            <iframe title="CI Report" srcDoc={html} className="w-full border-0" style={{ height: "calc(100vh - 170px)", minHeight: "640px" }} />
          ) : <div className="flex items-center justify-center h-64 text-gray-400 text-sm">Đang tải báo cáo...</div>}
        </div>
      )}
    </div>
  );
}
