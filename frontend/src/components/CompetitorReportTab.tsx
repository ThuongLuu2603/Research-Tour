import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ExternalLink, Loader2, Save, Pencil, X } from "lucide-react";
import {
  getCompetitorReport, saveCompetitorReportOverrides,
  type CompetitorReport, type CompMetrics, type CompRoute,
} from "@/lib/api";

const fmtVND = (n: number | null | undefined) =>
  n == null ? "—" : new Intl.NumberFormat("vi-VN").format(Math.round(n)) + "đ";
const fmtVNDk = (n: number | null | undefined) =>
  n == null ? "—" : Math.round(n / 1000).toLocaleString("vi-VN") + "K";
const mLabel = (ym: string) => { const [, m] = ym.split("-"); return "T" + parseInt(m, 10); };
const keyOf = (dep: string, mkt: string) => `${dep}|||${mkt}`;

// Dòng tần suất theo tháng: "T5: 11 · T6: 16 · T7: 27"
function freqLine(m: CompMetrics) {
  if (!m.monthly.length) return <span className="text-gray-400">—</span>;
  return (
    <div className="text-[11px] leading-snug">
      <div className="text-gray-500">Mở bán {mLabel(m.sell_from)}–{mLabel(m.sell_to)}</div>
      <div className="text-gray-700">{m.monthly.map((x) => `${mLabel(x.month)}: ${x.count}`).join(" · ")} đoàn</div>
    </div>
  );
}

// Liệt kê từng tuyến trong 1 cột (vtr | competitor | peer)
function routeLines(routes: CompRoute[], pick: "vtr" | "competitor" | "peer") {
  const rows = routes
    .map((r) => ({ tuyen: r.tuyen, m: r[pick] as (CompMetrics & { company?: string }) | null }))
    .filter((x) => x.m);
  if (!rows.length) return <span className="text-gray-300">—</span>;
  return (
    <div className="space-y-1">
      {rows.map(({ tuyen, m }) => (
        <div key={tuyen} className="text-[11px] leading-snug">
          <span className="font-medium text-gray-800">{tuyen}</span>
          {m!.company ? <span className="text-gray-400"> · {m!.company}</span> : null}
          <span className="text-gray-600">: từ <b className="text-primary-700">{fmtVNDk(m!.price_from)}</b> ({m!.products} sp, {m!.departures} đoàn)</span>
          {m!.link ? <a href={m!.link} target="_blank" rel="noreferrer" className="ml-1 text-primary-600 inline-flex items-center"><ExternalLink size={10} /></a> : null}
        </div>
      ))}
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

  useEffect(() => {
    if (data?.overrides) {
      const init: Record<string, string> = {};
      for (const [k, v] of Object.entries(data.overrides)) if (v?.note) init[k] = v.note;
      setNotes(init);
    }
  }, [data]);

  const save = async () => {
    setBusy(true); setMsg("");
    try {
      const overrides: Record<string, { note?: string }> = {};
      for (const [k, note] of Object.entries(notes)) if (note?.trim()) overrides[k] = { note: note.trim() };
      await saveCompetitorReportOverrides(overrides);
      qc.setQueryData<CompetitorReport>(["competitor-report"], (old) => old ? { ...old, overrides } : old);
      setEditing(false); setMsg("Đã lưu nhận định.");
    } catch { setMsg("Lưu thất bại — thử lại."); }
    finally { setBusy(false); }
  };

  if (isLoading) return <div className="flex items-center gap-2 text-sm text-gray-500 p-6"><Loader2 size={16} className="animate-spin" /> Đang dựng báo cáo so sánh đối thủ…</div>;
  if (!data || data.departures.length === 0) return <div className="text-sm text-gray-400 p-6">Chưa có dữ liệu so sánh.</div>;

  const peer = data.peer_name || "Saigontourist";

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-xs text-gray-500">
          So sánh theo <b>đầu khởi hành → thị trường → từng tuyến</b>. Cột Đối thủ lấy <b>cty mạnh nhất mỗi tuyến</b>;
          Cột ngang tầm = <b>{peer}</b>. {canEdit && "Admin điền Nhận định rồi Lưu."}
        </p>
        <div className="flex items-center gap-2">
          {msg && <span className="text-xs text-green-700">{msg}</span>}
          {canEdit && (editing ? (
            <>
              <button onClick={save} disabled={busy} className="btn-primary text-xs flex items-center gap-1">
                {busy ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Lưu nhận định
              </button>
              <button onClick={() => setEditing(false)} className="btn-secondary text-xs flex items-center gap-1"><X size={13} /> Thoát</button>
            </>
          ) : (
            <button onClick={() => { setEditing(true); setMsg(""); }} className="btn-secondary text-xs flex items-center gap-1"><Pencil size={13} /> Điền / sửa nhận định</button>
          ))}
        </div>
      </div>

      {data.departures.map((dep) => (
        <div key={dep.diem_kh} className="card p-4">
          <h2 className="text-lg font-bold text-gray-900 mb-2">
            Khách từ {dep.diem_kh}
            <span className="ml-2 text-xs font-normal text-gray-400">{dep.total_tours} tour · {dep.markets.length} thị trường</span>
          </h2>
          <div className="space-y-4">
            {dep.markets.map((mk) => {
              const k = keyOf(dep.diem_kh, mk.thi_truong);
              return (
                <div key={k} className="border rounded-lg overflow-hidden">
                  <div className="bg-primary-50/60 px-3 py-1.5 font-semibold text-gray-800 text-sm">
                    Thị trường {mk.thi_truong}
                    {mk.competitor_companies.length > 0 && (
                      <span className="ml-2 text-[11px] font-normal text-gray-500">Đối thủ: {mk.competitor_companies.join(", ")}</span>
                    )}
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs border-collapse min-w-[820px]">
                      <thead>
                        <tr className="bg-gray-50 text-gray-600">
                          <th className="border px-2 py-1.5 text-left w-[88px]">Tiêu chí</th>
                          <th className="border px-2 py-1.5 text-left">VTR {dep.diem_kh}</th>
                          <th className="border px-2 py-1.5 text-left">Đối thủ (mạnh nhất / tuyến)</th>
                          <th className="border px-2 py-1.5 text-left">Ngang tầm ({peer})</th>
                        </tr>
                      </thead>
                      <tbody className="align-top">
                        {/* Sản phẩm */}
                        <tr>
                          <td className="border px-2 py-1.5 font-medium text-gray-700">Sản phẩm</td>
                          <td className="border px-2 py-1.5">
                            <div className="text-[11px] text-gray-500 mb-1">{mk.vtr_routes} tuyến · {mk.vtr.departures} đoàn</div>
                            {routeLines(mk.routes, "vtr")}
                          </td>
                          <td className="border px-2 py-1.5">
                            <div className="text-[11px] text-gray-500 mb-1">{mk.competitor_routes} tuyến · {mk.competitor.departures} đoàn</div>
                            {routeLines(mk.routes, "competitor")}
                          </td>
                          <td className="border px-2 py-1.5">
                            <div className="text-[11px] text-gray-500 mb-1">{mk.peer_routes} tuyến · {mk.peer.departures} đoàn</div>
                            {routeLines(mk.routes, "peer")}
                          </td>
                        </tr>
                        {/* Giá bán */}
                        <tr>
                          <td className="border px-2 py-1.5 font-medium text-gray-700">Giá bán</td>
                          <td className="border px-2 py-1.5">
                            <div>Giá từ: <b className="text-primary-700">{fmtVND(mk.vtr.price_from)}</b></div>
                            <div className="text-gray-500">Giá TB: {fmtVND(mk.vtr.price_avg)}</div>
                          </td>
                          <td className="border px-2 py-1.5">
                            <div>Giá từ: <b>{fmtVND(mk.competitor.price_from)}</b></div>
                            <div className="text-amber-700">Giá SS: {fmtVND(mk.competitor.price_avg)}</div>
                          </td>
                          <td className="border px-2 py-1.5">
                            <div>Giá từ: <b>{fmtVND(mk.peer.price_from)}</b></div>
                            <div className="text-gray-500">Giá TB: {fmtVND(mk.peer.price_avg)}</div>
                          </td>
                        </tr>
                        {/* Tần suất KH */}
                        <tr>
                          <td className="border px-2 py-1.5 font-medium text-gray-700">TS khởi hành</td>
                          <td className="border px-2 py-1.5">{freqLine(mk.vtr)}</td>
                          <td className="border px-2 py-1.5">{freqLine(mk.competitor)}</td>
                          <td className="border px-2 py-1.5">{freqLine(mk.peer)}</td>
                        </tr>
                        {/* Nhận định */}
                        <tr>
                          <td className="border px-2 py-1.5 font-medium text-gray-700">Nhận định</td>
                          <td className="border px-2 py-1.5" colSpan={3}>
                            {editing ? (
                              <textarea value={notes[k] || ""} onChange={(e) => setNotes((s) => ({ ...s, [k]: e.target.value }))}
                                rows={2} placeholder="Nhập nhận định cho thị trường này…"
                                className="w-full text-sm border rounded p-1.5 focus:outline-none focus:ring-1 focus:ring-primary-400" />
                            ) : (
                              <p className="text-sm text-gray-700 whitespace-pre-line">{notes[k] || <span className="text-gray-400 italic">Chưa có nhận định.</span>}</p>
                            )}
                          </td>
                        </tr>
                      </tbody>
                    </table>
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
