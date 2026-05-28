import { useState, useCallback, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getFilterOptions, syncToursFromGoogleSheet, Tour,
  listWorkspaces, getWorkspaceTours, patchWorkspaceTour, bulkPatchWorkspaceTours,
  shareWorkspace, listWorkspaceMembers, revokeWorkspaceShare, copyWorkspaceOverrides,
  WorkspaceInfo,
} from "@/lib/api";
import { fmtVND, formatPhanKhuc, segmentColor, cn } from "@/lib/utils";
import { formatApiError } from "@/lib/apiError";
import { COL } from "@/lib/glossary";
import { Search, Download, Flag, FlagOff, ChevronLeft, ChevronRight, ExternalLink, Pencil, Check, X, RefreshCw, Users, Copy } from "lucide-react";

const PAGE_SIZE = 50;

function Badge({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("badge", className)}>{children}</span>;
}

function EditableCell({ value, onSave, disabled }: { value: string; onSave: (v: string) => void; disabled?: boolean }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  if (disabled) {
    return <span className="truncate max-w-[140px]">{value || "—"}</span>;
  }
  if (!editing) {
    return (
      <span className="group flex items-center gap-1">
        <span className="truncate max-w-[140px]">{value || "—"}</span>
        <button onClick={() => { setDraft(value); setEditing(true); }} className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-primary-600">
          <Pencil size={12} />
        </button>
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1">
      <input
        autoFocus
        className="input text-xs py-0.5 px-1 w-36"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") { onSave(draft); setEditing(false); }
          if (e.key === "Escape") setEditing(false);
        }}
      />
      <button onClick={() => { onSave(draft); setEditing(false); }} className="text-green-600"><Check size={14} /></button>
      <button onClick={() => setEditing(false)} className="text-red-500"><X size={14} /></button>
    </span>
  );
}

export default function ResearchGrid() {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [selMarkets, setSelMarkets] = useState<string[]>([]);
  const [selCompanies, setSelCompanies] = useState<string[]>([]);
  const [selNguon, setSelNguon] = useState<string[]>([]);
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [toast, setToast] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkMarket, setBulkMarket] = useState("");
  const [bulkRoute, setBulkRoute] = useState("");
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [showShare, setShowShare] = useState(false);
  const [shareUsername, setShareUsername] = useState("");
  const [sharePerm, setSharePerm] = useState<"view" | "edit" | "copy">("view");
  const [copyFromId, setCopyFromId] = useState("");

  const { data: workspaces } = useQuery({ queryKey: ["workspaces"], queryFn: listWorkspaces, staleTime: 60000 });
  const activeWs = workspaces?.find((w) => w.id === workspaceId) ?? workspaces?.[0];
  const canEdit = activeWs?.permission === "edit" || activeWs?.is_owner;

  useEffect(() => {
    if (workspaces?.length && workspaceId == null) {
      setWorkspaceId(workspaces[0].id);
    }
  }, [workspaces, workspaceId]);

  const { data: opts } = useQuery({ queryKey: ["filter-options"], queryFn: getFilterOptions, staleTime: 60000 });
  const { data, isFetching } = useQuery({
    queryKey: ["workspace-tours", workspaceId, page, search, selMarkets, selCompanies, selNguon, onlyFlagged],
    queryFn: () => getWorkspaceTours(workspaceId!, {
      page, page_size: PAGE_SIZE, search,
      thi_truong: selMarkets, cong_ty: selCompanies, nguon: selNguon,
      flagged: onlyFlagged || undefined,
    }),
    enabled: !!workspaceId,
    placeholderData: (prev) => prev,
  });

  const { data: members, refetch: refetchMembers } = useQuery({
    queryKey: ["workspace-members", workspaceId],
    queryFn: () => listWorkspaceMembers(workspaceId!),
    enabled: !!workspaceId && showShare,
  });

  const mutation = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Partial<Tour> }) =>
      patchWorkspaceTour(workspaceId!, id, patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspace-tours"] });
      setToast("Đã lưu vào workspace (không ảnh hưởng dữ liệu chung / So sánh VTR)");
    },
    onError: (e: { response?: { data?: { detail?: string } } }) => {
      setToast(e.response?.data?.detail || "Lỗi lưu tour");
    },
  });

  const syncMutation = useMutation({
    mutationFn: syncToursFromGoogleSheet,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["workspace-tours"] });
      qc.invalidateQueries({ queryKey: ["filter-options"] });
      if (res.errors?.length) {
        const msg = res.errors.map((s) => `${s.nguon}: ${s.error}`).join(" · ");
        setToast(`Đồng bộ một phần — lỗi: ${msg}`);
        return;
      }
      const seg = res.phan_khuc?.updated != null ? ` · Phân khúc: ${res.phan_khuc.updated} tour` : "";
      setToast(
        `Đã kéo Sheet: +${res.total_inserted} mới, ${res.total_updated} cập nhật${seg}`
      );
    },
    onError: (e) => {
      setToast(formatApiError(e, "Lỗi đồng bộ từ Sheet (timeout hoặc Google API)"));
    },
  });

  const bulkMutation = useMutation({
    mutationFn: (body: { tour_ids: number[]; thi_truong?: string; tuyen_tour?: string; flagged?: boolean }) =>
      bulkPatchWorkspaceTours(workspaceId!, body),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["workspace-tours"] });
      setSelectedIds([]);
      setBulkMarket("");
      setBulkRoute("");
      setToast(`Đã cập nhật ${res.updated ?? selectedIds.length} tour trong workspace`);
    },
    onError: (e: { response?: { data?: { detail?: string } } }) => {
      setToast(e.response?.data?.detail || "Lỗi cập nhật hàng loạt");
    },
  });

  const shareMutation = useMutation({
    mutationFn: () => shareWorkspace(workspaceId!, shareUsername.trim(), sharePerm),
    onSuccess: () => {
      setShareUsername("");
      refetchMembers();
      setToast("Đã chia sẻ workspace");
    },
    onError: (e: { response?: { data?: { detail?: string } } }) => {
      setToast(e.response?.data?.detail || "Lỗi chia sẻ");
    },
  });

  const copyMutation = useMutation({
    mutationFn: () => copyWorkspaceOverrides(workspaceId!, Number(copyFromId)),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["workspace-tours"] });
      setCopyFromId("");
      setToast(`Đã copy ${res.copied} override sang workspace`);
    },
    onError: (e: { response?: { data?: { detail?: string } } }) => {
      setToast(e.response?.data?.detail || "Lỗi copy workspace");
    },
  });

  const totalPages = Math.ceil((data?.total ?? 0) / PAGE_SIZE);

  const handleExport = () => {
    const token = localStorage.getItem("access_token");
    window.open(`/api/workspaces/${workspaceId}/export/csv?search=${encodeURIComponent(search)}&access_token=${token}`, "_blank");
  };

  const toggleFilter = useCallback((arr: string[], set: (v: string[]) => void, val: string) => {
    set(arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val]);
    setPage(1);
  }, []);

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);
  };

  const pageIds = (data?.items ?? []).map((t) => t.id);
  const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.includes(id));

  return (
    <div className="flex flex-col h-full p-6 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Research Grid</h1>
          <p className="text-sm text-gray-500">
            {(data?.total ?? 0).toLocaleString("vi-VN")} tour · Chỉnh sửa chỉ trong workspace (So sánh VTR dùng dữ liệu chung)
          </p>
        </div>
        <div className="flex gap-2 flex-wrap items-center">
          <select
            className="input text-xs py-1.5 max-w-[220px]"
            value={workspaceId ?? ""}
            onChange={(e) => { setWorkspaceId(Number(e.target.value)); setPage(1); }}
          >
            {(workspaces ?? []).map((w: WorkspaceInfo) => (
              <option key={w.id} value={w.id}>
                {w.name}{w.is_personal ? " (cá nhân)" : ""} — {w.permission}
              </option>
            ))}
          </select>
          {activeWs?.is_owner && (
            <button onClick={() => setShowShare((v) => !v)} className="btn-secondary text-xs flex items-center gap-1">
              <Users size={14} /> Chia sẻ
            </button>
          )}
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className="btn-secondary text-xs flex items-center gap-1"
            title="Kéo dữ liệu chung từ Google Sheet"
          >
            <RefreshCw size={14} className={syncMutation.isPending ? "animate-spin" : ""} />
            Kéo từ Sheet
          </button>
          <button onClick={handleExport} className="btn-secondary text-xs">
            <Download size={14} /> CSV
          </button>
        </div>
      </div>

      {showShare && activeWs?.is_owner && (
        <div className="card p-4 space-y-3 border border-slate-200">
          <h3 className="font-semibold text-sm flex items-center gap-2"><Users size={14} /> Chia sẻ workspace</h3>
          <div className="flex flex-wrap gap-2 items-center">
            <input className="input text-xs py-1 w-40" placeholder="Username" value={shareUsername} onChange={(e) => setShareUsername(e.target.value)} />
            <select className="input text-xs py-1" value={sharePerm} onChange={(e) => setSharePerm(e.target.value as "view" | "edit" | "copy")}>
              <option value="view">Xem</option>
              <option value="edit">Sửa</option>
              <option value="copy">Copy</option>
            </select>
            <button className="btn-primary text-xs" disabled={!shareUsername.trim() || shareMutation.isPending} onClick={() => shareMutation.mutate()}>
              Mời
            </button>
          </div>
          <ul className="text-xs space-y-1">
            {(members?.members ?? []).map((m) => (
              <li key={m.user_id} className="flex items-center justify-between gap-2 py-1 border-b border-gray-100">
                <span>{m.display_name || m.username} ({m.permission}){m.is_owner ? " · chủ" : ""}</span>
                {!m.is_owner && (
                  <button className="text-red-500 hover:text-red-700" onClick={() => revokeWorkspaceShare(workspaceId!, m.user_id).then(() => refetchMembers())}>
                    Thu hồi
                  </button>
                )}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2 items-center pt-2 border-t border-gray-100">
            <Copy size={14} className="text-gray-500" />
            <span className="text-xs text-gray-600">Copy override từ workspace ID:</span>
            <input className="input text-xs py-1 w-24" value={copyFromId} onChange={(e) => setCopyFromId(e.target.value)} placeholder="ID" />
            <button className="btn-secondary text-xs" disabled={!copyFromId || copyMutation.isPending} onClick={() => copyMutation.mutate()}>
              Copy sang workspace hiện tại
            </button>
          </div>
        </div>
      )}

      {toast && (
        <p className="text-xs px-3 py-2 rounded bg-blue-50 text-blue-800 flex items-center justify-between">
          {toast}
          <button onClick={() => setToast("")} className="text-blue-600 hover:text-blue-900 ml-4"><X size={12} /></button>
        </p>
      )}

      {!canEdit && (
        <p className="text-xs px-3 py-2 rounded bg-amber-50 text-amber-800">
          Workspace này chỉ xem — không thể chỉnh sửa.
        </p>
      )}

      <div className="card p-4 flex flex-wrap gap-3 items-center">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            className="input pl-8 w-60 text-xs"
            placeholder="Tìm tên tour, công ty, mã..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          />
        </div>

        <div className="flex gap-1 flex-wrap">
          {(opts?.nguon ?? []).map((n: string) => (
            <button
              key={n}
              onClick={() => toggleFilter(selNguon, setSelNguon, n)}
              className={cn("text-xs px-2.5 py-1 rounded-full border transition-colors", selNguon.includes(n) ? "bg-primary-600 text-white border-primary-600" : "bg-white text-gray-600 border-gray-300 hover:border-primary-400")}
            >
              {n}
            </button>
          ))}
        </div>

        <select
          className="input text-xs py-1.5 max-w-[160px]"
          value=""
          onChange={(e) => { if (e.target.value) toggleFilter(selMarkets, setSelMarkets, e.target.value); e.target.value = ""; }}
        >
          <option value="">{COL.thiTruong}{selMarkets.length ? ` (${selMarkets.length})` : ""}</option>
          {(opts?.thi_truong ?? []).filter((m: string) => !selMarkets.includes(m)).map((m: string) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        {selMarkets.map((m) => (
          <button key={m} onClick={() => toggleFilter(selMarkets, setSelMarkets, m)} className="text-xs px-2 py-1 rounded-full bg-indigo-100 text-indigo-800 flex items-center gap-1">
            {m}<X size={10} />
          </button>
        ))}

        <select
          className="input text-xs py-1.5 max-w-[160px]"
          value=""
          onChange={(e) => { if (e.target.value) toggleFilter(selCompanies, setSelCompanies, e.target.value); e.target.value = ""; }}
        >
          <option value="">{COL.congTy}{selCompanies.length ? ` (${selCompanies.length})` : ""}</option>
          {(opts?.cong_ty ?? []).filter((c: string) => !selCompanies.includes(c)).slice(0, 200).map((c: string) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        {selCompanies.map((c) => (
          <button key={c} onClick={() => toggleFilter(selCompanies, setSelCompanies, c)} className="text-xs px-2 py-1 rounded-full bg-purple-100 text-purple-800 flex items-center gap-1">
            {c}<X size={10} />
          </button>
        ))}

        <button
          onClick={() => { setOnlyFlagged((v) => !v); setPage(1); }}
          className={cn("text-xs flex items-center gap-1 px-3 py-1.5 rounded-lg border transition-colors", onlyFlagged ? "bg-amber-50 text-amber-700 border-amber-400" : "bg-white text-gray-600 border-gray-300")}
        >
          <Flag size={12} /> Flagged
        </button>

        {(selMarkets.length > 0 || selCompanies.length > 0 || selNguon.length > 0 || onlyFlagged || search) && (
          <button
            onClick={() => { setSelMarkets([]); setSelCompanies([]); setSelNguon([]); setOnlyFlagged(false); setSearch(""); setPage(1); }}
            className="text-xs text-red-500 hover:text-red-700 flex items-center gap-1"
          >
            <X size={12} /> Xoá bộ lọc
          </button>
        )}

        {isFetching && <span className="text-xs text-gray-400 ml-auto animate-pulse">Đang tải...</span>}
      </div>

      {canEdit && selectedIds.length > 0 && (
        <div className="card p-3 flex flex-wrap items-center gap-3 bg-slate-50 border border-slate-200">
          <span className="text-xs font-medium">{selectedIds.length} tour đã chọn</span>
          <input className="input text-xs py-1 w-40" placeholder={COL.thiTruong} value={bulkMarket} onChange={(e) => setBulkMarket(e.target.value)} />
          <input className="input text-xs py-1 w-40" placeholder={COL.tuyenTour} value={bulkRoute} onChange={(e) => setBulkRoute(e.target.value)} />
          <button
            className="btn-primary text-xs"
            disabled={bulkMutation.isPending || (!bulkMarket && !bulkRoute)}
            onClick={() => bulkMutation.mutate({
              tour_ids: selectedIds,
              ...(bulkMarket ? { thi_truong: bulkMarket } : {}),
              ...(bulkRoute ? { tuyen_tour: bulkRoute } : {}),
            })}
          >
            Áp dụng hàng loạt
          </button>
          <button className="btn-secondary text-xs" onClick={() => bulkMutation.mutate({ tour_ids: selectedIds, flagged: true })}>Flag</button>
          <button className="text-xs text-gray-500" onClick={() => setSelectedIds([])}>Bỏ chọn</button>
        </div>
      )}

      <div className="card overflow-auto flex-1 min-h-0">
        <table className="w-full text-sm border-collapse">
          <thead className="sticky top-0 z-10">
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="px-3 py-2.5 text-left">
                <input type="checkbox" disabled={!canEdit} checked={allPageSelected} onChange={() => setSelectedIds(allPageSelected ? selectedIds.filter((id) => !pageIds.includes(id)) : [...new Set([...selectedIds, ...pageIds])])} />
              </th>
              {["#", COL.tenTour, COL.congTy, COL.thiTruong, COL.tuyenTour, COL.thoiGian, COL.gia, "Phân khúc", "Nguồn", "Ghi chú", "Flag", COL.linkTour].map((h) => (
                <th key={h} className="px-3 py-2.5 text-left text-xs font-semibold text-gray-600 whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {(data?.items ?? []).map((tour, i) => (
              <tr key={tour.id} className={cn("hover:bg-blue-50 transition-colors", tour.flagged && "bg-amber-50", tour.has_override && "ring-1 ring-inset ring-blue-200", selectedIds.includes(tour.id) && "bg-blue-50/60")}>
                <td className="px-3 py-2">
                  <input type="checkbox" disabled={!canEdit} checked={selectedIds.includes(tour.id)} onChange={() => toggleSelect(tour.id)} />
                </td>
                <td className="px-3 py-2 text-xs text-gray-400">{(page - 1) * PAGE_SIZE + i + 1}</td>
                <td className="px-3 py-2 max-w-xs">
                  <p className="font-medium text-gray-900 text-xs leading-snug line-clamp-2">{tour.ten_tour}</p>
                  {tour.has_override && <span className="text-[10px] text-blue-600">Đã chỉnh workspace</span>}
                </td>
                <td className="px-3 py-2 text-xs text-gray-700 max-w-[140px]">
                  <span className="truncate block max-w-[140px]">{tour.cong_ty}</span>
                </td>
                <td className="px-3 py-2">
                  <EditableCell disabled={!canEdit} value={tour.thi_truong} onSave={(v) => mutation.mutate({ id: tour.id, patch: { thi_truong: v } })} />
                </td>
                <td className="px-3 py-2">
                  <EditableCell disabled={!canEdit} value={tour.tuyen_tour} onSave={(v) => mutation.mutate({ id: tour.id, patch: { tuyen_tour: v } })} />
                </td>
                <td className="px-3 py-2 text-xs text-gray-600 whitespace-nowrap">{tour.thoi_gian || "—"}</td>
                <td className="px-3 py-2 text-xs font-medium text-gray-900 whitespace-nowrap">
                  {tour.gia ? `${fmtVND(tour.gia)}` : tour.gia_raw || "—"}
                </td>
                <td className="px-3 py-2">
                  {tour.phan_khuc && formatPhanKhuc(tour.phan_khuc) && (
                    <Badge className={segmentColor(tour.phan_khuc)}>{formatPhanKhuc(tour.phan_khuc)}</Badge>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-gray-500">{tour.nguon}</td>
                <td className="px-3 py-2">
                  <EditableCell disabled={!canEdit} value={tour.analyst_note} onSave={(v) => mutation.mutate({ id: tour.id, patch: { analyst_note: v } })} />
                </td>
                <td className="px-3 py-2">
                  <button
                    disabled={!canEdit}
                    onClick={() => mutation.mutate({ id: tour.id, patch: { flagged: !tour.flagged } })}
                    className={cn("transition-colors", tour.flagged ? "text-amber-500 hover:text-amber-700" : "text-gray-300 hover:text-amber-400", !canEdit && "opacity-40 cursor-not-allowed")}
                  >
                    {tour.flagged ? <Flag size={14} /> : <FlagOff size={14} />}
                  </button>
                </td>
                <td className="px-3 py-2">
                  {tour.link_url && (
                    <a href={tour.link_url} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:text-primary-800">
                      <ExternalLink size={14} />
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">
          Trang {page}/{totalPages || 1} · {(data?.total ?? 0).toLocaleString("vi-VN")} kết quả
        </p>
        <div className="flex gap-1">
          <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="btn-secondary px-2 py-1.5 text-xs">
            <ChevronLeft size={14} />
          </button>
          {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
            const p = page <= 3 ? i + 1 : page - 2 + i;
            if (p < 1 || p > totalPages) return null;
            return (
              <button key={p} onClick={() => setPage(p)} className={cn("px-3 py-1.5 text-xs rounded-lg border", p === page ? "bg-primary-600 text-white border-primary-600" : "bg-white text-gray-600 border-gray-300 hover:border-primary-400")}>
                {p}
              </button>
            );
          })}
          <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages || totalPages === 0} className="btn-secondary px-2 py-1.5 text-xs">
            <ChevronRight size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
