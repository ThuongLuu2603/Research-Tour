import { useEffect, useRef, useState } from "react";

// Đếm số từ giá trị trước → giá trị mới (easeOutCubic). Có lý do rõ ràng: hút mắt vào KPI
// đầu trang và báo hiệu "số liệu vừa đổi" khi refetch. Tôn trọng prefers-reduced-motion.
export function useCountUp(target: number | null | undefined, duration = 650): number | null {
  const [val, setVal] = useState<number | null>(target ?? null);
  const fromRef = useRef(0);
  const rafRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (target == null) {
      setVal(null);
      return;
    }
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce || duration <= 0) {
      fromRef.current = target;
      setVal(target);
      return;
    }
    const from = fromRef.current;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setVal(from + (target - from) * eased);
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = target;
        setVal(target);
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [target, duration]);

  return val;
}
