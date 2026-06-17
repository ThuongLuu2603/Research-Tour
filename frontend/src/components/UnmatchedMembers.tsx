import { useState } from "react";
import type { UnmatchedTourMember } from "@/lib/api";

/**
 * Danh sách tour mẫu cho panel «Chưa khớp» — tên tour + link (mở tab mới) + công ty.
 * Dùng chung cho mọi tab (Tuyến tour / Công ty / Điểm KH / Thời gian / Ngày KH) để
 * admin xem & quyết định gán trước khi chuẩn hóa alias.
 */
export function UnmatchedMembers({
  members,
  itemKey,
  limit = 15,
  tone = "amber",
}: {
  members?: UnmatchedTourMember[];
  itemKey: string;
  limit?: number;
  tone?: "amber" | "gray";
}) {
  const [open, setOpen] = useState(false);
  const list = members ?? [];
  if (list.length === 0) return null;
  const btnColor = tone === "amber" ? "text-amber-700" : "text-primary-600";
  const liBg = tone === "amber" ? "bg-amber-100" : "bg-white";
  return (
    <div onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className={`text-[10px] ${btnColor} hover:underline mt-0.5 block`}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
      >
        {open ? "▲ Ẩn mẫu" : `▼ Xem ${list.length} tour mẫu`}
      </button>
      {open && (
        <ul className="mt-1 space-y-0.5 text-[10px] text-gray-600 font-sans">
          {list.slice(0, limit).map((m, i) => (
            <li key={i} className={`flex items-start gap-1 ${liBg} rounded px-1 py-0.5`}>
              <span className="text-amber-600 shrink-0">·</span>
              {m.link_url ? (
                <a
                  href={m.link_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary-600 hover:underline break-words"
                  title={m.title}
                >
                  {m.title || "(không tên)"}
                </a>
              ) : (
                <span className="break-words" title={m.title}>
                  {m.title || "(không tên)"}
                </span>
              )}
              {m.cong_ty && <span className="text-gray-400 shrink-0">· {m.cong_ty}</span>}
              {m.count > 1 && <span className="text-gray-400 shrink-0">×{m.count}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
