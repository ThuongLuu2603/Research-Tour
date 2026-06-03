import { Navigate } from "react-router-dom";
import { useCallback, useMemo, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listRouteRules, deleteRouteRule, updateRouteRule,
  listCompanyRules, createCompanyRule, deleteCompanyRule, updateCompanyRule,
  listDepartureRules, createDepartureRule, deleteDepartureRule, updateDepartureRule,
  listDurationRules, createDurationRule, deleteDurationRule, updateDurationRule,
  seedCompanyDefaults, seedDepartureDefaults, seedDurationDefaults,
  applyClassificationToTours,
  getApplyClassificationStatus,
  getRulesUnmatched,
  RouteRule, CompanyRule, DepartureRule, DurationRule, UnmatchedItem,
} from "@/lib/api";
import { COL } from "@/lib/glossary";
import { InfoTip } from "@/components/InfoTip";
import { cn } from "@/lib/utils";
import { formatDurationLabel, parseDurationInput } from "@/lib/durationFormat";
import { buildRouteKeywordConflicts, mergeRouteKeywordLists, parseRouteKeywordList } from "@/lib/rulesUnmatched";
import { dropHandlers, dragAliasProps, keepInputKeys, keywordForRouteDrop, matchRulesSearch } from "@/lib/rulesAdminUi";
import { ClassificationRulesTab } from "@/components/ClassificationRulesTab";
import { Plus, Trash2, RefreshCw, Database, Search, Pencil, Check, X, GripVertical } from "lucide-react";

type Tab = "classify" | "company" | "departure" | "duration";
const matchSearch = matchRulesSearch;

function RuleSearchBar({ value, onChange, total, filtered }: { value: string; onChange: (v: string) => void; total: number; filtered: number }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="relative flex-1 min-w-[220px] max-w-md">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          className="input pl-9 text-sm w-full"
          placeholder="Tìm thị trường, tuyến, keyword, tên tour..."
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={keepInputKeys}
        />
      </div>
      <span className="text-xs text-gray-500">{filtered}/{total} dòng</span>
    </div>
  );
}

export default function RulesAdminPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [tab, setTab] = useState<Tab>("classify");
  const [search, setSearch] = useState("");
  const [syncMsg, setSyncMsg] = useState("");
  const [applying, setApplying] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<Record<string, string>>({});

  const [cCanonical, setCCanonical] = useState("");
  const [cAlias, setCAlias] = useState("");
  const [dCanonical, setDCanonical] = useState("");
  const [dAlias, setDAlias] = useState("");
  const [durDays, setDurDays] = useState("");
  const [durAlias, setDurAlias] = useState("");
  const [dropTarget, setDropTarget] = useState<string | null>(null);

  const { data: routeRules } = useQuery({ queryKey: ["route-rules"], queryFn: listRouteRules, enabled: isAdmin });
  const { data: companyRules } = useQuery({ queryKey: ["company-rules"], queryFn: listCompanyRules, enabled: isAdmin });
  const { data: departureRules } = useQuery({ queryKey: ["departure-rules"], queryFn: listDepartureRules, enabled: isAdmin });
  const { data: durationRules } = useQuery({ queryKey: ["duration-rules"], queryFn: listDurationRules, enabled: isAdmin });
  const unmatchedScope = tab === "classify" || tab === "company" || tab === "departure" || tab === "duration" ? tab : null;
  const [hiddenGapValues, setHiddenGapValues] = useState<Set<string>>(() => new Set());
  const { data: unmatched, isLoading: unmatchedLoading } = useQuery({
    queryKey: ["rules-unmatched", unmatchedScope],
    queryFn: () => getRulesUnmatched(unmatchedScope!, false),
    enabled: isAdmin && !!unmatchedScope,
    staleTime: 120_000,
  });

  const refreshUnmatchedList = useCallback(async () => {
    if (!unmatchedScope) return;
    const data = await getRulesUnmatched(unmatchedScope, true);
    qc.setQueryData(["rules-unmatched", unmatchedScope], data);
    setHiddenGapValues((prev) => {
      if (!prev.size) return prev;
      const remaining = new Set(data.items.map((i) => i.value));
      const next = new Set<string>();
      for (const v of prev) {
        if (remaining.has(v)) next.add(v);
      }
      return next;
    });
  }, [unmatchedScope, qc]);

  const markGapsHandled = useCallback((values: string[]) => {
    if (!values.length) return;
    setHiddenGapValues((prev) => new Set([...prev, ...values]));
    void refreshUnmatchedList();
  }, [refreshUnmatchedList]);

  const unmarkGapsHandled = useCallback((values: string[]) => {
    if (!values.length) return;
    setHiddenGapValues((prev) => {
      const next = new Set(prev);
      for (const v of values) next.delete(v);
      return next;
    });
  }, []);

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
  const appendKeywordToRouteRule = async (rule: RouteRule, raw: string) => {
    const add = parseRouteKeywordList(keywordForRouteDrop(raw) || raw);
    if (!add.length) {
      setSyncMsg("Nhập keyword ngắn (vd: mexico) hoặc nhiều từ cách nhau dấu phẩy (canada, cuba, mexico).");
      return;
    }
    const merged = mergeRouteKeywordLists(rule.keywords, add.join(", "));
    await updateRouteRule(rule.id, {
      thi_truong: rule.thi_truong,
      tuyen_tour: rule.tuyen_tour,
      keywords: merged,
    });
    afterRuleSaved(`Đã thêm vào rule — tour phải chứa đủ: ${merged}`);
  };

  const showErr = (e: unknown) =>
    setSyncMsg(String((e as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail || (e as Error)?.message || e));

  const finishApplyPoll = (st: { running?: boolean; error?: string; message?: string; last_result?: unknown }) => {
    setApplying(false);
    if (st.error) {
      setSyncMsg(st.error);
      return;
    }
    const msg =
      st.message
      || (st.last_result && typeof (st.last_result as { message?: string }).message === "string"
        ? (st.last_result as { message: string }).message
        : "");
    if (msg) setSyncMsg(msg);
    invalidate();
    void refreshUnmatchedList();
  };

  const pollApplyStatus = (attempt = 0) => {
    getApplyClassificationStatus()
      .then((st) => {
        if (st.running && attempt < 120) {
          setSyncMsg(st.message || (st.progress ? `Đang áp dụng… ${st.progress} tour` : "Đang áp dụng quy tắc…"));
          window.setTimeout(() => pollApplyStatus(attempt + 1), 2000);
          return;
        }
        finishApplyPoll(st);
      })
      .catch(() => setApplying(false));
  };

  const pollAfterRuleSave = (attempt = 0) => {
    getApplyClassificationStatus()
      .then((st) => {
        if (st.running && attempt < 60) {
          setSyncMsg(st.message || "Đang áp dụng quy tắc lên tour…");
          window.setTimeout(() => pollAfterRuleSave(attempt + 1), 2000);
          return;
        }
        invalidate();
        if (st.message && !st.running) setSyncMsg(st.message);
        void refreshUnmatchedList();
      })
      .catch(() => {
        invalidate();
        void refreshUnmatchedList();
      });
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

  const afterRuleSaved = (label: string, opts?: { gapValues?: string[]; skipPoll?: boolean }) => {
    if (opts?.gapValues?.length) markGapsHandled(opts.gapValues);
    invalidate();
    setSyncMsg(label);
    void refreshUnmatchedList();
    if (!opts?.skipPoll) pollAfterRuleSave();
  };

  const startEdit = (id: number, draft: Record<string, string>) => {
    setEditingId(id);
    setEditDraft(draft);
  };
  const cancelEdit = () => { setEditingId(null); setEditDraft({}); };

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
  const routeKeywordConflicts = useMemo(
    () => buildRouteKeywordConflicts(routeRules ?? []),
    [routeRules],
  );

  const filteredUnmatched = useMemo(() => {
    const base = (unmatched?.items ?? []).filter((x) => matchSearch(
      search,
      x.value,
      x.count,
      x.thi_truong,
      x.keyword,
      x.suggested_market,
      x.suggested_thi_truong,
      x.suggested_route,
      x.market_keyword,
      x.route_keywords,
      x.sample,
      x.needs_market ? "thiếu tt" : "",
      x.needs_route ? "thiếu tuyến" : "",
      ...(x.members ?? []).flatMap((m) => [m.title, m.count]),
    ));
    return base.filter((x) => !hiddenGapValues.has(x.value));
  }, [unmatched, search, hiddenGapValues]);

  const classifySearchCounts = useMemo(() => {
    const routes = (routeRules ?? []).filter((r) =>
      matchSearch(search, r.thi_truong, r.tuyen_tour, r.keywords),
    );
    return {
      filtered: routes.length + filteredUnmatched.length,
      total: (routeRules?.length ?? 0) + (unmatched?.items?.length ?? 0),
    };
  }, [routeRules, unmatched, search, filteredUnmatched.length]);

  const canonicalOptions = useMemo(() => {
    if (tab === "company") return [...new Set((companyRules ?? []).map((r) => r.canonical_name))];
    if (tab === "departure") return [...new Set((departureRules ?? []).map((r) => r.canonical_name))];
    return [];
  }, [tab, companyRules, departureRules]);
  const marketOptions = useMemo(
    () => [...new Set((routeRules ?? []).map((r) => r.thi_truong))].sort(),
    [routeRules],
  );
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
        {syncMsg && (
          <p
            className={cn(
              "text-sm px-3 py-2 rounded w-full border",
              applying || syncMsg.includes("Đang ")
                ? "text-amber-900 bg-amber-50 border-amber-200"
                : syncMsg.includes("thất bại") || syncMsg.includes("Lỗi") || syncMsg.includes("error")
                  ? "text-red-800 bg-red-50 border-red-200"
                  : "text-green-800 bg-green-50 border-green-200",
            )}
            role="status"
          >
            {syncMsg}
          </p>
        )}
      </div>

      <div className="flex gap-2 flex-wrap">
        {([
          ["classify", "Tuyến tour"],
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
          tab === "classify" ? classifySearchCounts.total
            : tab === "company" ? (companyRules?.length ?? 0) + (unmatched?.items?.length ?? 0)
            : tab === "departure" ? (departureRules?.length ?? 0) + (unmatched?.items?.length ?? 0)
            : tab === "duration" ? (durationRules?.length ?? 0) + (unmatched?.items?.length ?? 0)
            : (durationRules?.length ?? 0)
        }
        filtered={
          tab === "classify" ? classifySearchCounts.filtered
            : tab === "company" ? filteredCompany.length + filteredUnmatched.length
            : tab === "departure" ? filteredDeparture.length + filteredUnmatched.length
            : tab === "duration" ? filteredDuration.length + filteredUnmatched.length
            : filteredDuration.length
        }
      />

      {tab === "classify" && (
        <ClassificationRulesTab
          routeRules={routeRules}
          searchQuery={search}
          gapItems={filteredUnmatched}
          gapLoading={unmatchedLoading}
          marketOptions={marketOptions}
          routeKeywordConflicts={routeKeywordConflicts}
          dropTarget={dropTarget}
          setDropTarget={setDropTarget}
          onAfterSaved={afterRuleSaved}
          onMarkGapsHandled={markGapsHandled}
          onGapAssignFailed={unmarkGapsHandled}
          onError={showErr}
          appendKeywordToRouteRule={appendKeywordToRouteRule}
          deleteRouteRule={deleteRouteRule}
          actionBtns={actionBtns}
        />
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
