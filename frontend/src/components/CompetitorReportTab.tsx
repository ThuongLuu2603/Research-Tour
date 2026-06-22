import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ExternalLink, Loader2, Save, Pencil, X } from "lucide-react";
import {
  getCompetitorReport, saveCompetitorReportOverrides,
  type CompetitorReport, type CompetitorMetrics,
} from "@/lib/api";

const fmtVND = (n: number | null | undefined) =>
  n == null ? "—" : new Intl.NumberFormat("vi-VN").format(Math.round(n)) + "đ";

const keyOf = (dep: string, mkt: string) => `${dep}|||${mkt}`;

function MetricCell({ m }: { m: CompetitorMetrics }) {
  return (
    <div className="text-xs space-y-0.5">
      <div><span className="text-gray-500">SL sản phẩm:</span> <b>{m.products}</b></div>
      <div><span className="text-gray-500">Giá từ:</span> <b className="text-primary-700">{fmtVND(m.price_from)}</b></div>
      <div><span className="text-gray-500">Tần suất:</span> <b>{m.departures || "—"}</b> đoàn</div>
      {m.cheapest_name && <div className="text-gray-400 truncate" title={m.cheapest_name}>SP rẻ nhất: {m.cheapest_name}</div>}
      {m.link ? (
        <a href={m.link} target="_blank" rel="noreferrer" className="text-primary-600 hover:underline inline-flex items-center gap-0.5">
          <ExternalLink size={11} /> Link tour
        </a>
      ) : null}
    </div>
  );
}

export default function CompetitorReportTab({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery<CompetitorReport>({
    queryKey: ["competitor-report"],
    queryFn: getCompetitorReport,
    staleTime: 30 * 60_000,
  });

  const [editing, setEditing] = useState(false);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  // Nạp nhận định đã lưu vào state khi data về.
  useEffect(() => {
    if (data?.overrides) {
      const init: Record<string, string> = {};
      for (const [k, v] of Object.entries(data.overrides)) {
        if (v?.note) init[k] = v.note;
      }
      setNotes(init);
    }
  }, [data]);

  const save = async () => {
    setBusy(true); setMsg("");
    try {
      const overrides: Record<string, { note?: string }> = {};
      for (const [k, note] of Object.entries(notes)) {
        if (note && note.trim()) overrides[k] = { note: note.trim() };
      }
      await saveCompetitorReportOverrides(overrides);
      qc.setQueryData<CompetitorReport>(["competitor-report"], (old) =>
        old ? { ...old, overrides } : old);
      setEditing(false);
      setMsg("Đã lưu nhận định vào hệ thống.");
    } catch { setMsg("Lưu thất bại — thử lại."); }
    finally { setBusy(false); }
  };

  if (isLoading) {
    return <div className="flex items-center gap-2 text-sm text-gray-500 p-6"><Loader2 size={16} className="animate-spin" /> Đang dựng báo cáo so sánh đối thủ…</div>;
  }
  if (!data || data.departures.length === 0) {
    return <div className="text-sm text-gray-400 p-6">Chưa có dữ liệu so sánh.</div>;
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-xs text-gray-500">
          So sánh 1:1 VTR vs <b>đối thủ mạnh nhất</b> mỗi thị trường, theo từng đầu khởi hành (đầu lớn trước).
          Số liệu tự tính từ dữ liệu cào. {canEdit && "Admin điền/sửa Nhận định rồi Lưu."}
        </p>
        <div className="flex items-center gap-2">
          {msg && <span className="text-xs text-green-700">{msg}</span>}
          {canEdit && (editing ? (
            <>
              <button onClick={save} disabled={busy} className="btn-primary text-xs flex items-center gap-1">
                {busy ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Lưu nhận định
              </button>
              <button onClick={() => setEditing(false)} className="btn-secondary text-xs flex items-center gap-1">
                <X size={13} /> Thoát
              </button>
            </>
          ) : (
            <button onClick={() => { setEditing(true); setMsg(""); }} className="btn-secondary text-xs flex items-center gap-1">
              <Pencil size={13} /> Điền / sửa nhận định
            </button>
          ))}
        </div>
      </div>

      {data.departures.map((dep) => (
        <div key={dep.diem_kh} className="card p-4">
          <h2 className="text-lg font-bold text-gray-900 mb-1">
            Khách từ {dep.diem_kh}
            <span className="ml-2 text-xs font-normal text-gray-400">{dep.total_tours} tour · {dep.markets.length} thị trường</span>
          </h2>
          <div className="space-y-3 mt-2">
            {dep.markets.map((mk) => {
              const k = keyOf(dep.diem_kh, mk.thi_truong);
              return (
                <div key={k} className="border rounded-lg overflow-hidden">
                  <div className="bg-gray-50 px-3 py-2 flex items-center justify-between gap-2 flex-wrap">
                    <span className="font-semibold text-gray-800">{mk.thi_truong}</span>
                    <span className="text-xs text-gray-500">
                      Đối thủ mạnh nhất: <b className="text-gray-700">{mk.competitor || "—"}</b>
                      {mk.competitor_company_count > 1 && <> · {mk.competitor_company_count} đối thủ trong TT</>}
                      {" · "}Giá SS thị trường: <b className="text-amber-700">{fmtVND(mk.market_price_from)}</b>
                    </span>
                  </div>
                  <div className="grid grid-cols-2 divide-x">
                    <div className="p-3">
                      <div className="text-[11px] font-semibold text-primary-700 mb-1">★ VIETRAVEL</div>
                      <MetricCell m={mk.vtr} />
                    </div>
                    <div className="p-3">
                      <div className="text-[11px] font-semibold text-gray-700 mb-1">{mk.competitor || "Đối thủ"}</div>
                      <MetricCell m={mk.competitor_metrics} />
                    </div>
                  </div>
                  <div className="px-3 py-2 border-t bg-amber-50/40">
                    <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Nhận định</div>
                    {editing ? (
                      <textarea
                        value={notes[k] || ""}
                        onChange={(e) => setNotes((s) => ({ ...s, [k]: e.target.value }))}
                        rows={2}
                        placeholder="Nhập nhận định cho thị trường này…"
                        className="w-full text-sm border rounded p-1.5 focus:outline-none focus:ring-1 focus:ring-primary-400"
                      />
                    ) : (
                      <p className="text-sm text-gray-700 whitespace-pre-line">
                        {notes[k] || <span className="text-gray-400 italic">Chưa có nhận định.</span>}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
