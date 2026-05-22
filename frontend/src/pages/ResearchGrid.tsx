import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getTours, getFilterOptions, patchTour, Tour } from "@/lib/api";
import { fmtVND, segmentColor, cn } from "@/lib/utils";
import { Search, Download, Flag, FlagOff, ChevronLeft, ChevronRight, ExternalLink, Pencil, Check, X } from "lucide-react";

const PAGE_SIZE = 50;

function Badge({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("badge", className)}>{children}</span>;
}

function EditableCell({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
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

  const { data: opts } = useQuery({ queryKey: ["filter-options"], queryFn: getFilterOptions, staleTime: 60000 });
  const { data, isFetching } = useQuery({
    queryKey: ["tours", page, search, selMarkets, selCompanies, selNguon, onlyFlagged],
    queryFn: () => getTours({ page, page_size: PAGE_SIZE, search, thi_truong: selMarkets, cong_ty: selCompanies, nguon: selNguon, flagged: onlyFlagged || undefined }),
    placeholderData: (prev) => prev,
  });

  const mutation = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Partial<Tour> }) => patchTour(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tours"] }),
  });

  const totalPages = Math.ceil((data?.total ?? 0) / PAGE_SIZE);

  const handleExport = (type: "csv" | "excel") => {
    const params: Record<string, string> = { search };
    selMarkets.forEach((m) => params[`thi_truong`] = m);
    const token = localStorage.getItem("access_token");
    const url = `/api/tours/export/${type}?search=${encodeURIComponent(search)}&access_token=${token}`;
    window.open(url, "_blank");
  };

  const toggleFilter = useCallback((arr: string[], set: (v: string[]) => void, val: string) => {
    set(arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val]);
    setPage(1);
  }, []);

  return (
    <div className="flex flex-col h-full p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Research Grid</h1>
          <p className="text-sm text-gray-500">
            {(data?.total ?? 0).toLocaleString("vi-VN")} tour · Chỉnh sửa trực tiếp Thị trường, Tuyến, Ghi chú
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => handleExport("csv")} className="btn-secondary text-xs">
            <Download size={14} /> CSV
          </button>
          <button onClick={() => handleExport("excel")} className="btn-secondary text-xs">
            <Download size={14} /> Excel
          </button>
        </div>
      </div>

      {/* Filters bar */}
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

        {/* Source filter */}
        <div className="flex gap-1">
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

      {/* Table */}
      <div className="card overflow-auto flex-1 min-h-0">
        <table className="w-full text-sm border-collapse">
          <thead className="sticky top-0 z-10">
            <tr className="bg-gray-50 border-b border-gray-200">
              {["#", "Tên Tour", "Công ty", "Thị trường", "Tuyến tour", "Ngày", "Giá", "Phân khúc", "Nguồn", "Ghi chú", "Flag", "Link"].map((h) => (
                <th key={h} className="px-3 py-2.5 text-left text-xs font-semibold text-gray-600 whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {(data?.items ?? []).map((tour, i) => (
              <tr key={tour.id} className={cn("hover:bg-blue-50 transition-colors", tour.flagged && "bg-amber-50")}>
                <td className="px-3 py-2 text-xs text-gray-400">{(page - 1) * PAGE_SIZE + i + 1}</td>
                <td className="px-3 py-2 max-w-xs">
                  <p className="font-medium text-gray-900 text-xs leading-snug line-clamp-2">{tour.ten_tour}</p>
                  {tour.lich_trinh && <p className="text-xs text-gray-400 truncate mt-0.5">{tour.lich_trinh}</p>}
                </td>
                <td className="px-3 py-2 text-xs text-gray-700 max-w-[140px]">
                  <span className="truncate block max-w-[140px]">{tour.cong_ty}</span>
                </td>
                <td className="px-3 py-2">
                  <EditableCell value={tour.thi_truong} onSave={(v) => mutation.mutate({ id: tour.id, patch: { thi_truong: v } })} />
                </td>
                <td className="px-3 py-2">
                  <EditableCell value={tour.tuyen_tour} onSave={(v) => mutation.mutate({ id: tour.id, patch: { tuyen_tour: v } })} />
                </td>
                <td className="px-3 py-2 text-xs text-gray-600 whitespace-nowrap">{tour.thoi_gian || "—"}</td>
                <td className="px-3 py-2 text-xs font-medium text-gray-900 whitespace-nowrap">
                  {tour.gia ? `${fmtVND(tour.gia)}` : tour.gia_raw || "—"}
                </td>
                <td className="px-3 py-2">
                  {tour.phan_khuc && <Badge className={segmentColor(tour.phan_khuc)}>{tour.phan_khuc}</Badge>}
                </td>
                <td className="px-3 py-2 text-xs text-gray-500">{tour.nguon}</td>
                <td className="px-3 py-2">
                  <EditableCell value={tour.analyst_note} onSave={(v) => mutation.mutate({ id: tour.id, patch: { analyst_note: v } })} />
                </td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => mutation.mutate({ id: tour.id, patch: { flagged: !tour.flagged } })}
                    className={cn("transition-colors", tour.flagged ? "text-amber-500 hover:text-amber-700" : "text-gray-300 hover:text-amber-400")}
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

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">
          Trang {page}/{totalPages} · {(data?.total ?? 0).toLocaleString("vi-VN")} kết quả
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
          <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="btn-secondary px-2 py-1.5 text-xs">
            <ChevronRight size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
