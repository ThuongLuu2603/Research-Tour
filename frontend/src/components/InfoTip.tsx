import { HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export function InfoTip({ text, className }: { text: string; className?: string }) {
  return (
    <span className={cn("relative inline-flex align-middle group/tip ml-0.5", className)}>
      <HelpCircle size={13} className="text-gray-400 hover:text-primary-600 cursor-help shrink-0" />
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-[calc(100%+6px)] left-1/2 -translate-x-1/2 w-56 px-2.5 py-2 text-[11px] leading-snug text-white bg-gray-900 rounded-lg shadow-lg opacity-0 invisible group-hover/tip:opacity-100 group-hover/tip:visible z-50 whitespace-normal text-left font-normal normal-case"
      >
        {text}
      </span>
    </span>
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
