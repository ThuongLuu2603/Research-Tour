import axios from "axios";

const api = axios.create({ baseURL: "/api" });

// Attach token from localStorage
api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem("access_token");
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  return cfg;
});

// Redirect to login on 401
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("access_token");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export default api;

// ── Auth ─────────────────────────────────────────────────────────────────────

export interface User { id: number; username: string; display_name: string; role?: string; avatar_url?: string }

export const login = async (username: string, password: string): Promise<{ access_token: string; user: User }> => {
  const form = new FormData();
  form.append("username", username);
  form.append("password", password);
  const { data } = await api.post("/auth/login", form);
  return data;
};

export const getMe = async (): Promise<User> => {
  const { data } = await api.get("/auth/me");
  return data;
};

export const updateProfile = async (patch: { display_name?: string; avatar_url?: string }): Promise<User> => {
  const { data } = await api.patch("/auth/profile", patch);
  return data;
};

export const changePassword = async (current_password: string, new_password: string) => {
  const { data } = await api.post("/auth/change-password", { current_password, new_password });
  return data;
};

export interface AdminUser {
  id: number; username: string; display_name: string; role: string;
  avatar_url: string; is_active: boolean; last_login: string | null;
}

export const listUsers = async (): Promise<AdminUser[]> => {
  const { data } = await api.get("/admin/users");
  return data;
};

export const createUser = async (username: string, password: string, display_name: string, role: string) => {
  const { data } = await api.post("/admin/users", { username, password, display_name, role });
  return data;
};

export const updateUser = async (id: number, patch: Partial<{ display_name: string; role: string; is_active: boolean; password: string }>) => {
  const { data } = await api.patch(`/admin/users/${id}`, patch);
  return data;
};

// ── Tours ─────────────────────────────────────────────────────────────────────

export interface Tour {
  id: number; cong_ty: string; thi_truong: string; tuyen_tour: string;
  ten_tour: string; lich_trinh: string; diem_kh: string; thoi_gian: string;
  gia: number | null; gia_raw: string; lich_kh: string; link_url: string;
  ma_tour: string; khach_san: string; hang_khong: string; so_ngay: number | null;
  phan_khuc: string; nguon: string; analyst_note: string; flagged: boolean;
}

export interface PaginatedTours { items: Tour[]; total: number; page: number; page_size: number }

export interface TourFilters {
  page?: number; page_size?: number; search?: string;
  thi_truong?: string[]; tuyen_tour?: string[]; cong_ty?: string[];
  diem_kh?: string[]; nguon?: string[]; phan_khuc?: string[];
  flagged?: boolean; gia_min?: number; gia_max?: number;
  sort_by?: string; sort_dir?: string;
}

export const getTours = async (filters: TourFilters = {}): Promise<PaginatedTours> => {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v === undefined || v === null) return;
    if (Array.isArray(v)) v.forEach((item) => params.append(k, item));
    else params.append(k, String(v));
  });
  const { data } = await api.get(`/tours?${params}`);
  return data;
};

export const getFilterOptions = async () => {
  const { data } = await api.get("/tours/filter-options");
  return data;
};

export const patchTour = async (id: number, patch: Partial<Tour>) => {
  const { data } = await api.patch(`/tours/${id}`, patch);
  return data;
};

export const exportUrl = (type: "csv" | "excel", params: Record<string, string>) => {
  const p = new URLSearchParams(params);
  return `/api/tours/export/${type}?${p}&access_token=${localStorage.getItem("access_token")}`;
};

// ── Analytics ─────────────────────────────────────────────────────────────────

export const getKPI = async (nguon?: string[]) => {
  const p = nguon?.map((n) => `nguon=${encodeURIComponent(n)}`).join("&") ?? "";
  const { data } = await api.get(`/analytics/kpi${p ? "?" + p : ""}`);
  return data;
};

export const getByMarket = async (nguon?: string[]) => {
  const p = nguon?.map((n) => `nguon=${encodeURIComponent(n)}`).join("&") ?? "";
  const { data } = await api.get(`/analytics/by-market${p ? "?" + p : ""}`);
  return data;
};

export const getByCompany = async (nguon?: string[]) => {
  const p = nguon?.map((n) => `nguon=${encodeURIComponent(n)}`).join("&") ?? "";
  const { data } = await api.get(`/analytics/by-company?limit=15${p ? "&" + p : ""}`);
  return data;
};

export const getBySegment = async (nguon?: string[]) => {
  const p = nguon?.map((n) => `nguon=${encodeURIComponent(n)}`).join("&") ?? "";
  const { data } = await api.get(`/analytics/by-segment${p ? "?" + p : ""}`);
  return data;
};

export const getScatterData = async (nguon?: string[]) => {
  const p = nguon?.map((n) => `nguon=${encodeURIComponent(n)}`).join("&") ?? "";
  const { data } = await api.get(`/analytics/scatter${p ? "?" + p : ""}`);
  return data;
};

export const getPriceStats = async (groupBy = "thi_truong", nguon?: string[]) => {
  const p = nguon?.map((n) => `nguon=${encodeURIComponent(n)}`).join("&") ?? "";
  const { data } = await api.get(`/analytics/price-stats?group_by=${groupBy}${p ? "&" + p : ""}`);
  return data;
};

export const getTreemap = async (nguon?: string[]) => {
  const p = nguon?.map((n) => `nguon=${encodeURIComponent(n)}`).join("&") ?? "";
  const { data } = await api.get(`/analytics/treemap${p ? "?" + p : ""}`);
  return data;
};

export interface MarketIntelRow {
  label: string;
  tour_count: number;
  departure_monthly: number;
  departure_share_pct?: number;
  tour_share_pct?: number;
  avg_price: number | null;
  avg_days: number | null;
  avg_price_day: number | null;
  market_price: number | null;
  is_vietravel?: boolean;
}

export interface MarketIntelligence {
  methodology: string;
  totals: { tours: number; departure_monthly: number; markets: number; companies: number };
  vietravel: MarketIntelRow;
  market_avg: MarketIntelRow;
  markets: MarketIntelRow[];
  companies: MarketIntelRow[];
  routes: Array<MarketIntelRow & { thi_truong: string; tuyen_tour: string }>;
}

export const getMarketIntelligence = async (nguon?: string[]): Promise<MarketIntelligence> => {
  const p = nguon?.map((n) => `nguon=${encodeURIComponent(n)}`).join("&") ?? "";
  const { data } = await api.get(`/analytics/market-intelligence${p ? "?" + p : ""}`);
  return data;
};

export const getCompetitorProfile = async (company: string) => {
  const { data } = await api.get(`/analytics/competitor/${encodeURIComponent(company)}`);
  return data;
};

// ── Scraper ───────────────────────────────────────────────────────────────────

export interface ScrapeJob {
  id: number; scraper_name: string; status: string; progress_pct: number;
  message: string; tours_added: number; tours_updated: number; tours_total: number;
  triggered_by: string; started_at: string; finished_at: string | null;
}

export const triggerScrape = async (scraper: "vietravel" | "findtourgo"): Promise<ScrapeJob> => {
  const { data } = await api.post("/scraper/trigger", { scraper });
  return data;
};

export const getScrapeJobs = async (): Promise<ScrapeJob[]> => {
  const { data } = await api.get("/scraper/jobs");
  return data;
};

export const getScrapeJob = async (id: number): Promise<ScrapeJob> => {
  const { data } = await api.get(`/scraper/jobs/${id}`);
  return data;
};

export const getSchedule = async () => {
  const { data } = await api.get("/scraper/schedule");
  return data;
};

export const updateSchedule = async (hour: number, minute: number) => {
  const { data } = await api.post("/scraper/schedule", { hour, minute });
  return data;
};

// ── Admin / Data sync ─────────────────────────────────────────────────────────

export interface DataStatus {
  total: number;
  breakdown: Record<string, number>;
  expected_min: Record<string, number>;
  complete: boolean;
  import?: {
    running: boolean;
    message: string;
    current_source: string;
    rows_done: number;
    error: string | null;
  };
}

export const getDataStatus = async (): Promise<DataStatus> => {
  const { data } = await api.get("/admin/data-status");
  return data;
};

export const syncSheetData = async () => {
  const { data } = await api.post("/admin/sync-data");
  return data;
};

// ── Compare (Vietravel vs market) ─────────────────────────────────────────────

export interface CompareSummary {
  company: string;
  total_vietravel_tours: number;
  total_market_tours: number;
  segments_with_vietravel: number;
  cheaper_count: number;
  expensive_count: number;
  similar_count: number;
  avg_gap_pct: number | null;
  vtr_freq_monthly_total: number;
  market_freq_monthly_total: number;
  freq_leading_segments: number;
  freq_lagging_segments: number;
  methodology: string;
}

export interface CompareSegment {
  segment_key: string;
  tuyen_tour: string;
  diem_kh: string;
  so_ngay: number;
  thi_truong: string;
  vietravel_avg_price: number | null;
  vietravel_avg_days: number | null;
  vietravel_min_price: number | null;
  vietravel_min_link: string;
  vietravel_min_tour: string;
  market_total_price: number | null;
  comparison_price: number | null;
  market_min_price: number | null;
  market_min_link: string;
  market_min_tour: string;
  market_min_company: string;
  market_avg_day: number | null;
  market_avg_days: number | null;
  vietravel_avg_day: number | null;
  gap_pct: number | null;
  vietravel_count: number;
  market_count: number;
  vietravel_freq_monthly: number;
  market_freq_monthly: number;
  market_freq_avg_per_company: number | null;
  freq_gap_pct: number | null;
  position: string;
  freq_position: string;
  top_competitors: Array<{ cong_ty: string; tour_count: number; freq_monthly: number; avg_price_day: number | null }>;
}

export interface CompareFilters {
  thi_truong?: string[];
  tuyen_tour?: string;
  diem_kh?: string;
  sort_by?: string;
  limit?: number;
}

const buildCompareParams = (filters: CompareFilters = {}) => {
  const params = new URLSearchParams();
  filters.thi_truong?.forEach((m) => params.append("thi_truong", m));
  if (filters.tuyen_tour) params.set("tuyen_tour", filters.tuyen_tour);
  if (filters.diem_kh) params.set("diem_kh", filters.diem_kh);
  if (filters.sort_by) params.set("sort_by", filters.sort_by);
  if (filters.limit) params.set("limit", String(filters.limit));
  return params.toString();
};

export const getCompareSummary = async (filters: CompareFilters = {}): Promise<CompareSummary> => {
  const q = buildCompareParams(filters);
  const { data } = await api.get(`/compare/summary${q ? "?" + q : ""}`);
  return data;
};

export const getCompareSegments = async (filters: CompareFilters = {}) => {
  const q = buildCompareParams(filters);
  const { data } = await api.get(`/compare/segments${q ? "?" + q : ""}`);
  return data as { methodology: string; items: CompareSegment[]; total: number };
};

export const getSegmentDetail = async (segmentKey: string) => {
  const { data } = await api.get(`/compare/segment-detail?segment_key=${encodeURIComponent(segmentKey)}`);
  return data;
};

export const getSegmentTours = async (segmentKey: string) => {
  const { data } = await api.get(`/compare/segment-tours?segment_key=${encodeURIComponent(segmentKey)}`);
  return data;
};

export const getCompareCompetitors = async (filters: CompareFilters = {}) => {
  const q = buildCompareParams(filters);
  const { data } = await api.get(`/compare/competitors${q ? "?" + q : ""}`);
  return data as { items: Array<{ cong_ty: string; tour_count: number; overlap_segments: number; freq_monthly: number; avg_price_day: number | null }>; total: number };
};

export const getCompareCompetitorDetail = async (company: string, filters: CompareFilters = {}) => {
  const q = buildCompareParams(filters);
  const { data } = await api.get(`/compare/competitor/${encodeURIComponent(company)}${q ? "?" + q : ""}`);
  return data;
};

// ── Classification rules (admin) ──────────────────────────────────────────────

export interface MarketRule {
  id: number; market: string; keyword: string; active: boolean; sort_order: number;
}

export interface RouteRule {
  id: number; thi_truong: string; tuyen_tour: string; keywords: string; active: boolean; sort_order: number;
}

export const listMarketRules = async (): Promise<MarketRule[]> => {
  const { data } = await api.get("/admin/rules/market");
  return data;
};

export const createMarketRule = async (body: { market: string; keyword: string }) => {
  const { data } = await api.post("/admin/rules/market", body);
  return data;
};

export const deleteMarketRule = async (id: number) => {
  const { data } = await api.delete(`/admin/rules/market/${id}`);
  return data;
};

export const listRouteRules = async (): Promise<RouteRule[]> => {
  const { data } = await api.get("/admin/rules/route");
  return data;
};

export const createRouteRule = async (body: { thi_truong: string; tuyen_tour: string; keywords: string }) => {
  const { data } = await api.post("/admin/rules/route", body);
  return data;
};

export const deleteRouteRule = async (id: number) => {
  const { data } = await api.delete(`/admin/rules/route/${id}`);
  return data;
};

export const seedMarketDefaults = async () => {
  const { data } = await api.post("/admin/rules/seed-market-defaults");
  return data;
};

export const syncRouteFromSheet = async () => {
  const { data } = await api.post("/admin/rules/sync-route-from-sheet");
  return data;
};

export const syncRouteToSheet = async () => {
  const { data } = await api.post("/admin/rules/sync-route-to-sheet");
  return data;
};

export const syncMarketFromSheet = async () => {
  const { data } = await api.post("/admin/rules/sync-market-from-sheet");
  return data;
};

export const syncMarketToSheet = async () => {
  const { data } = await api.post("/admin/rules/sync-market-to-sheet");
  return data;
};

export const syncAllFromSheet = async () => {
  const { data } = await api.post("/admin/rules/sync-all-from-sheet");
  return data;
};

export const syncAllToSheet = async () => {
  const { data } = await api.post("/admin/rules/sync-all-to-sheet");
  return data;
};
