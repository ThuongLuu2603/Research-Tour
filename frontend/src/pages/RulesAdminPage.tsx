import { Navigate } from "react-router-dom";
import { useMemo, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listMarketRules, createMarketRule, deleteMarketRule, updateMarketRule,
  listRouteRules, createRouteRule, deleteRouteRule, updateRouteRule,
  listCompanyRules, createCompanyRule, deleteCompanyRule, updateCompanyRule,
  listDepartureRules, createDepartureRule, deleteDepartureRule, updateDepartureRule,
  listDurationRules, createDurationRule, deleteDurationRule, updateDurationRule,
  seedMarketDefaults, seedCompanyDefaults, seedDepartureDefaults, seedDurationDefaults,
  seedRouteDefaults,
  applyClassificationToTours,
  getApplyClassificationStatus,
  getRulesUnmatched,
  MarketRule, RouteRule, CompanyRule, DepartureRule, DurationRule, UnmatchedItem,
} from "@/lib/api";
import { COL } from "@/lib/glossary";
import { InfoTip } from "@/components/InfoTip";
import { cn } from "@/lib/utils";
import { formatDurationLabel, parseDurationInput } from "@/lib/durationFormat";
import { Plus, Trash2, RefreshCw, Database, Search, Pencil, Check, X, GripVertical } from "lucide-react";

type Tab = "market" | "route" | "company" | "departure" | "duration";
function matchSearch(q: string, ...parts: (string | number | undefined | null)[]) {
  if (!q.trim()) return true;
  const needle = q.trim().toLowerCase();
  return parts.some((p) => String(p ?? "").toLowerCase().includes(needle));
}

function RuleSearchBar({ value, onChange, total, filtered }: { value: string; onChange: (v: string) => void; total: number; filtered: number }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="relative flex-1 min-w-[220px] max-w-md">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          className="input pl-9 text-sm w-full"
          placeholder="Tìm alias, tên chuẩn, keyword..."
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
      <span className="text-xs text-gray-500">{filtered}/{total} dòng</span>
    </div>
  );
}

function dropHandlers(
  targetKey: string,
  dropTarget: string | null,
  setDropTarget: (k: string | null) => void,
  onAssign: (alias: string) => void,
) {
  const active = dropTarget === targetKey;
  return {
    onDragOver: (e: React.DragEvent) => { e.preventDefault(); setDropTarget(targetKey); },
    onDragLeave: () => { if (dropTarget === targetKey) setDropTarget(null); },
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      setDropTarget(null);
      const alias = e.dataTransfer.getData("text/plain").trim();
      if (alias) onAssign(alias);
    },
    dropClassName: active ? "ring-2 ring-inset ring-primary-500 bg-primary-50" : "",
  };
}

function dragAliasProps(value: string) {
  return {
    draggable: true,
    onDragStart: (e: React.DragEvent) => {
      e.dataTransfer.setData("text/plain", value);
      e.dataTransfer.effectAllowed = "copy";
    },
    className: "cursor-grab active:cursor-grabbing inline-flex items-center gap-1",
  };
}

export default function RulesAdminPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [tab, setTab] = useState<Tab>("market");
  const [search, setSearch] = useState("");
  const [syncMsg, setSyncMsg] = useState("");
  const [applying, setApplying] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<Record<string, string>>({});

  const [mMarket, setMMarket] = useState("");
  const [mKeyword, setMKeyword] = useState("");
  const [rMarket, setRMarket] = useState("");
  const [rRoute, setRRoute] = useState("");
  const [rKeywords, setRKeywords] = useState("");
  const [cCanonical, setCCanonical] = useState("");
  const [cAlias, setCAlias] = useState("");
  const [dCanonical, setDCanonical] = useState("");
  const [dAlias, setDAlias] = useState("");
  const [durDays, setDurDays] = useState("");
  const [durAlias, setDurAlias] = useState("");
  const [dropTarget, setDropTarget] = useState<string | null>(null);

  const { data: marketRules } = useQuery({ queryKey: ["market-rules"], queryFn: listMarketRules, enabled: isAdmin });
  const { data: routeRules } = useQuery({ queryKey: ["route-rules"], queryFn: listRouteRules, enabled: isAdmin });
  const { data: companyRules } = useQuery({ queryKey: ["company-rules"], queryFn: listCompanyRules, enabled: isAdmin });
  const { data: departureRules } = useQuery({ queryKey: ["departure-rules"], queryFn: listDepartureRules, enabled: isAdmin });
  const { data: durationRules } = useQuery({ queryKey: ["duration-rules"], queryFn: listDurationRules, enabled: isAdmin });
  const { data: unmatched } = useQuery({
    queryKey: ["rules-unmatched", tab],
    queryFn: () => getRulesUnmatched(tab),
    enabled: isAdmin,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["market-rules"] });
    qc.invalidateQueries({ queryKey: ["route-rules"] });
    qc.invalidateQueries({ queryKey: ["company-rules"] });
    qc.invalidateQueries({ queryKey: ["departure-rules"] });
    qc.invalidateQueries({ queryKey: ["duration-rules"] });
    qc.invalidateQueries({ queryKey: ["rules-unmatched"] });
    qc.invalidateQueries({ queryKey: ["compare-class-gaps"] });
    qc.invalidateQueries({ queryKey: ["workspace-tours"] });
    qc.invalidateQueries({ queryKey: ["filter-options"] });
  };

  const assignCompanyAlias = async (canonical: string, alias: string) => {
    await createCompanyRule({ canonical_name: canonical, alias });
    invalidate();
    setSyncMsg(`Đã gán alias "${alias}" → ${canonical}`);
  };
  const assignDepartureAlias = async (canonical: string, alias: string) => {
    await createDepartureRule({ canonical_name: canonical, alias });
    invalidate();
    setSyncMsg(`Đã gán alias "${alias}" → ${canonical}`);
  };
  const assignDurationAlias = async (days: number, alias: string) => {
    await createDurationRule({ canonical_days: days, alias });
    invalidate();
    setSyncMsg(`Đã gán "${alias}" → ${days}N`);
  };
  const assignMarketKeyword = async (market: string, keyword: string) => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return;
    await createMarketRule({ market: market.trim(), keyword: kw });
    afterRuleSaved(`Đã thêm keyword «${kw}» → ${market}`);
  };
  const assignRouteKeyword = async (thiTruong: string, tuyenTour: string, keyword: string) => {
    const kw = keyword.trim().toLowerCase();
    if (!kw || !thiTruong.trim() || !tuyenTour.trim()) return;
    await createRouteRule({ thi_truong: thiTruong.trim(), tuyen_tour: tuyenTour.trim(), keywords: kw });
    afterRuleSaved(`Đã thêm keyword tuyến «${kw}»`);
  };

  const showErr = (e: unknown) =>
    setSyncMsg(String((e as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail || (e as Error)?.message || e));

  const pollApplyStatus = (attempt = 0) => {
    getApplyClassificationStatus()
      .then((st) => {
        if (st.running) {
          if (attempt < 120) window.setTimeout(() => pollApplyStatus(attempt + 1), 3000);
          return;
        }
        setApplying(false);
        if (st.message) {
          setSyncMsg(st.message);
          invalidate();
        } else if (st.last_result && typeof (st.last_result as { message?: string }).message === "string") {
          setSyncMsg((st.last_result as { message: string }).message);
          invalidate();
        }
      })
      .catch(() => setApplying(false));
  };

  const onApplyTours = () => {
    setApplying(true);
    setSyncMsg("Đang khởi chạy áp dụng quy tắc lên tour…");
    applyClassificationToTours()
      .then((r) => {
        setSyncMsg(r.message || "Đang áp dụng quy tắc (chạy nền)…");
        pollApplyStatus();
      })
      .catch((e) => { showErr(e); setApplying(false); });
  };

  const afterRuleSaved = (label: string) => {
    invalidate();
    setSyncMsg(`${label} — tour sẽ cập nhật trong vài phút (chạy nền). Bấm «Áp dụng ngay» nếu cần kết quả tức thì.`);
  };

  const startEdit = (id: number, draft: Record<string, string>) => {
    setEditingId(id);
    setEditDraft(draft);
  };
  const cancelEdit = () => { setEditingId(null); setEditDraft({}); };

  const filteredMarket = useMemo(
    () => (marketRules ?? []).filter((r) => matchSearch(search, r.market, r.keyword)),
    [marketRules, search],
  );
  const filteredRoute = useMemo(
    () => (routeRules ?? []).filter((r) => matchSearch(search, r.thi_truong, r.tuyen_tour, r.keywords)),
    [routeRules, search],
  );
  const filteredCompany = useMemo(
    () => (companyRules ?? []).filter((r) => matchSearch(search, r.canonical_name, r.alias)),
    [companyRules, search],
  );
  const filteredDeparture = useMemo(
    () => (departureRules ?? []).filter((r) => matchSearch(search, r.canonical_name, r.alias)),
    [departureRules, search],
  );
  const filteredDuration = useMemo(
    () => (durationRules ?? []).filter((r) =>
      matchSearch(search, r.canonical_days, r.alias, formatDurationLabel(r.canonical_days)),
    ),
    [durationRules, search],
  );
  const filteredUnmatched = useMemo(
    () => (unmatched?.items ?? []).filter((x) => matchSearch(search, x.value, x.count, x.thi_truong)),
    [unmatched, search],
  );
  const canonicalOptions = useMemo(() => {
    if (tab === "company") return [...new Set((companyRules ?? []).map((r) => r.canonical_name))];
    if (tab === "departure") return [...new Set((departureRules ?? []).map((r) => r.canonical_name))];
    return [];
  }, [tab, companyRules, departureRules]);
  const marketOptions = useMemo(
    () => [...new Set((marketRules ?? []).map((r) => r.market))].sort(),
    [marketRules],
  );
  const routeMarketOptions = useMemo(
    () => [...new Set((routeRules ?? []).map((r) => r.thi_truong))].sort(),
    [routeRules],
  );

  const addMarket = useMutation({
    mutationFn: () => createMarketRule({ market: mMarket, keyword: mKeyword }),
    onSuccess: () => { setMKeyword(""); afterRuleSaved("Đã lưu quy tắc thị trường"); },
  });
  const addRoute = useMutation({
    mutationFn: () => createRouteRule({ thi_truong: rMarket, tuyen_tour: rRoute, keywords: rKeywords }),
    onSuccess: () => { setRKeywords(""); afterRuleSaved("Đã lưu quy tắc tuyến"); },
  });
  const addCompany = useMutation({
    mutationFn: () => createCompanyRule({ canonical_name: cCanonical, alias: cAlias }),
    onSuccess: () => { setCAlias(""); afterRuleSaved("Đã thêm alias công ty"); },
  });
  const addDeparture = useMutation({
    mutationFn: () => createDepartureRule({ canonical_name: dCanonical, alias: dAlias }),
    onSuccess: () => { setDAlias(""); afterRuleSaved("Đã thêm alias điểm khởi hành"); },
  });
  const parsedDurDays = parseDurationInput(durDays);
  const addDuration = useMutation({
    mutationFn: () => createDurationRule({ canonical_days: parsedDurDays!, alias: durAlias }),
    onSuccess: () => { setDurDays(""); setDurAlias(""); afterRuleSaved("Đã thêm alias thời gian"); },
  });

  if (!isAdmin) return <Navigate to="/" replace />;

  const actionBtns = (onDelete: () => void, onSave?: () => void) => (
    <td className="px-3 py-2 whitespace-nowrap">
      {editingId !== null && onSave ? (
        <span className="flex gap-1">
          <button type="button" className="text-green-600 p-1" onClick={onSave} title="Lưu"><Check size={14} /></button>
          <button type="button" className="text-gray-400 p-1" onClick={cancelEdit} title="Huỷ"><X size={14} /></button>
        </span>
      ) : (
        <span className="flex gap-1">
          <button type="button" className="text-red-500 p-1" onClick={onDelete} title="Xóa"><Trash2 size={14} /></button>
        </span>
      )}
    </td>
  );

  return (
    <div className="p-6 max-w-5xl space-y-6">
      <div>
        <h1 className="text-xl font-bold">Quy tắc phân loại & Key matching</h1>
        <p className="text-sm text-gray-500">
          Quy tắc lưu trong Supabase và áp dụng <strong>toàn hệ thống</strong> (mọi tour Main/Vietravel): Research Grid, So sánh VTR, Market Lab, phân khúc, báo cáo…
          Sau khi sửa, tour được cập nhật tự động (nền) hoặc bấm «Áp dụng ngay lên tour».
        </p>
      </div>

      <div className="card p-4 space-y-2 bg-slate-50 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-gray-600">Áp dụng lại toàn bộ quy tắc lên mọi tour trong database (toàn hệ thống).</p>
        <button type="button" onClick={onApplyTours} disabled={applying} className="btn-primary text-xs flex items-center gap-1 shrink-0 disabled:opacity-60">
          <RefreshCw size={13} className={applying ? "animate-spin" : ""} /> {applying ? "Đang áp dụng…" : "Áp dụng ngay lên tour"}
        </button>
        {syncMsg && <p className="text-xs text-green-700 bg-green-50 px-3 py-2 rounded w-full">{syncMsg}</p>}
      </div>

      <div className="flex gap-2 flex-wrap">
        {([
          ["market", "Thị trường"],
          ["route", "Tuyến tour"],
          ["company", COL.congTy],
          ["departure", COL.diemKhoiHanh],
          ["duration", COL.thoiGian],
        ] as const).map(([t, label]) => (
          <button key={t} onClick={() => { setTab(t); setSearch(""); cancelEdit(); }}
            className={cn("px-4 py-2 rounded-lg text-sm font-medium", tab === t ? "bg-primary-600 text-white" : "bg-gray-100")}>
            {label}
          </button>
        ))}
      </div>

      <RuleSearchBar
        value={search}
        onChange={setSearch}
        total={
          tab === "market" ? (marketRules?.length ?? 0) + (unmatched?.items?.length ?? 0)
            : tab === "route" ? (routeRules?.length ?? 0) + (unmatched?.items?.length ?? 0)
            : tab === "company" ? (companyRules?.length ?? 0) + (unmatched?.items?.length ?? 0)
            : tab === "departure" ? (departureRules?.length ?? 0) + (unmatched?.items?.length ?? 0)
            : tab === "duration" ? (durationRules?.length ?? 0) + (unmatched?.items?.length ?? 0)
            : (durationRules?.length ?? 0)
        }
        filtered={
          tab === "market" ? filteredMarket.length + filteredUnmatched.length
            : tab === "route" ? filteredRoute.length + filteredUnmatched.length
            : tab === "company" ? filteredCompany.length + filteredUnmatched.length
            : tab === "departure" ? filteredDeparture.length + filteredUnmatched.length
            : tab === "duration" ? filteredDuration.length + filteredUnmatched.length
            : filteredDuration.length
        }
      />

      {tab === "market" && (
        <div className="space-y-4">
          <div className="card p-4 flex flex-wrap gap-2 items-end">
            <div><label className="text-xs text-gray-500">Thị trường</label>
              <input className="input text-sm" value={mMarket} onChange={(e) => setMMarket(e.target.value)} placeholder="Thái Lan" /></div>
            <div className="flex-1 min-w-[200px]"><label className="text-xs text-gray-500">Keyword</label>
              <input className="input text-sm" value={mKeyword} onChange={(e) => setMKeyword(e.target.value)} placeholder="bangkok, pattaya..." /></div>
            <button onClick={() => addMarket.mutate()} disabled={!mMarket || !mKeyword} className="btn-primary text-sm"><Plus size={14} /> Thêm</button>
            <button
              type="button"
              onClick={() => seedMarketDefaults().then(() => afterRuleSaved("Đã import quy tắc mặc định")).catch(showErr)}
              className="btn-secondary text-sm"
            >
              <Database size={14} /> Import mặc định
            </button>
          </div>
          <div className="card overflow-auto max-h-[560px]">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0 z-10"><tr>
                <th className="px-3 py-2 text-left">Thị trường <span className="text-[10px] font-normal text-gray-400">(thả keyword vào đây)</span></th>
                <th className="px-3 py-2 text-left">Keyword</th><th className="w-20"></th>
              </tr></thead>
              <tbody>
                {filteredMarket.map((r: MarketRule) => {
                  const dropKey = `mkt-${r.market}`;
                  const { dropClassName, ...drop } = dropHandlers(dropKey, dropTarget, setDropTarget, (kw) => assignMarketKeyword(r.market, kw));
                  return (
                  <tr key={r.id} className={cn("border-t", editingId === r.id && "bg-blue-50")}>
                    <td className={cn("px-3 py-2", dropClassName)} {...drop}>
                      {editingId === r.id ? (
                        <input className="input text-sm py-1" value={editDraft.market ?? ""} onChange={(e) => setEditDraft({ ...editDraft, market: e.target.value })} />
                      ) : (
                        <span className="flex items-center gap-1">{r.market}
                          <button type="button" className="text-gray-400 hover:text-primary-600" onClick={() => startEdit(r.id, { market: r.market, keyword: r.keyword })}><Pencil size={12} /></button>
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {editingId === r.id ? (
                        <input className="input text-sm py-1 font-mono" value={editDraft.keyword ?? ""} onChange={(e) => setEditDraft({ ...editDraft, keyword: e.target.value })} />
                      ) : r.keyword}
                    </td>
                    {actionBtns(
                      () => deleteMarketRule(r.id).then(() => afterRuleSaved("Đã xóa quy tắc")),
                      editingId === r.id ? () => updateMarketRule(r.id, { market: editDraft.market, keyword: editDraft.keyword }).then(() => { cancelEdit(); afterRuleSaved("Đã cập nhật"); }).catch(showErr) : undefined,
                    )}
                  </tr>
                  );
                })}
                <UnmatchedMarketRows items={filteredUnmatched} onAssign={assignMarketKeyword} />
              </tbody>
            </table>
            <datalist id="market-suggestions">{marketOptions.map((m) => <option key={m} value={m} />)}</datalist>
            <p className="text-xs text-gray-400 p-3">{filteredMarket.length} rules · {filteredUnmatched.length} tour chưa khớp</p>
          </div>
        </div>
      )}

      {tab === "route" && (
        <div className="space-y-4">
          <div className="card p-4 space-y-2">
            <div className="grid grid-cols-3 gap-2">
              <input className="input text-sm" placeholder="Thị trường" value={rMarket} onChange={(e) => setRMarket(e.target.value)} />
              <input className="input text-sm" placeholder="Tuyến tour" value={rRoute} onChange={(e) => setRRoute(e.target.value)} />
              <input className="input text-sm" placeholder="Keywords (dấu phẩy, AND)" value={rKeywords} onChange={(e) => setRKeywords(e.target.value)} />
            </div>
            <button onClick={() => addRoute.mutate()} disabled={!rMarket || !rRoute || !rKeywords} className="btn-primary text-sm"><Plus size={14} /> Thêm rule</button>
            <button
              type="button"
              onClick={() => seedRouteDefaults().then((r) => afterRuleSaved(r.message || "Đã nạp quy tắc tuyến")).catch(showErr)}
              className="btn-secondary text-sm"
            >
              <Database size={14} /> Import mặc định
            </button>
          </div>
          {(routeRules?.length ?? 0) === 0 && (
            <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              Chưa có quy tắc tuyến trong Supabase. Bấm <strong>Import mặc định</strong> hoặc thêm thủ công — quy tắc chỉ lưu trong database, không đồng bộ Sheet.
            </p>
          )}
          <div className="card overflow-auto max-h-[560px]">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0 z-10"><tr>
                <th className="px-3 py-2 text-left">Thị trường</th>
                <th className="px-3 py-2 text-left">Tuyến <span className="text-[10px] font-normal text-gray-400">(thả keyword)</span></th>
                <th className="px-3 py-2 text-left">Keywords</th><th className="w-20"></th>
              </tr></thead>
              <tbody>
                {filteredRoute.length === 0 && filteredUnmatched.length === 0 && (
                  <tr><td colSpan={4} className="px-3 py-8 text-center text-gray-400 text-sm">Không có dòng nào</td></tr>
                )}
                {filteredRoute.map((r: RouteRule) => {
                  const dropKey = `route-${r.thi_truong}-${r.tuyen_tour}`;
                  const { dropClassName, ...drop } = dropHandlers(dropKey, dropTarget, setDropTarget, (kw) => assignRouteKeyword(r.thi_truong, r.tuyen_tour, kw));
                  return (
                  <tr key={r.id} className={cn("border-t", editingId === r.id && "bg-blue-50")}>
                    <td className="px-3 py-2">
                      {editingId === r.id ? <input className="input text-sm py-1" value={editDraft.thi_truong ?? ""} onChange={(e) => setEditDraft({ ...editDraft, thi_truong: e.target.value })} /> : (
                        <span className="flex items-center gap-1">{r.thi_truong}<button type="button" className="text-gray-400 hover:text-primary-600" onClick={() => startEdit(r.id, { thi_truong: r.thi_truong, tuyen_tour: r.tuyen_tour, keywords: r.keywords })}><Pencil size={12} /></button></span>
                      )}
                    </td>
                    <td className={cn("px-3 py-2", dropClassName)} {...drop}>{editingId === r.id ? <input className="input text-sm py-1" value={editDraft.tuyen_tour ?? ""} onChange={(e) => setEditDraft({ ...editDraft, tuyen_tour: e.target.value })} /> : r.tuyen_tour}</td>
                    <td className="px-3 py-2 font-mono text-xs">{editingId === r.id ? <input className="input text-sm py-1 font-mono" value={editDraft.keywords ?? ""} onChange={(e) => setEditDraft({ ...editDraft, keywords: e.target.value })} /> : r.keywords}</td>
                    {actionBtns(
                      () => deleteRouteRule(r.id).then(() => afterRuleSaved("Đã xóa quy tắc")),
                      editingId === r.id ? () => updateRouteRule(r.id, { thi_truong: editDraft.thi_truong, tuyen_tour: editDraft.tuyen_tour, keywords: editDraft.keywords }).then(() => { cancelEdit(); afterRuleSaved("Đã cập nhật"); }).catch(showErr) : undefined,
                    )}
                  </tr>
                  );
                })}
                <UnmatchedRouteRows items={filteredUnmatched} onAssign={assignRouteKeyword} />
              </tbody>
            </table>
            <datalist id="route-market-suggestions">{routeMarketOptions.map((m) => <option key={m} value={m} />)}</datalist>
            <p className="text-xs text-gray-400 p-3">{filteredRoute.length} rules · {filteredUnmatched.length} tour chưa khớp tuyến</p>
          </div>
        </div>
      )}

      {tab === "company" && (
        <div className="space-y-4">
          <div className="card p-4 flex flex-wrap gap-2 items-end">
            <div><label className="text-xs text-gray-500">Tên chính thức</label>
              <input className="input text-sm" value={cCanonical} onChange={(e) => setCCanonical(e.target.value)} placeholder="Vietravel" /></div>
            <div className="flex-1 min-w-[200px]"><label className="text-xs text-gray-500">Alias</label>
              <input className="input text-sm" value={cAlias} onChange={(e) => setCAlias(e.target.value)} placeholder="vietravel, vtr..."
                onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); setCAlias(e.dataTransfer.getData("text/plain")); }} /></div>
            <button onClick={() => addCompany.mutate()} disabled={!cCanonical || !cAlias} className="btn-primary text-sm"><Plus size={14} /> Thêm</button>
            <button onClick={() => seedCompanyDefaults().then(() => afterRuleSaved("Đã import alias mặc định"))} className="btn-secondary text-sm"><Database size={14} /> Alias mặc định</button>
          </div>
          <AliasTable
            rows={filteredCompany}
            unmatched={filteredUnmatched}
            canonicalOptions={canonicalOptions}
            editingId={editingId}
            editDraft={editDraft}
            dropTarget={dropTarget}
            setDropTarget={setDropTarget}
            onDropAssign={(canonical, alias) => assignCompanyAlias(canonical, alias)}
            onStartEdit={(r) => startEdit(r.id, { canonical_name: r.canonical_name, alias: r.alias })}
            onDraftChange={setEditDraft}
            onCancel={cancelEdit}
            onSave={(r) => updateCompanyRule(r.id, { canonical_name: editDraft.canonical_name, alias: editDraft.alias }).then(() => { cancelEdit(); afterRuleSaved("Đã cập nhật alias công ty"); })}
            onDelete={(r) => deleteCompanyRule(r.id).then(() => afterRuleSaved("Đã xóa alias"))}
            canonicalLabel="Tên chính thức"
          />
        </div>
      )}

      {tab === "departure" && (
        <div className="space-y-4">
          <div className="card p-4 flex flex-wrap gap-2 items-end">
            <div><label className="text-xs text-gray-500">Tên chính thức</label>
              <input className="input text-sm" value={dCanonical} onChange={(e) => setDCanonical(e.target.value)} placeholder="TP.HCM" /></div>
            <div className="flex-1 min-w-[200px]"><label className="text-xs text-gray-500">Alias</label>
              <input className="input text-sm" value={dAlias} onChange={(e) => setDAlias(e.target.value)} placeholder="sài gòn, hcm..."
                onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); setDAlias(e.dataTransfer.getData("text/plain")); }} /></div>
            <button onClick={() => addDeparture.mutate()} disabled={!dCanonical || !dAlias} className="btn-primary text-sm"><Plus size={14} /> Thêm</button>
            <button onClick={() => seedDepartureDefaults().then(() => afterRuleSaved("Đã import alias mặc định"))} className="btn-secondary text-sm"><Database size={14} /> Alias mặc định</button>
          </div>
          <p className="text-xs text-gray-500 inline-flex items-center gap-1">
            Chuẩn hóa {COL.diemKhoiHanh}.
            <InfoTip text="Sài Gòn / HCM / TPHCM → TP.HCM. Bấm bút chì để sửa từng dòng." />
          </p>
          <AliasTable
            rows={filteredDeparture}
            unmatched={filteredUnmatched}
            canonicalOptions={canonicalOptions}
            editingId={editingId}
            editDraft={editDraft}
            dropTarget={dropTarget}
            setDropTarget={setDropTarget}
            onDropAssign={(canonical, alias) => assignDepartureAlias(canonical, alias)}
            onStartEdit={(r) => startEdit(r.id, { canonical_name: r.canonical_name, alias: r.alias })}
            onDraftChange={setEditDraft}
            onCancel={cancelEdit}
            onSave={(r) => updateDepartureRule(r.id, { canonical_name: editDraft.canonical_name, alias: editDraft.alias }).then(() => { cancelEdit(); afterRuleSaved("Đã cập nhật alias điểm KH"); })}
            onDelete={(r) => deleteDepartureRule(r.id).then(() => afterRuleSaved("Đã xóa alias"))}
            canonicalLabel="Tên chính thức"
          />
        </div>
      )}

      {tab === "duration" && (
        <div className="space-y-4">
          <div className="card p-4 flex flex-wrap gap-2 items-end">
            <div><label className="text-xs text-gray-500">Chuẩn (NĐ)</label>
              <input className="input text-sm w-28" value={durDays} onChange={(e) => setDurDays(e.target.value)} placeholder="5N4Đ" />
              {parsedDurDays != null && durDays.trim() && (
                <span className="text-[10px] text-gray-500 block mt-0.5">= {parsedDurDays} ngày</span>
              )}
            </div>
            <div className="flex-1 min-w-[200px]"><label className="text-xs text-gray-500">Alias (text gốc)</label>
              <input className="input text-sm" value={durAlias} onChange={(e) => setDurAlias(e.target.value)} placeholder="5n4d, 5 ngày 4 đêm..."
                onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); setDurAlias(e.dataTransfer.getData("text/plain")); }} /></div>
            <button onClick={() => addDuration.mutate()} disabled={parsedDurDays == null || !durAlias} className="btn-primary text-sm"><Plus size={14} /> Thêm</button>
            <button onClick={() => seedDurationDefaults().then(() => afterRuleSaved("Đã import alias mặc định"))} className="btn-secondary text-sm"><Database size={14} /> Alias mặc định</button>
          </div>
          <p className="text-xs text-gray-500 inline-flex items-center gap-1">
            Key matching {COL.thoiGian} — chuẩn dạng <strong>NĐ</strong>: 5N4Đ→5, 5N5Đ→5.5, 1N→1, 0.5N→0.5 (1 buổi).
            <InfoTip text="Alias khớp không phân biệt hoa thường. Giá trị số lưu trong DB; nhãn NĐ chỉ để hiển thị." />
          </p>
          <div className="card overflow-auto max-h-[500px]">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0"><tr>
                <th className="px-3 py-2 text-left">Chuẩn (NĐ) <span className="text-[10px] font-normal text-gray-400">(thả alias vào đây)</span></th><th className="px-3 py-2 text-left">Alias</th><th className="w-24"></th>
              </tr></thead>
              <tbody>
                {filteredDuration.map((r: DurationRule) => {
                  const key = `dur-${r.canonical_days}`;
                  const { dropClassName, ...drop } = dropHandlers(key, dropTarget, setDropTarget, (alias) => assignDurationAlias(r.canonical_days, alias));
                  return (
                  <tr key={r.id} className={cn("border-t", editingId === r.id && "bg-blue-50")}>
                    <td className={cn("px-3 py-2 font-medium", dropClassName)} {...drop}>
                      {editingId === r.id ? (
                        <input className="input text-sm py-1 w-24" value={editDraft.canonical_label ?? formatDurationLabel(r.canonical_days)} onChange={(e) => setEditDraft({ ...editDraft, canonical_label: e.target.value })} />
                      ) : (
                        <span className="flex items-center gap-1">{formatDurationLabel(r.canonical_days)}
                          <span className="text-[10px] text-gray-400">({r.canonical_days})</span>
                          <button type="button" className="text-gray-400 hover:text-primary-600" onClick={() => startEdit(r.id, { canonical_label: formatDurationLabel(r.canonical_days), alias: r.alias })}><Pencil size={12} /></button>
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {editingId === r.id ? (
                        <input className="input text-sm py-1 font-mono" value={editDraft.alias ?? ""} onChange={(e) => setEditDraft({ ...editDraft, alias: e.target.value })} />
                      ) : r.alias}
                    </td>
                    <td className="px-3 py-2">
                      {editingId === r.id ? (
                        <span className="flex gap-1">
                          <button type="button" className="text-green-600" onClick={() => {
                            const days = parseDurationInput(editDraft.canonical_label ?? "");
                            if (days == null) { setSyncMsg("Chuẩn NĐ không hợp lệ (VD: 5N4Đ, 0.5N)"); return; }
                            updateDurationRule(r.id, { canonical_days: days, alias: editDraft.alias }).then(() => { afterRuleSaved("Đã cập nhật alias thời gian"); cancelEdit(); }).catch(showErr);
                          }}><Check size={14} /></button>
                          <button type="button" className="text-gray-400" onClick={cancelEdit}><X size={14} /></button>
                        </span>
                      ) : (
                        <button type="button" className="text-red-500" onClick={() => deleteDurationRule(r.id).then(() => { invalidate(); setSyncMsg("Đã xóa alias"); })}><Trash2 size={14} /></button>
                      )}
                    </td>
                  </tr>
                  );
                })}
                {filteredUnmatched.length > 0 && (
                  <>
                    <tr className="bg-amber-100 border-t-2 border-amber-400">
                      <td colSpan={3} className="px-3 py-2 text-xs font-semibold text-amber-900">
                        <span className="inline-flex items-center gap-1">
                          <GripVertical size={12} /> Chưa khớp ({filteredUnmatched.length}) — kéo Alias lên dòng Số ngày phía trên, hoặc nhập ngày rồi bấm Gán
                          <InfoTip text="Giá trị thời gian raw từ tour chưa có trong bảng alias." />
                        </span>
                      </td>
                    </tr>
                    {filteredUnmatched.map((item) => (
                      <UnmatchedDurationRow
                        key={item.value}
                        item={item}
                        onAssign={(days, alias) => assignDurationAlias(days, alias)}
                      />
                    ))}
                  </>
                )}
              </tbody>
            </table>
            <p className="text-xs text-gray-400 p-3">{filteredDuration.length} rules · {filteredUnmatched.length} chưa khớp</p>
          </div>
        </div>
      )}
    </div>
  );
}

function UnmatchedMarketRows({
  items,
  onAssign,
}: {
  items: UnmatchedItem[];
  onAssign: (market: string, keyword: string) => void | Promise<void>;
}) {
  const [pending, setPending] = useState<Record<string, string>>({});
  const [keywords, setKeywords] = useState<Record<string, string>>({});
  if (!items.length) return null;
  return (
    <>
      <tr className="bg-amber-100 border-t-2 border-amber-400">
        <td colSpan={3} className="px-3 py-2 text-xs font-semibold text-amber-900">
          <span className="inline-flex items-center gap-1">
            <GripVertical size={12} /> Chưa khớp thị trường ({items.length}) — kéo tên tour lên dòng Thị trường, hoặc nhập keyword rồi Gán
            <InfoTip text="Tour phân loại «Khác» vì chưa có keyword trong tên/lịch trình." />
          </span>
        </td>
      </tr>
      {items.map((item) => (
        <tr key={item.value} className="bg-amber-50/70 border-t border-amber-200">
          <td className="px-3 py-2">
            <input
              className="input text-xs py-1 w-full border-amber-300 bg-white"
              placeholder="Thị trường..."
              list="market-suggestions"
              value={pending[item.value] ?? ""}
              onChange={(e) => setPending({ ...pending, [item.value]: e.target.value })}
            />
          </td>
          <td className="px-3 py-2 font-mono text-xs text-amber-950 space-y-1">
            <input
              className="input text-xs py-1 w-full border-amber-200 bg-white font-mono"
              placeholder="keyword (vd: bangkok)..."
              value={keywords[item.value] ?? ""}
              onChange={(e) => setKeywords({ ...keywords, [item.value]: e.target.value })}
            />
            <span {...dragAliasProps(item.value)} title={`${item.count} tour · kéo lên Thị trường phía trên`} className="block truncate max-w-md">
              <GripVertical size={10} className="text-amber-600 shrink-0 inline" />
              {item.value}
              <span className="text-gray-500 ml-1">({item.count})</span>
            </span>
          </td>
          <td className="px-3 py-2">
            <button
              type="button"
              className="btn-primary text-[10px] py-1 px-2"
              disabled={!(pending[item.value] ?? "").trim() || !((keywords[item.value] ?? "").trim() || item.value)}
              onClick={async () => {
                const market = (pending[item.value] ?? "").trim();
                const kw = (keywords[item.value] ?? "").trim() || item.value;
                if (!market) return;
                await onAssign(market, kw);
                setPending((p) => { const n = { ...p }; delete n[item.value]; return n; });
                setKeywords((k) => { const n = { ...k }; delete n[item.value]; return n; });
              }}
            >
              Gán
            </button>
          </td>
        </tr>
      ))}
    </>
  );
}

function UnmatchedRouteRows({
  items,
  onAssign,
}: {
  items: UnmatchedItem[];
  onAssign: (thiTruong: string, tuyenTour: string, keyword: string) => void | Promise<void>;
}) {
  const [pendingMarket, setPendingMarket] = useState<Record<string, string>>({});
  const [pendingRoute, setPendingRoute] = useState<Record<string, string>>({});
  const [keywords, setKeywords] = useState<Record<string, string>>({});
  if (!items.length) return null;
  return (
    <>
      <tr className="bg-amber-100 border-t-2 border-amber-400">
        <td colSpan={4} className="px-3 py-2 text-xs font-semibold text-amber-900">
          <span className="inline-flex items-center gap-1">
            <GripVertical size={12} /> Chưa khớp tuyến ({items.length}) — kéo keyword lên cột Tuyến, hoặc nhập tuyến + keyword rồi Gán
            <InfoTip text="Đã có thị trường nhưng tuyến vẫn = tên thị trường (chưa match rule tuyến)." />
          </span>
        </td>
      </tr>
      {items.map((item) => (
        <tr key={item.value} className="bg-amber-50/70 border-t border-amber-200">
          <td className="px-3 py-2">
            <input
              className="input text-xs py-1 w-full border-amber-300 bg-white"
              placeholder="Thị trường"
              list="route-market-suggestions"
              value={pendingMarket[item.value] ?? item.thi_truong ?? ""}
              onChange={(e) => setPendingMarket({ ...pendingMarket, [item.value]: e.target.value })}
            />
          </td>
          <td className="px-3 py-2">
            <input
              className="input text-xs py-1 w-full border-amber-300 bg-white"
              placeholder="Tuyến tour..."
              value={pendingRoute[item.value] ?? ""}
              onChange={(e) => setPendingRoute({ ...pendingRoute, [item.value]: e.target.value })}
            />
          </td>
          <td className="px-3 py-2 font-mono text-xs text-amber-950 space-y-1">
            <input
              className="input text-xs py-1 w-full border-amber-200 bg-white font-mono"
              placeholder="keyword..."
              value={keywords[item.value] ?? ""}
              onChange={(e) => setKeywords({ ...keywords, [item.value]: e.target.value })}
            />
            <span {...dragAliasProps(item.value)} title={`${item.count} tour`} className="block truncate max-w-xs">
              <GripVertical size={10} className="text-amber-600 shrink-0 inline" />
              {item.value}
              <span className="text-gray-500 ml-1">({item.count})</span>
            </span>
          </td>
          <td className="px-3 py-2">
            <button
              type="button"
              className="btn-primary text-[10px] py-1 px-2"
              disabled={
                !(pendingMarket[item.value] ?? item.thi_truong ?? "").trim()
                || !(pendingRoute[item.value] ?? "").trim()
                || !((keywords[item.value] ?? "").trim())
              }
              onClick={async () => {
                const mk = (pendingMarket[item.value] ?? item.thi_truong ?? "").trim();
                const route = (pendingRoute[item.value] ?? "").trim();
                const kw = (keywords[item.value] ?? "").trim();
                if (!mk || !route || !kw) return;
                await onAssign(mk, route, kw);
                setPendingRoute((p) => { const n = { ...p }; delete n[item.value]; return n; });
                setKeywords((k) => { const n = { ...k }; delete n[item.value]; return n; });
              }}
            >
              Gán
            </button>
          </td>
        </tr>
      ))}
    </>
  );
}

function AliasTable({
  rows, unmatched, canonicalOptions, editingId, editDraft, dropTarget, setDropTarget, onDropAssign,
  onStartEdit, onDraftChange, onCancel, onSave, onDelete, canonicalLabel,
}: {
  rows: Array<CompanyRule | DepartureRule>;
  unmatched: UnmatchedItem[];
  canonicalOptions: string[];
  editingId: number | null;
  editDraft: Record<string, string>;
  dropTarget: string | null;
  setDropTarget: (k: string | null) => void;
  onDropAssign: (canonical: string, alias: string) => void | Promise<void>;
  onStartEdit: (r: CompanyRule | DepartureRule) => void;
  onDraftChange: (d: Record<string, string>) => void;
  onCancel: () => void;
  onSave: (r: CompanyRule | DepartureRule) => void;
  onDelete: (r: CompanyRule | DepartureRule) => void;
  canonicalLabel: string;
}) {
  const [pending, setPending] = useState<Record<string, string>>({});

  return (
    <div className="card overflow-auto max-h-[560px]">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 sticky top-0 z-10"><tr>
          <th className="px-3 py-2 text-left">{canonicalLabel} <span className="text-[10px] font-normal text-gray-400">(thả alias vào đây)</span></th>
          <th className="px-3 py-2 text-left">Alias</th>
          <th className="w-24"></th>
        </tr></thead>
        <tbody>
          {rows.map((r) => {
            const key = `alias-${r.canonical_name}`;
            const { dropClassName, ...drop } = dropHandlers(key, dropTarget, setDropTarget, (alias) => onDropAssign(r.canonical_name, alias));
            return (
            <tr key={r.id} className={cn("border-t", editingId === r.id && "bg-blue-50")}>
              <td className={cn("px-3 py-2 font-medium", dropClassName)} {...drop}>
                {editingId === r.id ? (
                  <input className="input text-sm py-1" value={editDraft.canonical_name ?? ""} onChange={(e) => onDraftChange({ ...editDraft, canonical_name: e.target.value })} />
                ) : (
                  <span className="flex items-center gap-1">{r.canonical_name}
                    <button type="button" className="text-gray-400 hover:text-primary-600" onClick={() => onStartEdit(r)}><Pencil size={12} /></button>
                  </span>
                )}
              </td>
              <td className="px-3 py-2 font-mono text-xs">
                {editingId === r.id ? (
                  <input className="input text-sm py-1 font-mono" value={editDraft.alias ?? ""} onChange={(e) => onDraftChange({ ...editDraft, alias: e.target.value })} />
                ) : r.alias}
              </td>
              <td className="px-3 py-2">
                {editingId === r.id ? (
                  <span className="flex gap-1">
                    <button type="button" className="text-green-600" onClick={() => onSave(r)}><Check size={14} /></button>
                    <button type="button" className="text-gray-400" onClick={onCancel}><X size={14} /></button>
                  </span>
                ) : (
                  <button type="button" className="text-red-500" onClick={() => onDelete(r)}><Trash2 size={14} /></button>
                )}
              </td>
            </tr>
            );
          })}

          {unmatched.length > 0 && (
            <>
              <tr className="bg-amber-100 border-t-2 border-amber-400">
                <td colSpan={3} className="px-3 py-2 text-xs font-semibold text-amber-900">
                  <span className="inline-flex items-center gap-1">
                    <GripVertical size={12} /> Chưa khớp ({unmatched.length}) — kéo cột Alias lên {canonicalLabel} phía trên, hoặc nhập tên chuẩn rồi bấm Gán
                  </span>
                </td>
              </tr>
              {unmatched.map((item) => (
                <tr key={item.value} className="bg-amber-50/70 border-t border-amber-200">
                  <td className="px-3 py-2">
                    <input
                      className="input text-xs py-1 w-full border-amber-300 bg-white"
                      placeholder={`${canonicalLabel}...`}
                      list="canonical-suggestions"
                      value={pending[item.value] ?? ""}
                      onChange={(e) => setPending({ ...pending, [item.value]: e.target.value })}
                    />
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-amber-950">
                    <span {...dragAliasProps(item.value)} title={`${item.count} tour · kéo lên dòng phía trên`}>
                      <GripVertical size={10} className="text-amber-600 shrink-0" />
                      {item.value || "—"}
                      <span className="text-gray-500 ml-1">({item.count})</span>
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      className="btn-primary text-[10px] py-1 px-2"
                      disabled={!(pending[item.value] ?? "").trim()}
                      onClick={async () => {
                        const c = (pending[item.value] ?? "").trim();
                        if (!c) return;
                        await onDropAssign(c, item.value);
                        setPending((p) => { const n = { ...p }; delete n[item.value]; return n; });
                      }}
                    >
                      Gán
                    </button>
                  </td>
                </tr>
              ))}
            </>
          )}
        </tbody>
      </table>
      <datalist id="canonical-suggestions">
        {canonicalOptions.map((c) => <option key={c} value={c} />)}
      </datalist>
      <p className="text-xs text-gray-400 p-3">{rows.length} rules · {unmatched.length} chưa khớp</p>
    </div>
  );
}

function UnmatchedDurationRow({ item, onAssign }: { item: UnmatchedItem; onAssign: (days: number, alias: string) => void }) {
  const [days, setDays] = useState("");
  return (
    <tr className="bg-amber-50/70 border-t border-amber-200">
      <td className="px-3 py-2">
        <input className="input text-xs py-1 w-20 border-amber-300 bg-white" type="number" min={1} max={45} placeholder="5N" value={days} onChange={(e) => setDays(e.target.value)} />
      </td>
      <td className="px-3 py-2 font-mono text-xs text-amber-950">
        <span {...dragAliasProps(item.value)} title={`${item.count} tour`}>
          <GripVertical size={10} className="text-amber-600 shrink-0" />
          {item.value || "—"}
          <span className="text-gray-500 ml-1">({item.count})</span>
        </span>
      </td>
      <td className="px-3 py-2">
        <button
          type="button"
          className="btn-primary text-[10px] py-1 px-2"
          disabled={!days || Number.isNaN(parseFloat(days))}
          onClick={() => onAssign(parseFloat(days), item.value)}
        >
          Gán
        </button>
      </td>
    </tr>
  );
}
