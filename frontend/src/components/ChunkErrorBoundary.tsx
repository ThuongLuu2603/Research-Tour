import { Component, type ErrorInfo, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";

// Khi deploy phiên bản mới, các file chunk (hash) cũ bị xoá. Tab đang mở bản cũ mà điều hướng
// sang trang chưa tải sẽ 404 chunk → import động fail → Suspense ném lỗi. Không có error boundary
// thì cả app trắng màn. Boundary này bắt lỗi đó và tự tải lại trang MỘT lần để lấy chunk mới.
//
// Chống lặp reload: dùng MỐC THỜI GIAN lần reload gần nhất (sessionStorage) thay vì cờ boolean.
// Cờ boolean bị xoá ở componentDidMount (fallback của Suspense commit TRƯỚC khi promise reject)
// nên không chặn được vòng lặp. Mốc thời gian thì không bị xoá khi mount, nên an toàn: nếu vừa
// reload trong RELOAD_WINDOW_MS mà vẫn lỗi → dừng và hiện nút "Tải lại" thủ công.

const RELOAD_TS_KEY = "chunk-reload-ts";
const RELOAD_WINDOW_MS = 12_000;
const CHUNK_ERR_RE =
  /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|ChunkLoadError|dynamically imported module/i;

function isChunkError(error: unknown): boolean {
  const msg = error instanceof Error ? error.message : String(error);
  return CHUNK_ERR_RE.test(msg);
}

interface Props {
  children: ReactNode;
}
interface State {
  hasError: boolean;
  isChunk: boolean;
  gaveUp: boolean; // đã reload mà vẫn lỗi (hoặc lỗi không phải chunk) → hiện fallback thủ công
}

export default class ChunkErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, isChunk: false, gaveUp: false };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { hasError: true, isChunk: isChunkError(error), gaveUp: false };
  }

  componentDidCatch(error: unknown, _info: ErrorInfo) {
    if (!isChunkError(error)) {
      this.setState({ gaveUp: true }); // lỗi render khác: không reload
      return;
    }
    let lastTs = 0;
    try {
      lastTs = Number(sessionStorage.getItem(RELOAD_TS_KEY)) || 0;
    } catch {
      /* ignore */
    }
    const now = Date.now();
    if (now - lastTs < RELOAD_WINDOW_MS) {
      // Vừa reload xong mà vẫn lỗi → ngừng để tránh lặp vô hạn.
      this.setState({ gaveUp: true });
      return;
    }
    try {
      sessionStorage.setItem(RELOAD_TS_KEY, String(now));
    } catch {
      /* ignore */
    }
    window.location.reload(); // tải lại 1 lần để lấy index.html + chunk mới
  }

  render() {
    const { hasError, isChunk, gaveUp } = this.state;
    if (!hasError) return this.props.children;

    // Lỗi chunk lần đầu, đang reload → spinner ngắn.
    if (isChunk && !gaveUp) {
      return (
        <div className="h-full min-h-[60vh] flex items-center justify-center">
          <div className="flex items-center gap-2 text-gray-500 text-sm">
            <RefreshCw size={18} className="animate-spin-slow" />
            Đang cập nhật phiên bản mới…
          </div>
        </div>
      );
    }

    // Đã reload mà vẫn lỗi, hoặc lỗi không phải do chunk → mời tải lại thủ công.
    return (
      <div className="h-full min-h-[60vh] flex items-center justify-center p-6">
        <div className="text-center max-w-sm">
          <p className="text-gray-800 font-semibold mb-1">Không tải được trang</p>
          <p className="text-gray-500 text-sm mb-4">
            Có lỗi khi tải nội dung. Vui lòng tải lại trang.
          </p>
          <button onClick={() => window.location.reload()} className="btn-primary mx-auto">
            <RefreshCw size={16} />
            Tải lại
          </button>
        </div>
      </div>
    );
  }
}
