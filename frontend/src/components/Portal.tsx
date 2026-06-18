import { createPortal } from "react-dom";
import type { ReactNode } from "react";

/**
 * Render children ra thẳng document.body — popup/modal position:fixed sẽ ghim theo
 * VIEWPORT (giữa màn hình) thay vì bị một ancestor có transform (animation page-enter,
 * scale, will-change…) biến thành containing block → đẩy modal xuống dưới document.
 */
export function Portal({ children }: { children: ReactNode }) {
  return createPortal(children, document.body);
}
