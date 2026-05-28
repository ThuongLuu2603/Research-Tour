/** Chuỗi lỗi từ FastAPI / axios (detail có thể là string hoặc mảng validation). */
export function formatApiError(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = e.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((x) => (typeof x === "object" && x && "msg" in x ? String((x as { msg: string }).msg) : String(x)))
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  if (e.message && !e.message.startsWith("timeout")) return e.message;
  return fallback;
}
