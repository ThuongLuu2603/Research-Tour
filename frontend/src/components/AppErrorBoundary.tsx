import { Component, type ErrorInfo, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import { clearPersistedQueryCache } from "@/lib/queryPersist";

// Lưới an toàn cấp cao nhất: nếu BẤT KỲ lỗi render nào lọt ra (kể cả dữ liệu cache cũ làm crash
// một trang), hiển thị màn hình phục hồi có nút Tải lại — KHÔNG bao giờ để app trắng màn.
// Nút Tải lại xoá cache localStorage trước rồi reload, nên dữ liệu hỏng không lặp lại.

interface Props {
  children: ReactNode;
}
interface State {
  hasError: boolean;
}

export default class AppErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("App error boundary:", error, info?.componentStack);
  }

  private handleReload = () => {
    clearPersistedQueryCache();
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 p-6">
        <div className="text-center max-w-sm animate-fade-in">
          <div className="mx-auto mb-4 w-14 h-14 rounded-2xl bg-primary-50 flex items-center justify-center">
            <RefreshCw size={24} className="text-primary-600" />
          </div>
          <p className="text-gray-900 font-semibold text-lg mb-1">Đã xảy ra lỗi hiển thị</p>
          <p className="text-gray-500 text-sm mb-5">
            Ứng dụng gặp sự cố khi tải dữ liệu. Hãy tải lại trang để tiếp tục.
          </p>
          <button onClick={this.handleReload} className="btn-primary mx-auto">
            <RefreshCw size={16} />
            Tải lại trang
          </button>
        </div>
      </div>
    );
  }
}
