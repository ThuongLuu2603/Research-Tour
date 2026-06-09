import { useState, useCallback, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getFilterOptions, Tour,
  listWorkspaces, getWorkspaceTours, downloadWorkspaceCsv, patchWorkspaceTour, bulkPatchWorkspaceTours,
  shareWorkspace, listWorkspaceMembers, revokeWorkspaceShare, copyWorkspaceOverrides,
  recomputeAllClassifications,
  getApplyClassificationStatus,
  WorkspaceInfo,
} from "@/lib/api";
import { fmtVND, formatPhanKhuc, segmentColor, cn } from "@/lib/utils";
import { useAuth } from "@/contexts/AuthContext";
import { COL } from "@/lib/glossary";
import { Search, Download, Flag, FlagOff, ChevronLeft, ChevronRight, ExternalLink, Pencil, Check, X, Users, Copy, ArrowUpDown, RefreshCw } from "lucide-react";

const PAGE_SIZE = 50;

type GridSortCol =
  | "id"
  | "ten_tour"
  | "cong_ty"
  | "thi_truong"
  | "tuyen_tour"
  | "thoi_gian"
  | "gia"
  | "phan_khuc"
  | "nguon"
  | "analyst_note";

const GRID_SORT_COLUMNS: { label: string; col: GridSortCol; wide?: boolean }[] = [
  { label: "#", col: "id" },
  { label: COL.tenTour, col: "ten_tour", wide: true },
  { label: COL.congTy, col: "cong_ty" },
  { label: COL.thiTruong, col: "thi_truong" },
  { label: COL.tuyenTour, col: "tuyen_tour" },
  { label: COL.thoiGian, col: "thoi_gian" },
  { label: COL.gia, col: "gia" },
  { label: "Phân khúc", col: "phan_khuc" },
  { label: "Nguồn", col: "nguon" },
  { label: "Ghi chú", col: "analyst_note" },
];

function SortTh({
  label,
  col,
  wide,
  sortBy,
  sortDir,
  onSort,
}: {
  label: string;
  col: GridSortCol;
  wide?: boolean;
  sortBy: GridSortCol;
  sortDir: "asc" | "desc";
  onSort: (c: GridSortCol) => void;
}) {
  const active = sortBy === col;
  return (
    <th
      className={cn(
        "px-3 py-2.5 text-left text-xs font-semibold text-gray-600 whitespace-nowrap cursor-pointer select-none hover:bg-gray-100",
        wide && "min-w-[260px] max-w-[440px] normal-case",
      )}
      onClick={() => onSort(col)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <ArrowUpDown size={11} className={cn(active ? "text-primary-600" : "text-gray-300")} />
        {active && <span className="text-primary-600 text-[10px]">{sortDir === "asc" ? "↑" : "↓"}</span>}
      </span>
    </th>
  );
}

function Badge({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("badge", className)}>{children}</span>;
}

/** Rút gọn trong ô bảng; hover hiện tooltip đủ nội dung. */
function HoverFullText({
  text,
  className,
  clamp = 2,
}: {
  text: string;
  className?: string;
  clamp?: 1 | 2;
}) {
  if (!text) return <span className="text-gray-400">—</span>;
  return (
    <span className="relative block max-w-full group/tip">
      <span
        className={cn(
          "block text-left",
          clamp === 2 ? "line-clamp-2" : "truncate",
          className,
        )}
      >
        {text}
      </span>
      <span
        role="tooltip"
        className="pointer-events-none invisible opacity-0 group-hover/tip:visible group-hover/tip:opacity-100 transition-opacity absolute z-30 left-0 top-full mt-1 w-max max-w-lg rounded-md border border-gray-700 bg-gray-900 text-white text-xs px-2.5 py-1.5 shadow-lg whitespace-normal leading-snug"
      >
        {text}
      </span>
    </span>
  );
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
  const [selRoutes, setSelRoutes] = useState<string[]>([]);
  const [selCompanies, setSelCompanies] = useState<string[]>([]);
  const [selPhanKhuc, setSelPhanKhuc] = useState<string[]>([]);
  const [selNguon, setSelNguon] = useState<string[]>([]);
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [pageInput, setPageInput] = useState("");
  const [toast, setToast] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkMarket, setBulkMarket] = useState("");
  const [bulkRoute, setBulkRoute] = useState("");
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [showShare, setShowShare] = useState(false);
  const [shareUsername, setShareUsername] = useState("");
  const [sharePerm, setSharePerm] = useState<"view" | "edit" | "copy">("view");
  const [copyFromId, setCopyFromId] = useState("");
  const [exporting, setExporting] = useState(false);
  const [sortBy, setSortBy] = useState<GridSortCol>("id");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  // Issue #4: Refresh / Re-apply rules — chỉ trigger classification, KHÔNG scrape, KHÔNG import.
  const [recomputing, setRecomputing] = useState(false);
  // Issue #7: Số ngày filter (dropdown options từ existing values)
  const [selDays, setSelDays] = useState<string[]>([]);

  const handleSort = (col: GridSortCol) => {
    if (sortBy === col) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortBy(col);
      setSortDir(col === "gia" || col === "id" ? "desc" : "asc");
    }
    setPage(1);
  };

  const { data: workspaces } = useQuery({ queryKey: ["workspaces"], queryFn: listWorkspaces, staleTime: 60000 });
  const activeWs = workspaces?.find((w) => w.id === workspaceId) ?? workspaces?.[0];
  const canEdit = activeWs?.permission === "edit" || activeWs?.is_owner;
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  useEffect(() => {
    if (workspaces?.length && workspaceId == null) {
      setWorkspaceId(workspaces[0].id);
    }
  }, [workspaces, workspaceId]);

  const { data: opts } = useQuery({ queryKey: ["filter-options"], queryFn: getFilterOptions, staleTime: 60000 });

  const availableRoutes = useMemo(() => {
    const byMarket = (opts?.routes_by_market ?? {}) as Record<string, string[]>;
    if (!selMarkets.length) return (opts?.tuyen_tour ?? []) as string[];
    const routes = new Set<string>();
    selMarkets.forEach((m) => (byMarket[m] ?? []).forEach((r) => routes.add(r)));
    return [...routes].sort((a, b) => a.localeCompare(b, "vi"));
  }, [opts, selMarkets]);

  // Issue #7: Reverse mapping route → market (auto-fill TT khi user chọn Tuyến tour trước).
  const marketByRoute = useMemo(() => {
    const map: Record<string, string> = {};
    const byMarket = (opts?.routes_by_market ?? {}) as Record<string, string[]>;
    Object.entries(byMarket).forEach(([mk, routes]) => {
      routes.forEach((r) => {
        // Nếu 1 tuyến tour thuộc nhiều TT (hiếm), giữ TT đầu tiên gặp.
        if (!(r in map)) map[r] = mk;
      });
    });
    return map;
  }, [opts]);

  useEffect(() => {
    setSelRoutes((prev) => {
      if (!prev.length) return prev;
      const valid = new Set(availableRoutes);
      const next = prev.filter((r) => valid.has(r));
      return next.length === prev.length ? prev : next;
    });
  }, [availableRoutes]);

  const { data, isFetching } = useQuery({
    queryKey: ["workspace-tours", workspaceId, page, search, selMarkets, selRoutes, selCompanies, selPhanKhuc, selNguon, onlyFlagged, sortBy, sortDir],
    queryFn: () => getWorkspaceTours(workspaceId!, {
      page, page_size: PAGE_SIZE, search,
      thi_truong: selMarkets, tuyen_tour: selRoutes, cong_ty: selCompanies,
      phan_khuc: selPhanKhuc, nguon: selNguon,
      flagged: onlyFlagged || undefined,
      sort_by: sortBy,
      sort_dir: sortDir,
    }),
    enabled: !!workspaceId,
    placeholderData: (prev) => prev,
    staleTime: 60_000,
    refetchInterval: 120_000,
    refetchOnWindowFocus: true,
  });

  // Issue #7: Số ngày dropdown options — distinct so_ngay từ trang hiện tại (workspace data).
  // Backend filter-options không trả so_ngay → derive client-side. Tooltip note coord.
  const dayOptions = useMemo(() => {
    const set = new Set<number>();
    (data?.items ?? []).forEach((t) => {
      if (t.so_ngay != null && t.so_ngay > 0) set.add(t.so_ngay);
    });
    return [...set].sort((a, b) => a - b);
  }, [data]);

  const { data: members, refetch: refetchMembers } = useQuery({
    queryKey: ["workspace-members", workspaceId],
    queryFn: () => listWorkspaceMembers(workspaceId!),
    enabled: !!workspaceId && showShare,
  });

  const mutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<Tour> }) =>
      patchWorkspaceTour(workspaceId!, id, patch),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["workspace-tours"] });
      // Admin sửa Thị trường/Tuyến/Thời gian → ghi vào DB chung; còn lại → riêng workspace.
      const wroteShared = isAdmin && ["thi_truong", "tuyen_tour", "thoi_gian"].some((k) => k in variables.patch);
      setToast(wroteShared
        ? "Đã ghi vào dữ liệu chung (áp dụng cho So sánh VTR; quy tắc sẽ không ghi đè khi tour update)"
        : "Đã lưu vào workspace của bạn (không ảnh hưởng dữ liệu chung / user khác)");
    },
    onError: (e: { response?: { data?: { detail?: string } } }) => {
      setToast(e.response?.data?.detail || "Lỗi lưu tour");
    },
  });

  const bulkMutation = useMutation({
    mutationFn: (body: { tour_ids: string[]; thi_truong?: string; tuyen_tour?: string; flagged?: boolean }) =>
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

  const handleExport = async () => {
    if (!workspaceId || exporting) return;
    setExporting(true);
    try {
      await downloadWorkspaceCsv(workspaceId, {
        search,
        thi_truong: selMarkets,
        tuyen_tour: selRoutes,
        cong_ty: selCompanies,
        phan_khuc: selPhanKhuc,
        nguon: selNguon,
        flagged: onlyFlagged || undefined,
      });
      setToast("Đã tải CSV");
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Lỗi tải CSV");
    } finally {
      setExporting(false);
    }
  };

  /**
   * Issue #4: Refresh / Re-apply rules — KHÔNG scrape, KHÔNG import.
   * Trigger re-apply: TT, tuyến tour, ngày KH, số ngày, phân khúc.
   * Endpoint reuse: POST /admin/rules/apply-classification-to-tours?full_scan=true&recompute_phan_khuc=true
   *   → backend chạy nền: apply_all_rules_to_tours (TT, tuyến, ngày, công ty, điểm KH, thời gian) + recompute phân khúc.
   *
   * NOTE for backend coord: nếu muốn UX nhanh hơn (skip company/departure scope vì
   * tab Sản phẩm & Data không cần re-apply alias), tạo endpoint mới
   *   POST /api/admin/recompute-all-classifications
   * gói chỉ market+route+phan_khuc+date. Hiện reuse endpoint full scope.
   */
  const handleRecomputeRules = async () => {
    if (recomputing) return;
    if (!isAdmin) {
      setToast("Chỉ admin mới có quyền re-apply rules.");
      return;
    }
    setRecomputing(true);
    setToast("Đang re-apply rules (chạy nền) — không scrape, không import…");
    try {
      const r = await recomputeAllClassifications();
      setToast(r.message || "Đã bắt đầu re-apply rules (chạy nền)…");
      // Poll status để báo xong
      const poll = async (attempt = 0) => {
        try {
          const st = await getApplyClassificationStatus();
          if (st.running && attempt < 120) {
            const prog = st.progress != null && st.total
              ? `Đang re-apply rules: ${st.progress}/${st.total} tour…`
              : st.message || "Đang re-apply rules…";
            setToast(prog);
            window.setTimeout(() => poll(attempt + 1), 2000);
            return;
          }
          setRecomputing(false);
          if (st.error) {
            setToast(`Lỗi: ${st.error}`);
            return;
          }
          const msg = st.message
            || (st.last_result && typeof (st.last_result as { message?: string }).message === "string"
              ? (st.last_result as { message: string }).message
              : "Đã re-apply rules xong");
          setToast(msg);
          // Refresh data + filter-options
          qc.invalidateQueries({ queryKey: ["workspace-tours"] });
          qc.invalidateQueries({ queryKey: ["filter-options"] });
        } catch {
          setRecomputing(false);
        }
      };
      poll();
    } catch (e) {
      setRecomputing(false);
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e instanceof Error ? e.message : "Lỗi re-apply rules");
      setToast(msg);
    }
  };

  const toggleFilter = useCallback((arr: string[], set: (v: string[]) => void, val: string) => {
    set(arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val]);
    setPage(1);
  }, []);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);
  };

  // Issue #7: client-side post-filter cho selDays (backend chưa support so_ngay filter).
  // Áp dụng trên page hiện tại — note coord backend nếu cần cross-page filter chính xác.
  const visibleItems = useMemo(() => {
    const items = data?.items ?? [];
    if (!selDays.length) return items;
    const set = new Set(selDays.map((d) => parseFloat(d)));
    return items.filter((t) => t.so_ngay != null && set.has(t.so_ngay));
  }, [data, selDays]);

  const pageIds = visibleItems.map((t) => t.id);
  const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.includes(id));

  return (
    <div className="flex flex-col h-full p-6 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Research Grid</h1>
          <p className="text-sm text-gray-500">
            {(data?.total ?? 0).toLocaleString("vi-VN")} tour từ database chung (Main + Vietravel) · chỉnh sửa lưu workspace · tự làm mới ~2 phút
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
          {isAdmin && (
            <button
              onClick={handleRecomputeRules}
              disabled={recomputing}
              className="btn-secondary text-xs flex items-center gap-1 disabled:opacity-60"
              title="Re-apply rules: thị trường, tuyến tour, ngày KH, số ngày, phân khúc. KHÔNG scrape, KHÔNG import."
            >
              <RefreshCw size={14} className={recomputing ? "animate-spin" : ""} />
              {recomputing ? "Đang re-apply…" : "Refresh rules"}
            </button>
          )}
          <button onClick={handleExport} disabled={!workspaceId || exporting} className="btn-secondary text-xs">
            <Download size={14} /> {exporting ? "Đang tải…" : "CSV"}
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
          onChange={(e) => {
            const route = e.target.value;
            if (!route) return;
            // Issue #7: Cascading reverse — nếu user chọn Tuyến tour mà chưa có TT nào,
            // auto-fill TT tương ứng (tuyến → market lookup).
            if (!selMarkets.length) {
              const autoMarket = marketByRoute[route];
              if (autoMarket) {
                setSelMarkets([autoMarket]);
              }
            }
            toggleFilter(selRoutes, setSelRoutes, route);
            e.target.value = "";
          }}
        >
          <option value="">{COL.tuyenTour}{selRoutes.length ? ` (${selRoutes.length})` : ""}{selMarkets.length ? " — theo TT" : ""}</option>
          {availableRoutes.filter((r: string) => !selRoutes.includes(r)).map((r: string) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
        {selRoutes.map((r) => (
          <button key={r} onClick={() => toggleFilter(selRoutes, setSelRoutes, r)} className="text-xs px-2 py-1 rounded-full bg-teal-100 text-teal-800 flex items-center gap-1">
            {r}<X size={10} />
          </button>
        ))}

        {/* Issue #7: Số ngày dropdown — options từ existing values (so_ngay của tour hiện tại).
            Backend không filter theo so_ngay → filter client-side ở render bên dưới.
            NOTE coord backend: nếu cần filter chính xác cross-page, thêm
              GET /workspaces/{id}/tours?so_ngay=3&so_ngay=5
            trong WorkspaceTourFilters + backend api/workspaces.py. */}
        <select
          className="input text-xs py-1.5 max-w-[140px]"
          value=""
          onChange={(e) => { if (e.target.value) toggleFilter(selDays, setSelDays, e.target.value); e.target.value = ""; }}
        >
          <option value="">Số ngày{selDays.length ? ` (${selDays.length})` : ""}</option>
          {dayOptions.filter((d) => !selDays.includes(String(d))).map((d) => (
            <option key={d} value={String(d)}>{d} ngày</option>
          ))}
        </select>
        {selDays.map((d) => (
          <button key={d} onClick={() => toggleFilter(selDays, setSelDays, d)} className="text-xs px-2 py-1 rounded-full bg-cyan-100 text-cyan-800 flex items-center gap-1">
            {d} ngày<X size={10} />
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

        <select
          className="input text-xs py-1.5 max-w-[140px]"
          value=""
          onChange={(e) => { if (e.target.value) toggleFilter(selPhanKhuc, setSelPhanKhuc, e.target.value); e.target.value = ""; }}
        >
          <option value="">Phân khúc{selPhanKhuc.length ? ` (${selPhanKhuc.length})` : ""}</option>
          {(opts?.phan_khuc ?? []).filter((p: string) => p && !selPhanKhuc.includes(p)).map((p: string) => (
            <option key={p} value={p}>{formatPhanKhuc(p) || p}</option>
          ))}
        </select>
        {selPhanKhuc.map((p) => (
          <button key={p} onClick={() => toggleFilter(selPhanKhuc, setSelPhanKhuc, p)} className="text-xs px-2 py-1 rounded-full bg-rose-100 text-rose-800 flex items-center gap-1">
            {formatPhanKhuc(p) || p}<X size={10} />
          </button>
        ))}

        <button
          onClick={() => { setOnlyFlagged((v) => !v); setPage(1); }}
          className={cn("text-xs flex items-center gap-1 px-3 py-1.5 rounded-lg border transition-colors", onlyFlagged ? "bg-amber-50 text-amber-700 border-amber-400" : "bg-white text-gray-600 border-gray-300")}
        >
          <Flag size={12} /> Flagged
        </button>

        {(selMarkets.length > 0 || selRoutes.length > 0 || selCompanies.length > 0 || selPhanKhuc.length > 0 || selNguon.length > 0 || selDays.length > 0 || onlyFlagged || search) && (
          <button
            onClick={() => { setSelMarkets([]); setSelRoutes([]); setSelCompanies([]); setSelPhanKhuc([]); setSelNguon([]); setSelDays([]); setOnlyFlagged(false); setSearch(""); setPage(1); }}
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
              {GRID_SORT_COLUMNS.map(({ label, col, wide }) => (
                <SortTh
                  key={col}
                  label={label}
                  col={col}
                  wide={wide}
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
              ))}
              <th className="px-3 py-2.5 text-left text-xs font-semibold text-gray-600 whitespace-nowrap">Flag</th>
              <th className="px-3 py-2.5 text-left text-xs font-semibold text-gray-600 whitespace-nowrap">{COL.linkTour}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {visibleItems.map((tour, i) => (
              <tr key={tour.id} className={cn("hover:bg-blue-50 transition-colors", tour.flagged && "bg-amber-50", tour.has_override && "ring-1 ring-inset ring-blue-200", selectedIds.includes(tour.id) && "bg-blue-50/60")}>
                <td className="px-3 py-2">
                  <input type="checkbox" disabled={!canEdit} checked={selectedIds.includes(tour.id)} onChange={() => toggleSelect(tour.id)} />
                </td>
                <td className="px-3 py-2 text-xs text-gray-400">{(page - 1) * PAGE_SIZE + i + 1}</td>
                <td className="px-3 py-2 min-w-[260px] max-w-[440px] align-top">
                  <HoverFullText
                    text={tour.ten_tour}
                    className="font-medium text-gray-900 text-xs leading-snug"
                    clamp={2}
                  />
                  {tour.has_override && <span className="text-[10px] text-blue-600 block mt-0.5">Đã chỉnh workspace</span>}
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
                <td className="px-3 py-2">
                  <EditableCell disabled={!canEdit} value={tour.thoi_gian} onSave={(v) => mutation.mutate({ id: tour.id, patch: { thoi_gian: v } })} />
                </td>
                <td className="px-3 py-2 text-xs font-medium text-gray-900 whitespace-nowrap">
                  {tour.gia ? `${fmtVND(tour.gia)}` : tour.gia_raw || "—"}
                </td>
                <td className="px-3 py-2">
                  {tour.phan_khuc ? (
                    <Badge className={segmentColor(tour.phan_khuc)}>{formatPhanKhuc(tour.phan_khuc) || tour.phan_khuc}</Badge>
                  ) : (
                    <span className="text-xs text-gray-400">—</span>
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

      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-xs text-gray-500">
          Trang {page}/{totalPages || 1} · {(data?.total ?? 0).toLocaleString("vi-VN")} kết quả
        </p>
        <div className="flex gap-1 items-center flex-wrap">
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
          {totalPages > 5 && (
            <form
              className="flex items-center gap-1 ml-1"
              onSubmit={(e) => {
                e.preventDefault();
                const n = Number(pageInput);
                if (n >= 1 && n <= totalPages) setPage(n);
              }}
            >
              <input
                className="input text-xs py-1 w-14 text-center"
                placeholder="Trang"
                value={pageInput}
                onChange={(e) => setPageInput(e.target.value.replace(/\D/g, ""))}
              />
              <button type="submit" className="btn-secondary text-xs py-1 px-2">Đi</button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
