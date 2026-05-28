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

export function segmentColor(seg: string): string {
  const map: Record<string, string> = {
    "Standard (<−30% TB/ngày TT)": "bg-green-100 text-green-800",
    "Premium (±30% TB/ngày TT)": "bg-purple-100 text-purple-800",
    "Luxury (>+30% TB/ngày TT)": "bg-amber-100 text-amber-800",
    "Budget (<2tr)": "bg-green-100 text-green-800",
    "Mid (2–5tr)": "bg-blue-100 text-blue-800",
    "Premium (5–15tr)": "bg-purple-100 text-purple-800",
    "Luxury (>15tr)": "bg-amber-100 text-amber-800",
    "Chưa có giá": "bg-gray-100 text-gray-600",
  };
  if (seg.startsWith("Standard")) return map["Standard (<−30% TB/ngày TT)"];
  if (seg.startsWith("Premium (±")) return map["Premium (±30% TB/ngày TT)"];
  if (seg.startsWith("Luxury (>+")) return map["Luxury (>+30% TB/ngày TT)"];
  return map[seg] ?? "bg-gray-100 text-gray-600";
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
