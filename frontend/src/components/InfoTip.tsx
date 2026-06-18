import { HelpCircle } from "lucide-react";
import { useCallback, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

/**
 * Tooltip dùng chung — render qua PORTAL ra body + position:fixed nên KHÔNG bị
 * overflow của card/table cắt (lỗi cũ: absolute trong .overflow-auto bị clip "under table").
 * Vị trí tính từ rect của trigger: ưu tiên hiện phía trên; sát mép trên → lật xuống;
 * kẹp ngang trong viewport. `block` = trigger chiếm block (cho ô bảng truncate).
 */
export function Tooltip({
  content,
  children,
  width = 224,
  placement = "auto",
  block = false,
  className,
}: {
  content: ReactNode;
  children: ReactNode;
  width?: number;
  placement?: "auto" | "top" | "bottom";
  block?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number; below: boolean } | null>(null);

  const show = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const m = 8;
    let left = r.left + r.width / 2 - width / 2;
    left = Math.max(m, Math.min(left, window.innerWidth - width - m));
    const below = placement === "bottom" || (placement === "auto" && r.top < 140);
    setPos({ left, top: below ? r.bottom + 6 : r.top - 6, below });
  }, [width, placement]);
  const hide = useCallback(() => setPos(null), []);

  return (
    <span
      ref={ref}
      className={cn("relative", block ? "block max-w-full" : "inline-flex align-middle", className)}
      onMouseEnter={show}
      onMouseLeave={hide}
    >
      {children}
      {pos && createPortal(
        <span
          role="tooltip"
          style={{
            position: "fixed",
            left: pos.left,
            top: pos.top,
            width,
            transform: pos.below ? undefined : "translateY(-100%)",
            zIndex: 9999,
          }}
          className="pointer-events-none px-2.5 py-2 text-[11px] leading-snug text-white bg-gray-900 rounded-lg shadow-xl whitespace-normal text-left font-normal normal-case"
        >
          {content}
        </span>,
        document.body,
      )}
    </span>
  );
}

export function InfoTip({ text, className }: { text: string; className?: string }) {
  return (
    <Tooltip content={text} className={cn("ml-0.5", className)}>
      <HelpCircle size={13} className="text-gray-400 hover:text-primary-600 cursor-help shrink-0" />
    </Tooltip>
  );
}

export function ThTip({ label, tip }: { label: string; tip?: string }) {
  return (
    <span className="inline-flex items-center gap-0.5 whitespace-nowrap">
      {label}
      {tip ? <InfoTip text={tip} /> : null}
    </span>
  );
}

export function PageTitle({ title, tip }: { title: string; tip?: string }) {
  return (
    <h1 className="text-xl font-bold text-gray-900 inline-flex items-center gap-1.5">
      {title}
      {tip ? <InfoTip text={tip} /> : null}
    </h1>
  );
}
