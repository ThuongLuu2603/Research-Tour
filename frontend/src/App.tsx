import { useEffect, lazy, Suspense } from "react";
import { Plane } from "lucide-react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { restoreQueryCache, startQueryPersist } from "@/lib/queryPersist";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import AppErrorBoundary from "@/components/AppErrorBoundary";
import Layout from "@/components/Layout";
import LoginPage from "@/pages/LoginPage";

// Tách code theo route — trang nặng (biểu đồ recharts) chỉ tải khi mở, giảm bundle lần đầu.
const IntelligenceHome = lazy(() => import("@/pages/IntelligenceHome"));
const ResearchGrid = lazy(() => import("@/pages/ResearchGrid"));
const VietravelCompare = lazy(() => import("@/pages/VietravelCompare"));
const ReportsPage = lazy(() => import("@/pages/ReportsPage"));
const ScraperHub = lazy(() => import("@/pages/ScraperHub"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));
const RulesAdminPage = lazy(() => import("@/pages/RulesAdminPage"));
const MarketLab = lazy(() => import("@/pages/MarketLab"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 90_000,
      // Giữ dữ liệu trong cache lâu (24h) để bản persist localStorage còn ý nghĩa
      // và chuyển trang qua lại không phải gọi lại API.
      gcTime: 24 * 60 * 60 * 1000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

// Khôi phục cache đã lưu NGAY trước khi render lần đầu → có dữ liệu hiển thị tức thì.
restoreQueryCache(queryClient);

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  if (isLoading) return (
    <div className="h-screen flex items-center justify-center bg-gradient-to-br from-primary-700 to-primary-900">
      <div className="text-center animate-fade-in">
        <div className="relative inline-flex items-center justify-center w-16 h-16 mb-4">
          <span className="absolute inset-0 rounded-2xl bg-accent-400/20 blur-xl animate-pulse-soft" />
          <span className="relative w-16 h-16 rounded-2xl glass flex items-center justify-center animate-float">
            <Plane size={28} className="text-white" />
          </span>
        </div>
        <p className="text-blue-100 text-sm">Đang tải…</p>
      </div>
    </div>
  );
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  useEffect(() => startQueryPersist(queryClient), []);
  return (
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<PrivateRoute><Layout /></PrivateRoute>}>
              <Route index element={<IntelligenceHome />} />
              <Route path="data" element={<ResearchGrid />} />
              <Route path="compare" element={<VietravelCompare />} />
              <Route path="market-lab" element={<MarketLab />} />
              <Route path="reports" element={<ReportsPage />} />
              <Route path="ops" element={<ScraperHub />} />
              <Route path="scraper" element={<Navigate to="/ops" replace />} />
              <Route path="rules" element={<RulesAdminPage />} />
              <Route path="settings" element={<SettingsPage />} />
              {/* Legacy redirects */}
              <Route path="price" element={<Navigate to="/compare?tab=price" replace />} />
              <Route path="market" element={<Navigate to="/compare?tab=overview" replace />} />
              <Route path="competitor" element={<Navigate to="/compare?tab=competitors" replace />} />
              <Route path="dashboard" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </AppErrorBoundary>
  );
}
