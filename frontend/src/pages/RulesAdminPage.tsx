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
  applyCompanyRulesToTours, applyDepartureRulesToTours, applyDurationRulesToTours,
  applyClassificationToTours,
  syncRouteFromSheet, syncRouteToSheet,
  syncMarketFromSheet, syncMarketToSheet,
  syncAllFromSheet, syncAllToSheet,
  getRulesUnmatched,
  MarketRule, RouteRule, CompanyRule, DepartureRule, DurationRule, UnmatchedItem,
} from "@/lib/api";
import { COL } from "@/lib/glossary";
import { InfoTip } from "@/components/InfoTip";
import { cn } from "@/lib/utils";
import { Plus, Trash2, RefreshCw, Database, Upload, Download, ArrowLeftRight, Search, Pencil, Check, X, GripVertical } from "lucide-react";

type Tab = "market" | "route" | "company" | "departure" | "duration";
type AliasTab = "company" | "departure" | "duration";

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

function UnmatchedDropTray({ items, search }: { items: UnmatchedItem[]; search: string }) {
  const filtered = useMemo(
    () => (items ?? []).filter((x) => matchSearch(search, x.value, x.count)),
    [items, search],
  );
  if (!filtered.length) {
    return (
      <div className="card p-4 border border-dashed border-gray-200 bg-gray-50 text-xs text-gray-500 text-center">
        Không còn giá trị chưa khớp trong dữ liệu tour (hoặc bị lọc bởi ô tìm kiếm).
      </div>
    );
  }
  return (
    <div className="card p-4 border-2 border-dashed border-amber-400 bg-amber-50/60 space-y-2">
      <p className="text-sm font-semibold text-amber-900 inline-flex items-center gap-1">
        <GripVertical size={14} /> Chưa khớp ({filtered.length}) — kéo thả lên cột &quot;Tên chính thức&quot; / &quot;Số ngày&quot;
        <InfoTip text="Các giá trị raw từ tour chưa map alias. Kéo chip và thả vào dòng tên chuẩn để tạo rule mới." />
      </p>
      <div className="flex flex-wrap gap-2 max-h-44 overflow-auto p-1">
        {filtered.map((item) => (
          <span
            key={item.value}
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData("text/plain", item.value);
              e.dataTransfer.effectAllowed = "copy";
            }}
            className="cursor-grab active:cursor-grabbing inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white border border-amber-300 text-xs shadow-sm hover:border-primary-500 hover:bg-blue-50"
            title={`${item.count} tour · kéo thả để gán`}
          >
            <GripVertical size={10} className="text-amber-600 shrink-0" />
            <span className="max-w-[200px] truncate">{item.value || "—"}</span>
            <span className="text-gray-400 shrink-0">({item.count})</span>
          </span>
        ))}
      </div>
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

export default function RulesAdminPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [tab, setTab] = useState<Tab>("market");
  const [search, setSearch] = useState("");
  const [syncMsg, setSyncMsg] = useState("");
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

  const aliasTab: AliasTab | null = tab === "company" || tab === "departure" || tab === "duration" ? tab : null;

  const { data: marketRules } = useQuery({ queryKey: ["market-rules"], queryFn: listMarketRules, enabled: isAdmin });
  const { data: routeRules } = useQuery({ queryKey: ["route-rules"], queryFn: listRouteRules, enabled: isAdmin });
  const { data: companyRules } = useQuery({ queryKey: ["company-rules"], queryFn: listCompanyRules, enabled: isAdmin });
  const { data: departureRules } = useQuery({ queryKey: ["departure-rules"], queryFn: listDepartureRules, enabled: isAdmin });
  const { data: durationRules } = useQuery({ queryKey: ["duration-rules"], queryFn: listDurationRules, enabled: isAdmin });
  const { data: unmatched } = useQuery({
    queryKey: ["rules-unmatched", aliasTab],
    queryFn: () => getRulesUnmatched(aliasTab!),
    enabled: isAdmin && !!aliasTab,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["market-rules"] });
    qc.invalidateQueries({ queryKey: ["route-rules"] });
    qc.invalidateQueries({ queryKey: ["company-rules"] });
    qc.invalidateQueries({ queryKey: ["departure-rules"] });
    qc.invalidateQueries({ queryKey: ["duration-rules"] });
    qc.invalidateQueries({ queryKey: ["rules-unmatched"] });
    qc.invalidateQueries({ queryKey: ["compare-class-gaps"] });
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

  const onSync = (fn: () => Promise<{ message?: string }>, label: string) =>
    fn().then((r) => { setSyncMsg(r.message || label); invalidate(); }).catch((e) => setSyncMsg(String(e.response?.data?.detail || e.message)));

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
    () => (durationRules ?? []).filter((r) => matchSearch(search, r.canonical_days, r.alias, `${r.canonical_days}N`)),
    [durationRules, search],
  );

  const addMarket = useMutation({
    mutationFn: () => createMarketRule({ market: mMarket, keyword: mKeyword }),
    onSuccess: () => { invalidate(); setMKeyword(""); setSyncMsg("Đã lưu DB và tự động ghi lên Sheet (nếu có quyền)"); },
  });
  const addRoute = useMutation({
    mutationFn: () => createRouteRule({ thi_truong: rMarket, tuyen_tour: rRoute, keywords: rKeywords }),
    onSuccess: () => { invalidate(); setRKeywords(""); setSyncMsg("Đã lưu DB và tự động ghi lên Sheet 'Điểm tuyến Tour'"); },
  });
  const addCompany = useMutation({
    mutationFn: () => createCompanyRule({ canonical_name: cCanonical, alias: cAlias }),
    onSuccess: () => { invalidate(); setCAlias(""); setSyncMsg("Đã thêm alias công ty"); },
  });
  const addDeparture = useMutation({
    mutationFn: () => createDepartureRule({ canonical_name: dCanonical, alias: dAlias }),
    onSuccess: () => { invalidate(); setDAlias(""); setSyncMsg("Đã thêm alias điểm khởi hành"); },
  });
  const addDuration = useMutation({
    mutationFn: () => createDurationRule({ canonical_days: parseFloat(durDays), alias: durAlias }),
    onSuccess: () => { invalidate(); setDurAlias(""); setSyncMsg("Đã thêm alias thời gian"); },
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
        <p className="text-sm text-gray-500">Bảng alias trong DB — tìm kiếm, sửa inline, thêm/xóa. Thời gian dùng cùng cơ chế với Công ty & Điểm KH.</p>
      </div>

      <div className="card p-4 space-y-3 bg-slate-50">
        <p className="text-sm font-medium flex items-center gap-2"><ArrowLeftRight size={16} /> Đồng bộ Google Sheet</p>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => onSync(syncAllFromSheet, "OK")} className="btn-secondary text-xs flex items-center gap-1">
            <Download size={13} /> Kéo tất cả Sheet → App
          </button>
          <button onClick={() => onSync(syncAllToSheet, "OK")} className="btn-secondary text-xs flex items-center gap-1">
            <Upload size={13} /> Đẩy tất cả App → Sheet
          </button>
          <button onClick={() => onSync(applyClassificationToTours, "Đã áp dụng phân loại lên toàn bộ tour")} className="btn-primary text-xs flex items-center gap-1">
            <RefreshCw size={13} /> Áp dụng phân loại → tour
          </button>
        </div>
        {syncMsg && <p className="text-xs text-green-700 bg-green-50 px-3 py-2 rounded">{syncMsg}</p>}
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
          tab === "market" ? (marketRules?.length ?? 0)
            : tab === "route" ? (routeRules?.length ?? 0)
            : tab === "company" ? (companyRules?.length ?? 0)
            : tab === "departure" ? (departureRules?.length ?? 0)
            : (durationRules?.length ?? 0)
        }
        filtered={
          tab === "market" ? filteredMarket.length
            : tab === "route" ? filteredRoute.length
            : tab === "company" ? filteredCompany.length
            : tab === "departure" ? filteredDeparture.length
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
            <button onClick={() => onSync(seedMarketDefaults, "Import xong")} className="btn-secondary text-sm"><Database size={14} /> Import mặc định</button>
            <button onClick={() => onSync(syncMarketFromSheet, "OK")} className="btn-secondary text-sm"><Download size={14} /> Sheet → App</button>
          </div>
          <div className="card overflow-auto max-h-[500px]">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0"><tr>
                <th className="px-3 py-2 text-left">Thị trường</th><th className="px-3 py-2 text-left">Keyword</th><th className="w-20"></th>
              </tr></thead>
              <tbody>
                {filteredMarket.map((r: MarketRule) => (
                  <tr key={r.id} className={cn("border-t", editingId === r.id && "bg-blue-50")}>
                    <td className="px-3 py-2">
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
                      () => deleteMarketRule(r.id).then(() => { invalidate(); setSyncMsg("Đã xóa"); }),
                      editingId === r.id ? () => updateMarketRule(r.id, { market: editDraft.market, keyword: editDraft.keyword }).then(() => { invalidate(); cancelEdit(); setSyncMsg("Đã cập nhật"); }) : undefined,
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
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
          </div>
          <div className="card overflow-auto max-h-[500px]">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0"><tr>
                <th className="px-3 py-2 text-left">Thị trường</th><th className="px-3 py-2 text-left">Tuyến</th><th className="px-3 py-2 text-left">Keywords</th><th className="w-20"></th>
              </tr></thead>
              <tbody>
                {filteredRoute.map((r: RouteRule) => (
                  <tr key={r.id} className={cn("border-t", editingId === r.id && "bg-blue-50")}>
                    <td className="px-3 py-2">
                      {editingId === r.id ? <input className="input text-sm py-1" value={editDraft.thi_truong ?? ""} onChange={(e) => setEditDraft({ ...editDraft, thi_truong: e.target.value })} /> : (
                        <span className="flex items-center gap-1">{r.thi_truong}<button type="button" className="text-gray-400 hover:text-primary-600" onClick={() => startEdit(r.id, { thi_truong: r.thi_truong, tuyen_tour: r.tuyen_tour, keywords: r.keywords })}><Pencil size={12} /></button></span>
                      )}
                    </td>
                    <td className="px-3 py-2">{editingId === r.id ? <input className="input text-sm py-1" value={editDraft.tuyen_tour ?? ""} onChange={(e) => setEditDraft({ ...editDraft, tuyen_tour: e.target.value })} /> : r.tuyen_tour}</td>
                    <td className="px-3 py-2 font-mono text-xs">{editingId === r.id ? <input className="input text-sm py-1 font-mono" value={editDraft.keywords ?? ""} onChange={(e) => setEditDraft({ ...editDraft, keywords: e.target.value })} /> : r.keywords}</td>
                    {actionBtns(
                      () => deleteRouteRule(r.id).then(() => { invalidate(); setSyncMsg("Đã xóa"); }),
                      editingId === r.id ? () => updateRouteRule(r.id, { thi_truong: editDraft.thi_truong, tuyen_tour: editDraft.tuyen_tour, keywords: editDraft.keywords }).then(() => { invalidate(); cancelEdit(); setSyncMsg("Đã cập nhật"); }) : undefined,
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
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
            <button onClick={() => onSync(seedCompanyDefaults, "Import xong")} className="btn-secondary text-sm"><Database size={14} /> Alias mặc định</button>
            <button onClick={() => onSync(applyCompanyRulesToTours, "OK")} className="btn-secondary text-sm"><RefreshCw size={14} /> Áp dụng → tour</button>
          </div>
          <AliasTable
            rows={filteredCompany}
            editingId={editingId}
            editDraft={editDraft}
            dropTarget={dropTarget}
            setDropTarget={setDropTarget}
            onDropAssign={(canonical, alias) => assignCompanyAlias(canonical, alias)}
            onStartEdit={(r) => startEdit(r.id, { canonical_name: r.canonical_name, alias: r.alias })}
            onDraftChange={setEditDraft}
            onCancel={cancelEdit}
            onSave={(r) => updateCompanyRule(r.id, { canonical_name: editDraft.canonical_name, alias: editDraft.alias }).then(() => { invalidate(); cancelEdit(); setSyncMsg("Đã cập nhật alias công ty"); })}
            onDelete={(r) => deleteCompanyRule(r.id).then(() => { invalidate(); setSyncMsg("Đã xóa alias"); })}
            canonicalLabel="Tên chính thức"
          />
          <UnmatchedDropTray items={unmatched?.items ?? []} search={search} />
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
            <button onClick={() => onSync(seedDepartureDefaults, "Import xong")} className="btn-secondary text-sm"><Database size={14} /> Alias mặc định</button>
            <button onClick={() => onSync(applyDepartureRulesToTours, "OK")} className="btn-secondary text-sm"><RefreshCw size={14} /> Áp dụng → tour</button>
          </div>
          <p className="text-xs text-gray-500 inline-flex items-center gap-1">
            Chuẩn hóa {COL.diemKhoiHanh}.
            <InfoTip text="Sài Gòn / HCM / TPHCM → TP.HCM. Bấm bút chì để sửa từng dòng." />
          </p>
          <AliasTable
            rows={filteredDeparture}
            editingId={editingId}
            editDraft={editDraft}
            dropTarget={dropTarget}
            setDropTarget={setDropTarget}
            onDropAssign={(canonical, alias) => assignDepartureAlias(canonical, alias)}
            onStartEdit={(r) => startEdit(r.id, { canonical_name: r.canonical_name, alias: r.alias })}
            onDraftChange={setEditDraft}
            onCancel={cancelEdit}
            onSave={(r) => updateDepartureRule(r.id, { canonical_name: editDraft.canonical_name, alias: editDraft.alias }).then(() => { invalidate(); cancelEdit(); setSyncMsg("Đã cập nhật alias điểm KH"); })}
            onDelete={(r) => deleteDepartureRule(r.id).then(() => { invalidate(); setSyncMsg("Đã xóa alias"); })}
            canonicalLabel="Tên chính thức"
          />
          <UnmatchedDropTray items={unmatched?.items ?? []} search={search} />
        </div>
      )}

      {tab === "duration" && (
        <div className="space-y-4">
          <div className="card p-4 flex flex-wrap gap-2 items-end">
            <div><label className="text-xs text-gray-500">Số ngày chuẩn</label>
              <input className="input text-sm w-24" type="number" min={1} max={45} value={durDays} onChange={(e) => setDurDays(e.target.value)} placeholder="5" /></div>
            <div className="flex-1 min-w-[200px]"><label className="text-xs text-gray-500">Alias (text gốc)</label>
              <input className="input text-sm" value={durAlias} onChange={(e) => setDurAlias(e.target.value)} placeholder="5n4d, 5 ngày 4 đêm..."
                onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); setDurAlias(e.dataTransfer.getData("text/plain")); }} /></div>
            <button onClick={() => addDuration.mutate()} disabled={!durDays || !durAlias || Number.isNaN(parseFloat(durDays))} className="btn-primary text-sm"><Plus size={14} /> Thêm</button>
            <button onClick={() => onSync(seedDurationDefaults, "Import xong")} className="btn-secondary text-sm"><Database size={14} /> Alias mặc định</button>
            <button onClick={() => onSync(applyDurationRulesToTours, "OK")} className="btn-secondary text-sm"><RefreshCw size={14} /> Áp dụng → tour</button>
          </div>
          <p className="text-xs text-gray-500 inline-flex items-center gap-1">
            Key matching {COL.thoiGian} — lưu trong bảng <code className="text-[10px] bg-gray-100 px-1 rounded">duration_alias_rules</code>.
            <InfoTip text="Alias khớp không phân biệt hoa thường. VD alias '5n4d' → 5 ngày. Dùng khi gom nhóm so sánh VTR." />
          </p>
          <div className="card overflow-auto max-h-[500px]">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0"><tr>
                <th className="px-3 py-2 text-left">Số ngày chuẩn</th><th className="px-3 py-2 text-left">Alias</th><th className="w-24"></th>
              </tr></thead>
              <tbody>
                {filteredDuration.map((r: DurationRule) => {
                  const key = `dur-${r.canonical_days}`;
                  const { dropClassName, ...drop } = dropHandlers(key, dropTarget, setDropTarget, (alias) => assignDurationAlias(r.canonical_days, alias));
                  return (
                  <tr key={r.id} className={cn("border-t", editingId === r.id && "bg-blue-50")}>
                    <td className={cn("px-3 py-2 font-medium", dropClassName)} {...drop}>
                      {editingId === r.id ? (
                        <input className="input text-sm py-1 w-20" type="number" value={editDraft.canonical_days ?? ""} onChange={(e) => setEditDraft({ ...editDraft, canonical_days: e.target.value })} />
                      ) : (
                        <span className="flex items-center gap-1">{r.canonical_days}N
                          <button type="button" className="text-gray-400 hover:text-primary-600" onClick={() => startEdit(r.id, { canonical_days: String(r.canonical_days), alias: r.alias })}><Pencil size={12} /></button>
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
                          <button type="button" className="text-green-600" onClick={() => updateDurationRule(r.id, { canonical_days: parseFloat(editDraft.canonical_days), alias: editDraft.alias }).then(() => { invalidate(); cancelEdit(); setSyncMsg("Đã cập nhật alias thời gian"); })}><Check size={14} /></button>
                          <button type="button" className="text-gray-400" onClick={cancelEdit}><X size={14} /></button>
                        </span>
                      ) : (
                        <button type="button" className="text-red-500" onClick={() => deleteDurationRule(r.id).then(() => { invalidate(); setSyncMsg("Đã xóa alias"); })}><Trash2 size={14} /></button>
                      )}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="text-xs text-gray-400 p-3">{filteredDuration.length} rules (DB)</p>
          </div>
          <UnmatchedDropTray items={unmatched?.items ?? []} search={search} />
        </div>
      )}
    </div>
  );
}

function AliasTable({
  rows, editingId, editDraft, dropTarget, setDropTarget, onDropAssign,
  onStartEdit, onDraftChange, onCancel, onSave, onDelete, canonicalLabel,
}: {
  rows: Array<CompanyRule | DepartureRule>;
  editingId: number | null;
  editDraft: Record<string, string>;
  dropTarget: string | null;
  setDropTarget: (k: string | null) => void;
  onDropAssign: (canonical: string, alias: string) => void;
  onStartEdit: (r: CompanyRule | DepartureRule) => void;
  onDraftChange: (d: Record<string, string>) => void;
  onCancel: () => void;
  onSave: (r: CompanyRule | DepartureRule) => void;
  onDelete: (r: CompanyRule | DepartureRule) => void;
  canonicalLabel: string;
}) {
  return (
    <div className="card overflow-auto max-h-[500px]">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 sticky top-0"><tr>
          <th className="px-3 py-2 text-left">{canonicalLabel} <span className="text-[10px] font-normal text-gray-400">(thả alias vào đây)</span></th><th className="px-3 py-2 text-left">Alias</th><th className="w-24"></th>
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
        </tbody>
      </table>
      <p className="text-xs text-gray-400 p-3">{rows.length} rules</p>
    </div>
  );
}
