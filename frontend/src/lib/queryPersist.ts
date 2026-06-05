import { dehydrate, hydrate, type QueryClient } from "@tanstack/react-query";

// Lưu cache React Query vào localStorage để lần vào sau hiển thị dữ liệu cũ NGAY LẬP TỨC,
// rồi refetch ngầm (stale-while-revalidate). Giúp app không bị "trắng màn mấy chục giây"
// khi dyno Render free vừa thức dậy / CockroachDB serverless đang khởi động.

const KEY = "rq-cache-v1";
const MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24h — quá cũ thì bỏ, tránh hiển thị số liệu lạc hậu
const MAX_BYTES = 3_000_000; // ~3MB, chừa chỗ cho localStorage (giới hạn ~5MB)

// Không lưu ra localStorage các query gắn với người dùng/quyền admin (tránh rò rỉ trên máy dùng chung).
// Dữ liệu còn lại là số liệu thị trường chung cho mọi người dùng đã đăng nhập.
const SENSITIVE_KEY_RE = /admin|workspace|member|user/i;

function isSensitiveKey(queryKey: readonly unknown[]): boolean {
  return queryKey.some((part) => typeof part === "string" && SENSITIVE_KEY_RE.test(part));
}

// build: ID của bản build hiện tại. Cache lưu từ bản build KHÁC sẽ bị bỏ — tránh hydrate
// dữ liệu schema cũ vào code mới (nguyên nhân khiến trang So sánh trắng màn sau deploy).
const BUILD_ID = typeof __APP_BUILD_ID__ !== "undefined" ? __APP_BUILD_ID__ : "dev";

type Persisted = { build: string; ts: number; state: ReturnType<typeof dehydrate> };

/** Xoá cache đã lưu (gọi khi đăng nhập/đăng xuất để không lẫn dữ liệu giữa các user). */
export function clearPersistedQueryCache(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

export function restoreQueryCache(client: QueryClient): void {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw) as Persisted;
    // Bỏ cache nếu: sai định dạng / khác bản build / quá cũ.
    if (!parsed?.state || parsed.build !== BUILD_ID || Date.now() - parsed.ts > MAX_AGE_MS) {
      localStorage.removeItem(KEY);
      return;
    }
    hydrate(client, parsed.state);
  } catch {
    try {
      localStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
  }
}

export function startQueryPersist(client: QueryClient): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null;

  const flush = () => {
    timer = null;
    try {
      // Chỉ lưu query đã thành công và KHÔNG nhạy cảm (bỏ admin/workspace/user…).
      const state = dehydrate(client, {
        shouldDehydrateQuery: (q) =>
          q.state.status === "success" && !isSensitiveKey(q.queryKey),
      });
      const payload = JSON.stringify({ build: BUILD_ID, ts: Date.now(), state } satisfies Persisted);
      if (payload.length > MAX_BYTES) return; // payload quá lớn → bỏ qua, không làm nghẽn localStorage
      localStorage.setItem(KEY, payload);
    } catch {
      /* quota / serialize lỗi → bỏ qua */
    }
  };

  const schedule = () => {
    if (timer) return;
    timer = setTimeout(flush, 1500); // debounce: gom nhiều thay đổi thành 1 lần ghi
  };

  const unsub = client.getQueryCache().subscribe(schedule);

  // Ghi nốt khi rời trang / chuyển tab ẩn.
  const onHide = () => {
    if (document.visibilityState === "hidden") flush();
  };
  document.addEventListener("visibilitychange", onHide);
  window.addEventListener("pagehide", flush);

  return () => {
    unsub();
    document.removeEventListener("visibilitychange", onHide);
    window.removeEventListener("pagehide", flush);
    if (timer) clearTimeout(timer);
  };
}
