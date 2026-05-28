import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmtVND(val: number | null | undefined): string {
  if (val == null) return "—";
  return new Intl.NumberFormat("vi-VN", { style: "decimal" }).format(val);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Hiển thị ngắn cột Phân khúc (hỗ trợ nhãn cũ trong DB). */
export function formatPhanKhuc(seg: string): string {
  if (!seg || seg === "Chưa có giá") return seg === "Chưa có giá" ? "—" : "";
  const s = seg.toLowerCase();
  if (s.startsWith("luxury")) return "Luxury";
  if (s.startsWith("premium")) return "Premium";
  if (s.startsWith("standard") || s.startsWith("budget") || s.startsWith("mid")) return "Standard";
  return seg;
}

export function segmentColor(seg: string): string {
  const short = formatPhanKhuc(seg) || seg;
  const map: Record<string, string> = {
    Standard: "bg-green-100 text-green-800",
    Premium: "bg-purple-100 text-purple-800",
    Luxury: "bg-amber-100 text-amber-800",
    "Chưa có giá": "bg-gray-100 text-gray-600",
  };
  return map[short] ?? "bg-gray-100 text-gray-600";
}

export function statusColor(status: string): string {
  const map: Record<string, string> = {
    success: "bg-green-100 text-green-800",
    running: "bg-blue-100 text-blue-800",
    pending: "bg-yellow-100 text-yellow-800",
    failed: "bg-red-100 text-red-800",
  };
  return map[status] ?? "bg-gray-100 text-gray-600";
}
