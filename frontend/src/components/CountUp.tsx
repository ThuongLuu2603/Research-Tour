import { useCountUp } from "@/lib/useCountUp";

// Hiển thị số có hiệu ứng đếm. value=null → "—". decimals cho phần trăm lẻ, suffix ví dụ "%".
export function CountUp({
  value,
  decimals = 0,
  suffix = "",
  locale = true,
}: {
  value: number | null | undefined;
  decimals?: number;
  suffix?: string;
  locale?: boolean;
}) {
  const v = useCountUp(value);
  if (v == null) return <>—</>;
  const text =
    decimals > 0
      ? v.toFixed(decimals)
      : locale
        ? Math.round(v).toLocaleString("vi-VN")
        : String(Math.round(v));
  return (
    <>
      {text}
      {suffix}
    </>
  );
}
