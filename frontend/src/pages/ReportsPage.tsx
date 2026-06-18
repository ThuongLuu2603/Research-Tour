import { useQuery } from "@tanstack/react-query";
import { useRef, useEffect, useState } from "react";
import { fetchReportHtml } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { PageTitle } from "@/components/InfoTip";
import { Download, Printer, RefreshCw, Pencil } from "lucide-react";

export default function ReportsPage() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "super_admin";

  const { data: html, refetch, isFetching } = useQuery({
    queryKey: ["report-html"],
    queryFn: fetchReportHtml,
    staleTime: 5 * 60_000, // báo cáo đổi chậm — không gọi lại mỗi lần mở (vẫn có nút Làm mới)
  });

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [editing, setEditing] = useState(false);

  // Bật/tắt sửa trực tiếp trên body của iframe (chỉ admin).
  const applyEditable = (on: boolean) => {
    const body = iframeRef.current?.contentDocument?.body;
    if (body) body.setAttribute("contenteditable", on ? "true" : "false");
  };
  useEffect(() => { applyEditable(editing); }, [editing, html]);

  // Lấy HTML hiện tại (kèm chỉnh sửa của admin) để in/tải.
  const currentHtml = (): string => {
    const docEl = iframeRef.current?.contentDocument?.documentElement;
    if (docEl) {
      const clone = docEl.cloneNode(true) as HTMLElement;
      clone.querySelector("body")?.removeAttribute("contenteditable");
      return "<!DOCTYPE html>" + clone.outerHTML;
    }
    return html || "";
  };

  const printReport = () => {
    const out = currentHtml();
    const w = window.open("", "_blank");
    if (!w || !out) return;
    w.document.write(out);
    w.document.close();
    w.focus();
    w.print();
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
    <div className="p-6 space-y-4 h-full flex flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <PageTitle title="Báo cáo CI Vietravel" tip="Báo cáo trình bày cho BGĐ — xem online hoặc in/PDF offline" />
          <p className="text-sm text-gray-500 mt-1">Ưu tiên: Giá → Tần suất → Phủ sóng · Cập nhật theo snapshot hàng ngày</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => refetch()} className="btn-secondary text-xs flex items-center gap-1">
            <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} /> Làm mới
          </button>
          {canEdit && (
            <button onClick={() => setEditing((v) => !v)}
              className={`text-xs flex items-center gap-1 ${editing ? "btn-primary" : "btn-secondary"}`}>
              <Pencil size={14} /> {editing ? "Đang sửa — bấm để khoá" : "Sửa trực tiếp"}
            </button>
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
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-1.5">
          ✏️ Đang bật chế độ sửa — bấm vào ô (đặc biệt cột <strong>Ghi chú</strong> nền vàng) để gõ. Sửa xong bấm <strong>In/PDF</strong> hoặc <strong>Tải HTML</strong> sẽ giữ nội dung đã sửa (không lưu vào hệ thống).
        </p>
      )}

      <div className="card flex-1 min-h-[600px] overflow-hidden p-0 bg-white">
        {html ? (
          <iframe
            ref={iframeRef}
            title="CI Report"
            srcDoc={html}
            onLoad={() => applyEditable(editing)}
            className="w-full h-full min-h-[600px] border-0"
          />
        ) : (
          <div className="flex items-center justify-center h-64 text-gray-400 text-sm">Đang tải báo cáo...</div>
        )}
      </div>

      <p className="text-xs text-gray-400">
        Mẹo: In/PDF → chọn &quot;Save as PDF&quot; để gửi file offline cho BGĐ.
        {canEdit && " Admin có thể bấm “Sửa trực tiếp” để thêm ghi chú/chỉnh số trước khi xuất."}
      </p>
    </div>
  );
}
