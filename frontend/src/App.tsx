import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import Layout from "@/components/Layout";
import LoginPage from "@/pages/LoginPage";
import Dashboard from "@/pages/Dashboard";
import ResearchGrid from "@/pages/ResearchGrid";
import PriceAnalysis from "@/pages/PriceAnalysis";
import MarketShare from "@/pages/MarketShare";
import Competitor from "@/pages/Competitor";
import ScraperHub from "@/pages/ScraperHub";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  if (isLoading) return (
    <div className="h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center">
        <div className="text-4xl mb-3">✈️</div>
        <p className="text-gray-500 text-sm">Đang tải...</p>
      </div>
    </div>
  );
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/"
              element={
                <PrivateRoute>
                  <Layout />
                </PrivateRoute>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="data" element={<ResearchGrid />} />
              <Route path="price" element={<PriceAnalysis />} />
              <Route path="market" element={<MarketShare />} />
              <Route path="competitor" element={<Competitor />} />
              <Route path="scraper" element={<ScraperHub />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
