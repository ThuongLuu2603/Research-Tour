import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useEffect, useState } from "react";
import { fetchReportHtml, saveReportHtml } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { PageTitle } from "@/components/InfoTip";
import { Download, Printer, RefreshCw, Pencil, Save } from "lucide-react";

export default function ReportsPage() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "super_admin";
  const qc = useQueryClient();

  const { data: html } = useQuery({
    queryKey: ["report-html"],
    queryFn: () => fetchReportHtml(false),
    staleTime: 30 * 60_000, // báo cáo lưu sẵn — không tự dựng lại mỗi lần vào
  });

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<"refresh" | "save" | null>(null);
  const [msg, setMsg] = useState("");

  const applyEditable = (on: boolean) => {
    const body = iframeRef.current?.contentDocument?.body;
    if (body) body.setAttribute("contenteditable", on ? "true" : "false");
  };
  useEffect(() => { applyEditable(editing); }, [editing, html]);

  const currentHtml = (): string => {
    const docEl = iframeRef.current?.contentDocument?.documentElement;
    if (docEl) {
      const clone = docEl.cloneNode(true) as HTMLElement;
      clone.querySelector("body")?.removeAttribute("contenteditable");
      return "<!DOCTYPE html>" + clone.outerHTML;
    }
    return html || "";
  };

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

  // "Lưu" = ghi đè bản chỉnh sửa tay vào hệ thống (giữ tới khi Làm mới / snapshot ngày).
  const doSave = async () => {
    setBusy("save"); setMsg("");
    try {
      const out = currentHtml();
      await saveReportHtml(out);
      qc.setQueryData(["report-html"], out);
      setEditing(false);  // thoát chế độ sửa sau khi lưu
      setMsg("Đã lưu chỉnh sửa vào hệ thống.");
    } catch { setMsg("Lưu thất bại — thử lại."); }
    finally { setBusy(null); }
  };

  // Lệnh định dạng (Word-like) áp lên vùng đang chọn trong iframe.
  const cmd = (command: string, value?: string) => {
    const doc = iframeRef.current?.contentDocument;
    if (!doc) return;
    iframeRef.current?.contentWindow?.focus();
    try { doc.execCommand("styleWithCSS", false, "true"); } catch { /* ignore */ }
    doc.execCommand(command, false, value);
  };

  const printReport = () => {
    const out = currentHtml();
    const w = window.open("", "_blank");
    if (!w || !out) return;
    w.document.write(out); w.document.close(); w.focus(); w.print();
  };

  const downloadHtml = () => {
    const out = currentHtml();
    if (!out) return;
    const blob = new Blob([out], { type: "text/html;charset=utf-8" });
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
          {canEdit && (
            <>
              <button onClick={() => setEditing((v) => !v)}
                className={`text-xs flex items-center gap-1 ${editing ? "btn-primary" : "btn-secondary"}`}>
                <Pencil size={14} /> {editing ? "Đang sửa" : "Sửa trực tiếp"}
              </button>
              {editing && (
                <button onClick={doSave} disabled={busy !== null} className="btn-primary text-xs flex items-center gap-1">
                  <Save size={14} className={busy === "save" ? "animate-spin" : ""} /> Lưu
                </button>
              )}
            </>
          )}
          <button onClick={printReport} disabled={!html} className="btn-primary text-xs flex items-center gap-1">
            <Printer size={14} /> In / PDF
          </button>
          <button onClick={downloadHtml} disabled={!html} className="btn-secondary text-xs flex items-center gap-1">
            <Download size={14} /> Tải HTML offline
          </button>
        </div>
      </div>

      {editing && (
        <>
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-1.5">
            ✏️ Đang bật chế độ sửa — bôi đen chữ rồi dùng thanh công cụ; gõ vào ô <strong>Ghi chú</strong> nền vàng. Xong bấm <strong>Lưu</strong> (sẽ thoát chế độ sửa).
          </p>
          <div className="flex flex-wrap items-center gap-1 bg-gray-50 border rounded px-2 py-1.5 text-sm sticky top-0 z-10">
            <button title="Đậm" className="w-7 h-7 rounded hover:bg-gray-200 font-bold" onClick={() => cmd("bold")}>B</button>
            <button title="Nghiêng" className="w-7 h-7 rounded hover:bg-gray-200 italic" onClick={() => cmd("italic")}>I</button>
            <button title="Gạch chân" className="w-7 h-7 rounded hover:bg-gray-200 underline" onClick={() => cmd("underline")}>U</button>
            <span className="w-px h-5 bg-gray-300 mx-1" />
            <select title="Cỡ chữ" className="input text-xs py-0.5 w-16" defaultValue=""
              onChange={(e) => { if (e.target.value) cmd("fontSize", e.target.value); e.target.value = ""; }}>
              <option value="">Cỡ</option>
              <option value="2">Nhỏ</option>
              <option value="3">Vừa</option>
              <option value="5">Lớn</option>
              <option value="6">Rất lớn</option>
            </select>
            <label title="Màu chữ" className="w-7 h-7 rounded hover:bg-gray-200 flex items-center justify-center cursor-pointer relative">
              <span className="font-bold">A</span>
              <input type="color" className="absolute inset-0 opacity-0 cursor-pointer" onChange={(e) => cmd("foreColor", e.target.value)} />
            </label>
            <label title="Tô nền" className="w-7 h-7 rounded hover:bg-gray-200 flex items-center justify-center cursor-pointer relative" style={{ background: "#fef08a" }}>
              <span>🖍</span>
              <input type="color" className="absolute inset-0 opacity-0 cursor-pointer" defaultValue="#fde68a" onChange={(e) => cmd("hiliteColor", e.target.value)} />
            </label>
            <span className="w-px h-5 bg-gray-300 mx-1" />
            <button title="Danh sách chấm" className="w-7 h-7 rounded hover:bg-gray-200" onClick={() => cmd("insertUnorderedList")}>•</button>
            <button title="Căn trái" className="w-7 h-7 rounded hover:bg-gray-200" onClick={() => cmd("justifyLeft")}>⬅</button>
            <button title="Căn giữa" className="w-7 h-7 rounded hover:bg-gray-200" onClick={() => cmd("justifyCenter")}>⬌</button>
            <span className="w-px h-5 bg-gray-300 mx-1" />
            <button title="Hoàn tác" className="w-7 h-7 rounded hover:bg-gray-200" onClick={() => cmd("undo")}>↶</button>
            <button title="Làm lại" className="w-7 h-7 rounded hover:bg-gray-200" onClick={() => cmd("redo")}>↷</button>
            <button title="Xoá định dạng" className="px-2 h-7 rounded hover:bg-gray-200 text-xs text-gray-600" onClick={() => cmd("removeFormat")}>Xoá ĐD</button>
          </div>
        </>
      )}

      <div className="card overflow-hidden p-0 bg-white">
        {html ? (
          <iframe
            ref={iframeRef}
            title="CI Report"
            srcDoc={html}
            onLoad={() => applyEditable(editing)}
            className="w-full border-0"
            style={{ height: "calc(100vh - 150px)", minHeight: "640px" }}
          />
        ) : (
          <div className="flex items-center justify-center h-64 text-gray-400 text-sm">Đang tải báo cáo...</div>
        )}
      </div>

      <p className="text-xs text-gray-400">
        Mẹo: In/PDF → chọn &quot;Save as PDF&quot; để gửi file offline cho BGĐ.
        {canEdit && " Admin có thể “Sửa trực tiếp” + “Lưu” để thêm ghi chú/chỉnh số — lưu vào hệ thống, hiện lại khi mở."}
      </p>
    </div>
  );
}
