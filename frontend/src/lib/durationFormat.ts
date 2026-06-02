/** Chuẩn NĐ: 5N4Đ→5, 5N5Đ→5.5, 1N→1, 0.5N→0.5 (khớp backend/duration_format.py). */

export function formatDurationLabel(days: number | null | undefined): string {
  if (days == null || Number.isNaN(days)) return "—";
  const d = Math.round(days * 100) / 100;
  if (Math.abs(d - 0.5) < 0.01) return "0.5N";
  const n = Math.trunc(d);
  const frac = Math.round((d - n) * 100) / 100;
  if (Math.abs(frac - 0.5) < 0.01 && n >= 1) return `${n}N${n}Đ`;
  if (Math.abs(frac) < 0.01 && n >= 1) {
    if (n === 1) return "1N";
    return `${n}N${n - 1}Đ`;
  }
  if (Math.abs(frac) < 0.01) return `${n}N`;
  return `${d}N`;
}

export function parseDurationInput(text: string): number | null {
  const s = text.trim().toLowerCase().replace(/\s+/g, "").replace(/đ/g, "d");
  if (!s) return null;

  let m = s.match(/^(\d+(?:\.\d+)?)n(\d+)d$/);
  if (m) {
    const n = parseFloat(m[1]);
    const d = parseInt(m[2], 10);
    if (Number.isInteger(n) && d === n) return n + 0.5;
    return n;
  }
  m = s.match(/^(\d+(?:\.\d+)?)n$/);
  if (m) {
    const v = parseFloat(m[1]);
    return v > 0 && v <= 45 ? v : null;
  }
  const v = parseFloat(s.replace(",", "."));
  return Number.isFinite(v) && v > 0 && v <= 45 ? v : null;
}
