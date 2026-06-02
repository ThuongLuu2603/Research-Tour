import type React from "react";
import { buildRouteKeywordConflicts, conflictHintForKeyword, parseRouteKeywordList } from "@/lib/rulesUnmatched";

export const ROUTE_DROP_KEYWORDS = [
  "bangkok", "pattaya", "phuket", "chiang mai", "thái lan", "thailand",
  "nhật bản", "tokyo", "osaka", "đài loan", "taiwan", "singapore", "malaysia",
  "hàn quốc", "seoul", "trung quốc", "châu âu", "paris", "dubai",
  "nong nooch", "coral", "safari", "wat arun", "baiyoke", "mexico", "canada", "cuba",
];

export function keywordForRouteDrop(dragged: string): string {
  const low = dragged.toLowerCase();
  let best = "";
  for (const h of ROUTE_DROP_KEYWORDS) {
    if (low.includes(h) && h.length > best.length) best = h;
  }
  if (best) return best;
  if (dragged.length <= 48) return dragged.trim();
  return "";
}

export function dropHandlers(
  targetKey: string,
  dropTarget: string | null,
  setDropTarget: (k: string | null) => void,
  onAssign: (alias: string) => void,
) {
  const active = dropTarget === targetKey;
  return {
    onDragOver: (e: React.DragEvent) => { e.preventDefault(); setDropTarget(targetKey); },
    onDragLeave: () => { if (dropTarget === targetKey) setDropTarget(null); },
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      setDropTarget(null);
      const alias = e.dataTransfer.getData("text/plain").trim();
      if (alias) onAssign(alias);
    },
    dropClassName: active ? "ring-2 ring-inset ring-primary-500 bg-primary-50" : "",
  };
}

export function dragAliasProps(value: string) {
  return {
    draggable: true,
    onDragStart: (e: React.DragEvent) => {
      e.dataTransfer.setData("text/plain", value);
      e.dataTransfer.effectAllowed = "copy";
    },
    className: "cursor-grab active:cursor-grabbing inline-flex items-center gap-1",
  };
}

export function RouteKeywordsCell({
  keywords,
  conflicts,
}: {
  keywords: string;
  conflicts: ReturnType<typeof buildRouteKeywordConflicts>;
}) {
  const parts = parseRouteKeywordList(keywords);
  if (!parts.length) return <span className="text-gray-400">—</span>;
  return (
    <span title="Tour phải chứa tất cả các từ sau (AND)">
      {parts.map((kw, i) => {
        const hint = conflictHintForKeyword(kw, conflicts);
        return (
          <span key={`${i}-${kw}`}>
            {i > 0 && <span className="text-gray-500 font-sans font-normal"> và </span>}
            <span className={hint ? "text-red-700 font-semibold underline decoration-dotted" : undefined} title={hint ?? undefined}>
              {kw}
            </span>
          </span>
        );
      })}
    </span>
  );
}
