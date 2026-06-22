import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { getCompetitorReportConfig, saveCompetitorReportConfig } from "@/lib/api";
import { Loader2, Save, Search } from "lucide-react";

function CheckList({ title, options, selected, setSelected }: {
  title: string; options: string[]; selected: Set<string>; setSelected: (s: Set<string>) => void;
}) {
  const [q, setQ] = useState("");
  const shown = useMemo(
    () => options.filter((o) => o.toLowerCase().includes(q.trim().toLowerCase())),
    [options, q],
  );
  const allChecked = shown.length > 0 && shown.every((o) => selected.has(o));
  const toggle = (o: string) => {
    const n = new Set(selected);
    n.has(o) ? n.delete(o) : n.add(o);
    setSelected(n);
  };
  const toggleAll = () => {
    const n = new Set(selected);
    if (allChecked) shown.forEach((o) => n.delete(o));
    else shown.forEach((o) => n.add(o));
    setSelected(n);
  };
  return (
    <div className="card p-3 flex flex-col">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-semibold text-sm">{title} <span className="text-xs font-normal text-gray-400">({selected.size}/{options.length} chọn)</span></h3>
        <button type="button" onClick={toggleAll} className="text-xs text-primary-600">{allChecked ? "Bỏ chọn (lọc)" : "Chọn tất cả (lọc)"}</button>
      </div>
      <div className="relative mb-2">
        <Search size={13} className="absolute left-2 top-2 text-gray-400" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm…"
          className="w-full text-xs border rounded pl-7 pr-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary-400" />
      </div>
      <div className="overflow-auto max-h-[420px] space-y-0.5 pr-1">
        {shown.map((o) => (
          <label key={o} className="flex items-center gap-2 text-xs px-2 py-1 rounded hover:bg-gray-50 cursor-pointer">
            <input type="checkbox" checked={selected.has(o)} onChange={() => toggle(o)} className="accent-primary-600" />
            <span className="truncate" title={o}>{o}</span>
          </label>
        ))}
        {shown.length === 0 && <div className="text-xs text-gray-400 px-2 py-3">Không có mục.</div>}
      </div>
    </div>
  );
}

export default function ReportConfigTab({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["competitor-report-config"], queryFn: getCompetitorReportConfig });

  const [selDeps, setSelDeps] = useState<Set<string>>(new Set());
  const [selMarkets, setSelMarkets] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (data) {
      setSelDeps(new Set(data.selected_departures));
      setSelMarkets(new Set(data.selected_markets));
    }
  }, [data]);

  const save = async () => {
    setBusy(true); setMsg("");
    try {
      await saveCompetitorReportConfig([...selDeps], [...selMarkets]);
      qc.invalidateQueries({ queryKey: ["competitor-report-config"] });
      qc.invalidateQueries({ queryKey: ["competitor-report-html"] });
      qc.invalidateQueries({ queryKey: ["competitor-departures"] });
      qc.invalidateQueries({ queryKey: ["competitor-report-html"] });
      setMsg("Đã lưu cấu hình báo cáo. Vào Báo cáo BGĐ → So sánh đối thủ bấm “Làm mới”.");
    } catch { setMsg("Lưu thất bại — thử lại."); }
    finally { setBusy(false); }
  };

  if (isLoading || !data) return <div className="flex items-center gap-2 text-sm text-gray-500 p-6"><Loader2 size={16} className="animate-spin" /> Đang tải…</div>;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-xs text-gray-500 max-w-3xl">
          Chọn <b>đầu khởi hành</b> và <b>thị trường</b> sẽ đưa vào báo cáo <b>So sánh đối thủ</b> (Báo cáo BGĐ).
          Để trống một cột = lấy <b>tất cả</b>. Sau khi lưu, vào Báo cáo → bấm “Làm mới” để dựng lại.
        </p>
        {canEdit && (
          <button onClick={save} disabled={busy} className="btn-primary text-xs flex items-center gap-1">
            {busy ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Lưu cấu hình
          </button>
        )}
      </div>
      {msg && <div className="text-xs text-green-700">{msg}</div>}
      <div className="grid md:grid-cols-2 gap-3">
        <CheckList title="Đầu khởi hành" options={data.departures_options} selected={selDeps} setSelected={setSelDeps} />
        <CheckList title="Thị trường" options={data.markets_options} selected={selMarkets} setSelected={setSelMarkets} />
      </div>
      {!canEdit && <p className="text-xs text-amber-600">Chỉ admin mới sửa được cấu hình.</p>}
    </div>
  );
}
