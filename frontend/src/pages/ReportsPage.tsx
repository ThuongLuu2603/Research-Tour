import { useQuery } from "@tanstack/react-query";
import { fetchReportHtml } from "@/lib/api";
import { PageTitle } from "@/components/InfoTip";
import { Download, Printer, RefreshCw } from "lucide-react";

export default function ReportsPage() {
  const { data: html, refetch, isFetching } = useQuery({
    queryKey: ["report-html"],
    queryFn: fetchReportHtml,
  });

  const printReport = () => {
    const w = window.open("", "_blank");
    if (!w || !html) return;
    w.document.write(html);
    w.document.close();
    w.focus();
    w.print();
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
          <button onClick={printReport} disabled={!html} className="btn-primary text-xs flex items-center gap-1">
            <Printer size={14} /> In / PDF
          </button>
          <button onClick={downloadHtml} disabled={!html} className="btn-secondary text-xs flex items-center gap-1">
            <Download size={14} /> Tải HTML offline
          </button>
        </div>
      </div>

      <div className="card flex-1 min-h-[600px] overflow-hidden p-0 bg-white">
        {html ? (
          <iframe title="CI Report" srcDoc={html} className="w-full h-full min-h-[600px] border-0" />
        ) : (
          <div className="flex items-center justify-center h-64 text-gray-400 text-sm">Đang tải báo cáo...</div>
        )}
      </div>

      <p className="text-xs text-gray-400">
        Mẹo: In/PDF → chọn &quot;Save as PDF&quot; để gửi file offline cho BGĐ.
      </p>
    </div>
  );
}
