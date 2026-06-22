import axios from "axios";
import { clearPersistedQueryCache } from "@/lib/queryPersist";

const api = axios.create({ baseURL: "/api" });

const compareApi = axios.create({ baseURL: "/api", timeout: 180_000 });
const marketLabApi = axios.create({ baseURL: "/api", timeout: 180_000 });
marketLabApi.interceptors.request.use((cfg) => {
  const token = localStorage.getItem("access_token");
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  return cfg;
});
marketLabApi.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("access_token");
      clearPersistedQueryCache();
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);
compareApi.interceptors.request.use((cfg) => {
  const token = localStorage.getItem("access_token");
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  return cfg;
});
compareApi.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("access_token");
      clearPersistedQueryCache();
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

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
      clearPersistedQueryCache();
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
  // id là string vì CockroachDB unique_rowid() > 2^53 (JS MAX_SAFE_INTEGER).
  // Number sẽ round mất last digits → PATCH bị 404 "Tour không tồn tại".
  id: string; external_id?: string; cong_ty: string; thi_truong: string; tuyen_tour: string;
  ten_tour: string; lich_trinh: string; diem_kh: string; thoi_gian: string;
  gia: number | null; gia_raw: string; lich_kh: string; link_url: string;
  ma_tour: string; khach_san: string; hang_khong: string; so_ngay: number | null;
  phan_khuc: string; dong_tour?: string; nguon: string; analyst_note: string; flagged: boolean;
  has_override?: boolean; canonical_id?: number;
  manual_locked?: boolean;  // admin đã chỉnh TT/Tuyến/Thời gian → ghi thẳng DB + khóa
  freq_monthly?: number;    // TB tần suất đoàn KH/tháng (tính từ lich_kh qua rule)
  sheet_sync?: { ok: boolean; message: string; row?: number } | null;
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

export interface TourFilterOptions {
  thi_truong: string[];
  tuyen_tour: string[];
  routes_by_market: Record<string, string[]>;
  cong_ty: string[];
  diem_kh: string[];
  nguon: string[];
  phan_khuc: string[];
}

export const getFilterOptions = async (): Promise<TourFilterOptions> => {
  const { data } = await api.get("/tours/filter-options");
  return data;
};

export const patchTour = async (id: string, patch: Partial<Tour>): Promise<Tour> => {
  const { data } = await api.patch(`/tours/${id}`, patch);
  return data;
};

const sheetSyncApi = axios.create({ baseURL: "/api", timeout: 300_000 });
sheetSyncApi.interceptors.request.use((cfg) => {
  const token = localStorage.getItem("access_token");
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  return cfg;
});
sheetSyncApi.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("access_token");
      clearPersistedQueryCache();
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export type SheetSyncSourceResult = {
  nguon: string;
  updated?: number;
  inserted?: number;
  deleted?: number;
  error?: string;
};

export type SheetSyncResult = {
  sources: SheetSyncSourceResult[];
  total_updated: number;
  total_inserted: number;
  total_deleted?: number;
  phan_khuc?: { updated?: number; route_buckets?: number; error?: string };
  ok?: boolean;
  errors?: SheetSyncSourceResult[];
};

/** Kéo Sheet → DB theo từng tab (tránh timeout Render khi Main ~9k dòng). */
export const syncToursFromGoogleSheet = async (): Promise<SheetSyncResult> => {
  const order = ["Vietravel", "Main"] as const;
  const sources: SheetSyncSourceResult[] = [];
  let total_updated = 0;
  let total_inserted = 0;
  let total_deleted = 0;
  for (const nguon of order) {
    // recompute=false cho từng tab → chỉ tính lại phân khúc 1 lần ở cuối (tránh chạy 3 lần).
    const { data } = await sheetSyncApi.post<SheetSyncSourceResult>(
      `/admin/sync-sheet-source?nguon=${encodeURIComponent(nguon)}&recompute=false`
    );
    sources.push(data);
    if (data.error) break;
    total_updated += data.updated ?? 0;
    total_inserted += data.inserted ?? 0;
    total_deleted += data.deleted ?? 0;
  }
  const { data: phan_khuc } = await sheetSyncApi.post<{ updated?: number; route_buckets?: number }>(
    "/admin/recompute-phan-khuc"
  );
  const errors = sources.filter((s) => s.error);
  return {
    sources,
    total_updated,
    total_inserted,
    total_deleted,
    phan_khuc,
    ok: errors.length === 0,
    errors,
  };
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
  avg_departures_per_month?: number;
  departure_share_pct?: number;
  tour_share_pct?: number;
  avg_price: number | null;
  median_price?: number | null;
  avg_days: number | null;
  avg_price_day: number | null;
  market_price: number | null;
  is_vietravel?: boolean;
}

export interface MarketIntelligence {
  methodology: string;
  totals: { tours: number; departure_monthly: number; avg_departures_per_month?: number; markets: number; companies: number };
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
  // id là CHUỖI (CockroachDB unique_rowid > 2^53, number sẽ làm tròn → cancel sai id)
  id: string; scraper_name: string; status: string; progress_pct: number;
  message: string; tours_added: number; tours_updated: number; tours_total: number;
  triggered_by: string; started_at: string; finished_at: string | null;
}

// scraper: "vietravel" | "findtourgo" | <key của site extra> (xem listExtraSources)
export const triggerScrape = async (scraper: string): Promise<ScrapeJob> => {
  const { data } = await api.post("/scraper/trigger", { scraper });
  return data;
};

// ── Extra sources (website tour khác) ──────────────────────────────────────────
export interface ExtraSource {
  key: string;
  name: string;
  enabled: boolean;
  last_status: string | null;
  last_run_at: string | null;
  last_count: number | null;
}

export const listExtraSources = async (): Promise<ExtraSource[]> => {
  const { data } = await api.get("/scraper/extra-sources");
  return Array.isArray(data) ? data : [];
};

export const toggleExtraSource = async (
  key: string,
  enabled: boolean,
): Promise<{ key: string; enabled: boolean }> => {
  const { data } = await api.post(`/scraper/extra-sources/${key}/toggle`, { enabled });
  return data;
};

export const getScrapeJobs = async (): Promise<ScrapeJob[]> => {
  const { data } = await api.get("/scraper/jobs");
  return data;
};

export const cancelScrapeJob = async (jobId: string) => {
  const { data } = await api.post(`/scraper/jobs/${jobId}/cancel`);
  return data as { message: string; job_id: string };
};

export const reconcileStaleScrapeJobs = async () => {
  const { data } = await api.post("/scraper/jobs/reconcile-stale");
  return data as { message: string; fixed_ids: number[] };
};

export const getScrapeJob = async (id: string): Promise<ScrapeJob> => {
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
    rows_total?: number;
    progress_pct?: number;
    job_id?: string | number | null;
    error: string | null;
  };
}

export const getDataStatus = async (): Promise<DataStatus> => {
  const { data } = await api.get("/admin/data-status");
  return data;
};

/** Đồng bộ tab Main từ Google Sheet (live) → DB + matcher. */
export const syncMainSheetLive = async () => {
  const { data } = await api.post("/admin/sync-main-sheet-live");
  return data;
};

/** Đồng bộ tab Vietravel từ Google Sheet (live) → DB. Dùng khi user edit thủ
 *  công trực tiếp trên tab Vietravel của sheet (auto-chain KHÔNG chạy bước này
 *  vì Vietravel scrape đã ghi DB trước → tránh round-trip vô nghĩa). */
export const syncVietravelFromSheet = async () => {
  const { data } = await sheetSyncApi.post(
    `/admin/sync-sheet-source?nguon=Vietravel&recompute=true`,
  );
  return data;
};

/** Import CSV gói khi deploy — không dùng khi Sheet đã cập nhật hàng ngày. */
export const syncBundledCsvImport = async () => {
  const { data } = await api.post("/admin/sync-data");
  return data;
};

// ── Compare (Vietravel vs market) ─────────────────────────────────────────────

export interface CompareSummary {
  company: string;
  total_vietravel_tours: number;
  vietravel_tab_tours: number;
  total_market_tours: number;
  segments_with_vietravel: number;
  segments_comparable?: number;
  cheaper_count: number;
  expensive_count: number;
  similar_count: number;
  avg_gap_pct: number | null;
  vtr_freq_monthly_total: number;
  vtr_avg_departures_per_month?: number | null;
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
  market_min_has_link?: boolean;
  vtr_comparison_period?: string;
  market_count_in_period?: number;
  market_avg_day: number | null;
  market_avg_days: number | null;
  vietravel_avg_day: number | null;
  gap_pct: number | null;
  vietravel_count: number;
  market_count: number;
  vietravel_freq_monthly: number;
  vtr_avg_departures_per_month?: number;
  market_freq_monthly: number;
  market_freq_avg_per_company: number | null;
  top_freq_competitor?: string;
  top_freq_competitor_departures?: number | null;
  freq_gap_pct: number | null;
  freq_gap_vs_avg_pct: number | null;
  position: string;
  freq_position: string;
  top_competitors: Array<{ cong_ty: string; tour_count: number; freq_monthly: number; avg_price_day: number | null }>;
}

export interface CompareFilters {
  thi_truong?: string[];
  tuyen_tour?: string;
  diem_kh?: string;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
  limit?: number;
}

const buildCompareParams = (filters: CompareFilters = {}) => {
  const params = new URLSearchParams();
  filters.thi_truong?.forEach((m) => params.append("thi_truong", m));
  if (filters.tuyen_tour) params.set("tuyen_tour", filters.tuyen_tour);
  if (filters.diem_kh) params.set("diem_kh", filters.diem_kh);
  if (filters.sort_by) params.set("sort_by", filters.sort_by);
  if (filters.sort_dir) params.set("sort_dir", filters.sort_dir);
  if (filters.limit) params.set("limit", String(filters.limit));
  return params.toString();
};

export const getCompareFilterOptions = async () => {
  const { data } = await compareApi.get("/compare/filter-options");
  return data as {
    thi_truong: string[];
    tuyen_tour: string[];
    diem_kh: string[];
    routes_by_market: Record<string, string[]>;
  };
};

export const getCompareClassificationGaps = async (filters: CompareFilters = {}) => {
  const q = buildCompareParams(filters);
  const { data } = await compareApi.get(`/compare/classification-gaps${q ? "?" + q : ""}`);
  return data as {
    cong_ty: Array<{ value: string; count: number }>;
    diem_kh: Array<{ value: string; count: number }>;
    thoi_gian: Array<{ value: string; count: number }>;
  };
};

export const getCompareSummary = async (filters: CompareFilters = {}): Promise<CompareSummary> => {
  const q = buildCompareParams(filters);
  const { data } = await compareApi.get(`/compare/summary${q ? "?" + q : ""}`);
  return data;
};

export const getCompareSegments = async (filters: CompareFilters = {}) => {
  const q = buildCompareParams(filters);
  const { data } = await compareApi.get(`/compare/segments${q ? "?" + q : ""}`);
  return data as { methodology: string; items: CompareSegment[]; total: number };
};

export interface WeekdayDistributionRow {
  weekday: string;
  weekday_index: number;
  departures_monthly: number;
  share_pct: number;
}

export interface WeekdayDistribution {
  labels: string[];
  vietravel: WeekdayDistributionRow[];
  market: WeekdayDistributionRow[];
  vietravel_total: number;
  market_total: number;
  vietravel_tour_count: number;
  market_tour_count: number;
}

export const getCompareWeekdayDistribution = async (filters: CompareFilters = {}): Promise<WeekdayDistribution> => {
  const q = buildCompareParams(filters);
  const { data } = await compareApi.get(`/compare/weekday-distribution${q ? "?" + q : ""}`);
  return data;
};

export const getSegmentDetail = async (segmentKey: string) => {
  const { data } = await compareApi.get(`/compare/segment-detail?segment_key=${encodeURIComponent(segmentKey)}`);
  return data;
};

export const getSegmentTours = async (segmentKey: string) => {
  const { data } = await compareApi.get(`/compare/segment-tours?segment_key=${encodeURIComponent(segmentKey)}`);
  return data;
};

export const getCompareCompetitors = async (filters: CompareFilters = {}) => {
  const q = buildCompareParams(filters);
  const { data } = await compareApi.get(`/compare/competitors${q ? "?" + q : ""}`);
  return data as { items: Array<{ cong_ty: string; tour_count: number; overlap_segments: number; freq_monthly: number; avg_price_day: number | null; score: number }>; total: number };
};

export const getCompareCompetitorDetail = async (company: string, filters: CompareFilters = {}) => {
  const q = buildCompareParams(filters);
  // company qua query param (encode) — tránh 404 khi tên có '/', '&'… trên path
  const params = new URLSearchParams(q);
  params.set("company", company);
  const { data } = await compareApi.get(`/compare/competitor?${params.toString()}`);
  return data;
};

// ── Classification rules (admin) ──────────────────────────────────────────────

export interface MarketRule {
  // id là string vì CockroachDB unique_rowid() > 2^53 — JS làm tròn → DELETE sai id.
  // Backend đã serialize bằng field_serializer("id") trong api/rules.py.
  id: string; market: string; keyword: string; active: boolean; sort_order: number;
}

export interface RouteRule {
  id: string; thi_truong: string; tuyen_tour: string; keywords: string; active: boolean; priority: boolean; sort_order: number;
}

export const listMarketRules = async (): Promise<MarketRule[]> => {
  const { data } = await api.get("/admin/rules/market");
  return data;
};

export const createMarketRule = async (body: { market: string; keyword: string }) => {
  const { data } = await api.post("/admin/rules/market", body);
  return data;
};

export const deleteMarketRule = async (id: string) => {
  const { data } = await api.delete(`/admin/rules/market/${id}`);
  return data;
};

export const updateMarketRule = async (id: string, body: { market: string; keyword: string }) => {
  const { data } = await api.patch(`/admin/rules/market/${id}`, body);
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

export const deleteRouteRule = async (id: string) => {
  const { data } = await api.delete(`/admin/rules/route/${id}`);
  return data;
};

export const updateRouteRule = async (id: string, body: { thi_truong: string; tuyen_tour: string; keywords: string }) => {
  const { data } = await api.patch(`/admin/rules/route/${id}`, body);
  return data;
};

export const setRouteRulePriority = async (id: string, priority: boolean): Promise<RouteRule> => {
  const { data } = await api.patch(`/admin/rules/route/${id}/priority`, { priority });
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

export const seedRouteDefaults = async (force = false) => {
  const { data } = await api.post(`/admin/rules/seed-route-defaults${force ? "?force=true" : ""}`);
  return data as { imported: number; message: string };
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

export interface CompanyRule {
  id: string; canonical_name: string; alias: string; active: boolean; sort_order: number;
}

export const listCompanyRules = async (): Promise<CompanyRule[]> => {
  const { data } = await api.get("/admin/rules/company");
  return data;
};

export const createCompanyRule = async (body: { canonical_name: string; alias: string }) => {
  const { data } = await api.post("/admin/rules/company", body);
  return data;
};

export const deleteCompanyRule = async (id: string) => {
  const { data } = await api.delete(`/admin/rules/company/${id}`);
  return data;
};

export const updateCompanyRule = async (id: string, body: { canonical_name: string; alias: string }) => {
  const { data } = await api.put(`/admin/rules/company/${id}`, body);
  return data;
};

export const seedCompanyDefaults = async () => {
  const { data } = await api.post("/admin/rules/company/seed-defaults");
  return data;
};

export const applyCompanyRulesToTours = async () => {
  const { data } = await api.post("/admin/rules/company/apply-to-tours");
  return data;
};

export interface DepartureRule {
  id: string; canonical_name: string; alias: string; active: boolean; sort_order: number;
}

export const listDepartureRules = async (): Promise<DepartureRule[]> => {
  const { data } = await api.get("/admin/rules/departure");
  return data;
};

export const createDepartureRule = async (body: { canonical_name: string; alias: string }) => {
  const { data } = await api.post("/admin/rules/departure", body);
  return data;
};

export const deleteDepartureRule = async (id: string) => {
  const { data } = await api.delete(`/admin/rules/departure/${id}`);
  return data;
};

export const updateDepartureRule = async (id: string, body: { canonical_name: string; alias: string }) => {
  const { data } = await api.put(`/admin/rules/departure/${id}`, body);
  return data;
};

export const seedDepartureDefaults = async () => {
  const { data } = await api.post("/admin/rules/departure/seed-defaults");
  return data;
};

export const applyDepartureRulesToTours = async () => {
  const { data } = await api.post("/admin/rules/departure/apply-to-tours");
  return data;
};

export interface DurationRule {
  id: string; canonical_days: number; alias: string; active: boolean; sort_order: number;
}

export const listDurationRules = async (): Promise<DurationRule[]> => {
  const { data } = await api.get("/admin/rules/duration");
  return data;
};

export const createDurationRule = async (body: { canonical_days: number; alias: string }) => {
  const { data } = await api.post("/admin/rules/duration", body);
  return data;
};

export const updateDurationRule = async (id: string, body: { canonical_days: number; alias: string }) => {
  const { data } = await api.put(`/admin/rules/duration/${id}`, body);
  return data;
};

export const deleteDurationRule = async (id: string) => {
  const { data } = await api.delete(`/admin/rules/duration/${id}`);
  return data;
};

export const seedDurationDefaults = async () => {
  const { data } = await api.post("/admin/rules/duration/seed-defaults");
  return data;
};

export const applyDurationRulesToTours = async () => {
  const { data } = await api.post("/admin/rules/duration/apply-to-tours");
  return data;
};

// Schedule alias rules (Ngày KH / lich_kh) — map "Theo yêu cầu", "Liên hệ"…
// về canonical (rỗng = bỏ qua tour khỏi thống kê tần suất đoàn).
export interface ScheduleRule {
  id: string; canonical_name: string; alias: string; active: boolean; sort_order: number;
}

export const listScheduleRules = async (): Promise<ScheduleRule[]> => {
  const { data } = await api.get("/admin/rules/schedule");
  return data;
};

export const createScheduleRule = async (body: { canonical_name: string; alias: string }) => {
  const { data } = await api.post("/admin/rules/schedule", body);
  return data;
};

export const deleteScheduleRule = async (id: string) => {
  const { data } = await api.delete(`/admin/rules/schedule/${id}`);
  return data;
};

export const updateScheduleRule = async (id: string, body: { canonical_name: string; alias: string }) => {
  const { data } = await api.put(`/admin/rules/schedule/${id}`, body);
  return data;
};

export const seedScheduleDefaults = async () => {
  const { data } = await api.post("/admin/rules/schedule/seed-defaults");
  return data;
};

// ── Date format rules (pattern-based parser cho lich_kh) ────────────────────
// Pattern dùng placeholder {dd} {mm} {yyyy} {yy} {weekday} {...}.
// Output type: dates | weekly | monthly_recurring | skip | verbatim.

export type DateFormatOutputType =
  | "dates"
  | "weekly"
  | "monthly_recurring"
  | "skip"
  | "verbatim"
  | "explicit_dates";

export interface DateFormatRule {
  id: string;
  pattern: string;
  output_type: DateFormatOutputType;
  // Chỉ dùng khi output_type='explicit_dates' (vd "25/06/2026, 28/07/2026")
  output_value?: string | null;
  priority: number;
  active: boolean;
  description: string;
}

export interface DateFormatRuleInput {
  pattern: string;
  output_type: DateFormatOutputType;
  output_value?: string | null;
  priority?: number;
  active?: boolean;
  description?: string;
}

export const listDateFormatRules = async (): Promise<DateFormatRule[]> => {
  const { data } = await api.get("/admin/rules/date-format");
  return data;
};

export const createDateFormatRule = async (body: DateFormatRuleInput): Promise<DateFormatRule> => {
  const { data } = await api.post("/admin/rules/date-format", body);
  return data;
};

export const updateDateFormatRule = async (
  id: string,
  body: DateFormatRuleInput,
): Promise<DateFormatRule> => {
  const { data } = await api.put(`/admin/rules/date-format/${id}`, body);
  return data;
};

export const deleteDateFormatRule = async (id: string) => {
  const { data } = await api.delete(`/admin/rules/date-format/${id}`);
  return data;
};

export const seedDateFormatDefaults = async () => {
  const { data } = await api.post("/admin/rules/date-format/seed-defaults");
  return data;
};

export interface DateFormatTestResult {
  matched_rule_id: string | null;
  output_type: DateFormatOutputType | null;
  dates: string[];
  count: number;
  input: string;
}

export const testDateFormat = async (text: string): Promise<DateFormatTestResult> => {
  const { data } = await api.post("/admin/rules/date-format/test", { text });
  return data;
};

export type UnmatchedTourMember = { title: string; count: number; link_url?: string; cong_ty?: string };

export type UnmatchedItem = {
  value: string;
  count: number;
  thi_truong?: string;
  sample?: string;
  /** Keyword đề xuất (địa danh / esim…); rỗng = cần tự nhập */
  keyword?: string;
  /** Gợi ý tên thị trường từ địa danh trong tên tour */
  suggested_market?: string;
  /** true = gom nhiều tour theo keyword; false = mỗi dòng là một tên tour */
  grouped?: boolean;
  /** Gợi ý thị trường đúng khi cột hiện tại sai (tab tuyến tour) */
  suggested_thi_truong?: string;
  /** Id nhóm (để tách tour khỏi bucket) */
  bucket_key?: string;
  /** Danh sách tên tour trong nhóm */
  members?: UnmatchedTourMember[];
  needs_market?: boolean;
  needs_route?: boolean;
  suggested_route?: string;
  market_keyword?: string;
  route_keywords?: string;
  resolved_market?: string;
};

export const getClassifyMarketOrder = async () => {
  const { data } = await api.get("/admin/rules/classify/market-order");
  return data as { markets: string[] };
};

export const putClassifyMarketOrder = async (markets: string[]) => {
  const { data } = await api.put("/admin/rules/classify/market-order", { markets });
  return data as { markets: string[]; message?: string };
};

export const assignClassification = async (body: {
  thi_truong: string;
  tuyen_tour?: string;
  route_keywords: string;
  market_keyword?: string;
  auto_apply?: boolean;
}) => {
  const { data } = await api.post("/admin/rules/assign-classification", body);
  return data as {
    message: string;
    thi_truong?: string;
    tuyen_tour?: string;
    tours_apply?: { message?: string; applied?: boolean; result?: { message?: string } };
  };
};

export const assignClassificationBulk = async (body: {
  items: { thi_truong: string; tuyen_tour?: string; route_keywords: string }[];
  auto_apply?: boolean;
}) => {
  const { data } = await api.post("/admin/rules/assign-classification/bulk", body);
  return data as {
    message: string;
    count: number;
    added: number;
    tours_apply?: { message?: string; result?: { message?: string } };
  };
};

export const getRulesUnmatched = async (
  scope: "market" | "route" | "classify" | "company" | "departure" | "duration" | "schedule",
  fresh = false,
) => {
  const { data } = await api.get(`/admin/rules/unmatched?scope=${scope}${fresh ? "&fresh=1" : ""}`);
  return data as { scope: string; items: UnmatchedItem[] };
};

export const getRulesUnmatchedSummary = async (): Promise<Record<string, number>> => {
  const { data } = await api.get("/admin/rules/unmatched-summary");
  return data;
};

export const previewKeywordMatch = async (keywords: string, limit = 20) => {
  const { data } = await api.get(`/admin/rules/preview-keyword?keywords=${encodeURIComponent(keywords)}&limit=${limit}`);
  return data as { keywords: string[]; tour_count: number; samples: Array<{ id: number; ten_tour: string; thi_truong: string; tuyen_tour: string; cong_ty: string }> };
};

export const getRuleRouteStats = async (): Promise<Record<string, number>> => {
  const { data } = await api.get("/admin/rules/route-stats");
  return data;
};

// ── Intelligence hub ──────────────────────────────────────────────────────────

export interface IntelInsight {
  id: string; category: string; severity: string; title: string; description: string;
  link_path: string; link_params?: Record<string, string>; priority?: number;
}

export interface FestivalBriefGap {
  slug: string; name: string; date_start: string; date_end: string; region: string;
  vtr_tours: number; competitor_tours: number; gap_score: number;
}

export interface FestivalBrief {
  upcoming_count: number;
  gap_count: number;
  top_gaps: FestivalBriefGap[];
}

export interface HomeBrief {
  snapshot_date: string;
  kpis: Record<string, number | null>;
  delta: Record<string, number | string | null> | null;
  trend: Array<{ date: string; avg_gap_pct: number | null; cheaper_segments: number; expensive_segments: number }>;
  festivals?: FestivalBrief;
  insights: IntelInsight[];
  alerts: Array<{ id: number; severity: string; category: string; title: string; message: string; link_path: string }>;
}

export const getHomeBrief = async (): Promise<HomeBrief> => {
  const { data } = await api.get("/intelligence/home");
  return data;
};

export const getCoverageMap = async (filters: CompareFilters = {}) => {
  const q = buildCompareParams(filters);
  const { data } = await api.get(`/intelligence/coverage${q ? "?" + q : ""}`);
  return data;
};

export const getCoverageSegment = async (thi_truong: string, tuyen_tour: string) => {
  const { data } = await api.get("/intelligence/coverage/segment", { params: { thi_truong, tuyen_tour } });
  return data;
};

export const getDataQuality = async () => {
  const { data } = await api.get("/intelligence/quality");
  return data;
};

export const getMatcherSuggest = async () => {
  const { data } = await api.get("/intelligence/matcher/suggest");
  return data;
};

export const getMatcherDetail = async (tourId: number) => {
  const { data } = await api.get(`/intelligence/matcher/${tourId}`);
  return data;
};

export const captureSnapshot = async () => {
  const { data } = await api.post("/intelligence/snapshot/capture");
  return data;
};

export const markAlertRead = async (id: number) => {
  const { data } = await api.post(`/intelligence/alerts/${id}/read`);
  return data;
};

export const bulkPatchTours = async (body: { tour_ids: number[]; thi_truong?: string; tuyen_tour?: string; flagged?: boolean }) => {
  const { data } = await api.post("/intelligence/tours/bulk-patch", body);
  return data;
};

// ── Market Lab ────────────────────────────────────────────────────────────────

export interface MarketLabRouteRow {
  route_key: string;
  thi_truong: string;
  tuyen_tour: string;
  vtr_tour_count: number;
  market_tour_count: number;
  market_departures_monthly: number;
  vtr_departures_monthly: number;
  avg_gap_pct: number | null;
  avg_freq_gap_pct: number | null;
  market_price_day: number | null;
  phase: string;
  opportunity_score: number;
  competitor_count: number;
  quality?: "ok" | "generic" | "market_mismatch";
  quality_note?: string;
  dominant_market?: string | null;
  momentum?: {
    history_days?: number;
    supply_delta_pct?: number | null;
    vtr_supply_delta_pct?: number | null;
    gap_delta?: number | null;
  };
}

export interface MarketLabMarketRow {
  thi_truong: string;
  route_count: number;
  market_departures_monthly: number;
  vtr_departures_monthly: number;
  avg_gap_pct: number | null;
  white_space_routes: number;
  opportunity_score: number;
}

export interface MarketLabOverview {
  grain: string;
  tab: string;
  history_days: number;
  meta?: {
    source: string;
    compute_seconds: number;
    suspect_routes_hidden?: number;
    hide_suspect?: boolean;
  };
  routes?: MarketLabRouteRow[];
  markets?: MarketLabMarketRow[];
  weekly_brief: {
    horizon_days: number;
    note: string;
    top_routes: Array<{
      route_key: string;
      thi_truong: string;
      tuyen_tour: string;
      base: string;
      action_hint: string;
      phase: string;
      avg_gap_pct: number | null;
      freq_gap_pct: number | null;
    }>;
  };
}

export const getMarketLabOverview = async (opts: {
  grain?: "route" | "market";
  tab?: "opportunity" | "operating";
  thi_truong?: string;
  hide_suspect?: boolean;
}): Promise<MarketLabOverview> => {
  const p = new URLSearchParams();
  if (opts.grain) p.set("grain", opts.grain);
  if (opts.tab) p.set("tab", opts.tab);
  if (opts.thi_truong) p.set("thi_truong", opts.thi_truong);
  if (opts.hide_suspect === false) p.set("hide_suspect", "false");
  const { data } = await marketLabApi.get(`/market-lab/overview?${p}`);
  return data;
};

export const getMarketLabSupplyCalendar = async (thi_truong: string, tuyen_tour: string) => {
  const p = new URLSearchParams({ thi_truong, tuyen_tour });
  const { data } = await marketLabApi.get(`/market-lab/supply-calendar?${p}`);
  return data as {
    route_key: string;
    months: Array<{ month: string; market_slots: number; vtr_slots: number; gap_slots: number }>;
    tour_count: number;
  };
};

export interface RouteHistoryPoint {
  date: string;
  market_dep: number;
  vtr_dep: number;
  gap_pct: number | null;
  freq_gap_pct: number | null;
  market_price_day: number | null;
  phase: string;
  opportunity_score: number;
}

export const getMarketLabRouteHistory = async (route_key: string, days = 30) => {
  const p = new URLSearchParams({ route_key, days: String(days) });
  const { data } = await marketLabApi.get(`/market-lab/route-history?${p}`);
  return data as { route_key: string; days: number; points: RouteHistoryPoint[] };
};

export interface SegmentHistoryPoint {
  date: string;
  gap_pct: number | null;
  freq_gap_pct: number | null;
  vtr_price: number | null;
  market_price: number | null;
  vtr_dep: number | null;
  market_dep: number | null;
}

export const getCompareSegmentHistory = async (segment_key: string, days = 30) => {
  const p = new URLSearchParams({ segment_key, days: String(days) });
  // Endpoint thật nằm ở router market-lab (/api/market-lab/segment-history) — trước
  // đây gọi /compare/segment-history (không tồn tại) → 404 → mini-chart luôn báo "chưa có".
  const { data } = await marketLabApi.get(`/market-lab/segment-history?${p}`);
  return data as { segment_key: string; points: SegmentHistoryPoint[] };
};

// ── Workspaces ────────────────────────────────────────────────────────────────

export interface WorkspaceInfo {
  id: number;
  name: string;
  owner_user_id: number;
  is_personal: boolean;
  visibility: string;
  permission: "view" | "edit" | "copy";
  is_owner: boolean;
}

export interface WorkspaceTourFilters {
  page?: number; page_size?: number; search?: string;
  thi_truong?: string[]; tuyen_tour?: string[]; cong_ty?: string[];
  nguon?: string[]; phan_khuc?: string[]; diem_kh?: string[]; flagged?: boolean; only_overridden?: boolean;
  sort_by?: string; sort_dir?: string;
}

export const listWorkspaces = async (): Promise<WorkspaceInfo[]> => {
  const { data } = await api.get("/workspaces");
  return data;
};

function workspaceTourQueryParams(filters: WorkspaceTourFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v === undefined || v === null) return;
    if (Array.isArray(v)) v.forEach((item) => params.append(k, item));
    else params.append(k, String(v));
  });
  return params;
}

export const getWorkspaceTours = async (workspaceId: number, filters: WorkspaceTourFilters = {}) => {
  const { data } = await api.get(`/workspaces/${workspaceId}/tours?${workspaceTourQueryParams(filters)}`);
  return data as { items: Tour[]; total: number; page: number; page_size: number; workspace_id: number };
};

export const downloadWorkspaceCsv = async (workspaceId: number, filters: WorkspaceTourFilters = {}) => {
  const { page: _p, page_size: _ps, sort_by: _sb, sort_dir: _sd, ...exportFilters } = filters;
  const response = await api.get(`/workspaces/${workspaceId}/export/csv?${workspaceTourQueryParams(exportFilters)}`, {
    responseType: "blob",
  });
  const blob = response.data as Blob;
  if (blob.type.includes("json")) {
    const err = JSON.parse(await blob.text()) as { detail?: string };
    throw new Error(err.detail || "Lỗi tải CSV");
  }
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `workspace_${workspaceId}_tours.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};

export const patchWorkspaceTour = async (workspaceId: number, tourId: string | number, patch: Partial<Tour>) => {
  const { data } = await api.patch(`/workspaces/${workspaceId}/tours/${tourId}`, patch);
  return data as Tour;
};

export const bulkPatchWorkspaceTours = async (
  workspaceId: number,
  body: { tour_ids: (string | number)[]; thi_truong?: string; tuyen_tour?: string; flagged?: boolean; analyst_note?: string },
) => {
  const { data } = await api.post(`/workspaces/${workspaceId}/tours/bulk-patch`, body);
  return data;
};

export const shareWorkspace = async (workspaceId: number, username: string, permission: "view" | "edit" | "copy") => {
  const { data } = await api.post(`/workspaces/${workspaceId}/share`, { username, permission });
  return data;
};

export const listWorkspaceMembers = async (workspaceId: number) => {
  const { data } = await api.get(`/workspaces/${workspaceId}/members`);
  return data as { workspace_id: number; members: Array<{ user_id: number; username: string; display_name: string; permission: string; is_owner: boolean }> };
};

export const revokeWorkspaceShare = async (workspaceId: number, memberUserId: number) => {
  const { data } = await api.delete(`/workspaces/${workspaceId}/share/${memberUserId}`);
  return data;
};

export const copyWorkspaceOverrides = async (workspaceId: number, sourceWorkspaceId: number) => {
  const { data } = await api.post(`/workspaces/${workspaceId}/copy-from`, { source_workspace_id: sourceWorkspaceId });
  return data as { copied: number; destination_workspace_id: number };
};

export const applyClassificationToTours = async (opts?: { fullScan?: boolean; recomputePhanKhuc?: boolean }) => {
  const params = new URLSearchParams();
  if (opts?.fullScan) params.set("full_scan", "true");
  if (opts?.recomputePhanKhuc) params.set("recompute_phan_khuc", "true");
  const q = params.toString();
  const { data } = await api.post(`/admin/rules/apply-classification-to-tours${q ? `?${q}` : ""}`);
  return data as { started?: boolean; running?: boolean; message?: string };
};

/**
 * Re-apply TẤT CẢ classification rules lên tour (TT, tuyến, ngày KH, số ngày, phân khúc).
 * KHÔNG scrape, KHÔNG import data. Tương đương: applyClassificationToTours({ recomputePhanKhuc: true }).
 *
 * NOTE for backend coord: nếu sau này backend muốn tách hẳn endpoint
 *   POST /api/admin/recompute-all-classifications
 * thì sửa URL bên dưới. Hiện đang reuse apply-classification-to-tours + recompute_phan_khuc=true
 * (đã cover full scope theo backend logic — xem api/rules.py: _start_apply_all_rules_background).
 */
export const recomputeAllClassifications = async () => {
  const params = new URLSearchParams();
  params.set("recompute_phan_khuc", "true");
  // full_scan=true để re-apply tất cả tour, không chỉ tour mới
  params.set("full_scan", "true");
  const { data } = await api.post(`/admin/rules/apply-classification-to-tours?${params.toString()}`);
  return data as { started?: boolean; running?: boolean; message?: string };
};

export const getApplyClassificationStatus = async () => {
  const { data } = await api.get("/admin/rules/apply-classification-status");
  return data as {
    running: boolean; message?: string; error?: string; stale?: boolean;
    progress?: number; total?: number; last_id?: number; params?: Record<string, unknown>;
    last_result?: Record<string, unknown>;
  };
};

export const assignMarketKeyword = async (market: string, keyword: string) => {
  const params = new URLSearchParams({ market, keyword });
  const { data } = await api.post(`/admin/rules/market/assign-keyword?${params}`);
  return data as { message: string };
};

export const reportHtmlUrl = () =>
  `/api/intelligence/report/html?access_token=${localStorage.getItem("access_token")}`;

export const fetchReportHtml = async (refresh = false): Promise<string> => {
  const { data } = await api.get(`/intelligence/report/html${refresh ? "?refresh=true" : ""}`, { responseType: "text" });
  return data;
};

export const saveReportHtml = async (html: string): Promise<{ saved: boolean }> => {
  const { data } = await api.put("/intelligence/report/html", { html });
  return data;
};

// ── So sánh đối thủ (Báo cáo BGĐ) ──────────────────────────────────────────────
export interface CompMonthly { month: string; count: number }
export interface CompMetrics {
  products: number;
  departures: number;
  price_from: number | null;
  price_avg: number | null;
  link: string;
  cheapest_name: string;
  monthly: CompMonthly[];
  sell_from: string;
  sell_to: string;
}
export interface CompRoute {
  tuyen: string;
  vtr: CompMetrics | null;
  competitor: (CompMetrics & { company: string }) | null;
  peer: CompMetrics | null;
}
export interface CompetitorMarketRow {
  thi_truong: string;
  competitor_companies: string[];
  has_peer: boolean;
  vtr: CompMetrics;
  competitor: CompMetrics;
  peer: CompMetrics;
  vtr_routes: number;
  competitor_routes: number;
  peer_routes: number;
  routes: CompRoute[];
}
export interface CompetitorDeparture {
  diem_kh: string;
  total_tours: number;
  markets: CompetitorMarketRow[];
}
export interface CompetitorReport {
  departures: CompetitorDeparture[];
  peer_name: string;
  overrides: Record<string, { note?: string }>;
}

export const getCompetitorReport = async (): Promise<CompetitorReport> => {
  const { data } = await api.get("/intelligence/competitor-report");
  return data;
};

export const saveCompetitorReportOverrides = async (
  overrides: Record<string, { note?: string }>,
): Promise<{ saved: boolean }> => {
  const { data } = await api.put("/intelligence/competitor-report/overrides", { overrides });
  return data;
};

// ── Festivals (T3 Phase 1) ────────────────────────────────────────────────────

export type FestivalRegion = "bac" | "trung" | "nam" | "intl" | "";
export type FestivalCategory = "cultural" | "religious" | "music" | "food" | "sport" | "other";

export interface Festival {
  id: string;
  slug: string;
  name_vi: string;
  name_en: string;
  date_start: string;  // ISO date
  date_end: string;
  is_lunar: boolean;
  location_text: string;
  province_code: string;
  region: FestivalRegion;
  category: FestivalCategory;
  description: string;
  image_url: string;
  source_url: string;
}

export interface FestivalFilters {
  from?: string;
  to?: string;
  region?: FestivalRegion;
  category?: FestivalCategory;
  province?: string;
  limit?: number;
}

export interface FestivalStats {
  total: number;
  by_region: Record<string, number>;
  by_category: Record<string, number>;
  by_month: Record<string, number>;
  upcoming_30d: number;
  upcoming_90d: number;
}

export const listFestivals = async (filters: FestivalFilters = {}): Promise<Festival[]> => {
  const params = new URLSearchParams();
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  if (filters.region) params.set("region", filters.region);
  if (filters.category) params.set("category", filters.category);
  if (filters.province) params.set("province", filters.province);
  if (filters.limit) params.set("limit", String(filters.limit));
  const { data } = await api.get(`/festivals?${params}`);
  return data;
};

export const getFestival = async (slug: string): Promise<Festival> => {
  const { data } = await api.get(`/festivals/${encodeURIComponent(slug)}`);
  return data;
};

export const getFestivalStats = async (): Promise<FestivalStats> => {
  const { data } = await api.get("/festivals/stats/summary");
  return data;
};

export const refreshFestivals = async () => {
  const { data } = await api.post("/festivals/refresh");
  return data as { message: string; inserted: number; updated: number; unchanged: number };
};

// Phase 2: cross-ref tour
export interface FestivalTourLite {
  id: string;
  cong_ty: string;
  thi_truong: string;
  tuyen_tour: string;
  ten_tour: string;
  diem_kh: string;
  province_code: string;
  gia: number | null;
  so_ngay: number | null;
  nguon: string;
  link_url: string;
  festival_distance_days: number | null;
}

export const listFestivalTours = async (slug: string, company?: string): Promise<FestivalTourLite[]> => {
  const params = new URLSearchParams();
  if (company) params.set("company", company);
  const { data } = await api.get(`/festivals/${encodeURIComponent(slug)}/tours?${params}`);
  return data;
};

export interface FestivalCompanyAgg {
  cong_ty: string;
  is_vtr: boolean;
  products: number;
  departures: number;
  price_from: number | null;
  link: string;
}

export interface FestivalSummary {
  slug: string;
  name: string;
  total_tours: number;
  by_company: Record<string, number>;
  companies: FestivalCompanyAgg[];
  avg_price: number | null;
  vtr_tours: number;
  competitor_tours: number;
}

export const getFestivalSummary = async (slug: string): Promise<FestivalSummary> => {
  const { data } = await api.get(`/festivals/${encodeURIComponent(slug)}/summary`);
  return data;
};

export interface CoverageGapItem {
  slug: string;
  name: string;
  date_start: string;
  date_end: string;
  region: string;
  location?: string;
  vtr_tours: number;
  competitor_tours: number;
  top_competitors: Record<string, number>;
  gap_score: number;
}

export const getCoverageGap = async (limit = 30): Promise<CoverageGapItem[]> => {
  const { data } = await api.get(`/festivals/insights/coverage-gap?limit=${limit}`);
  return data;
};

export const retagFestivals = async (onlyUntagged = false) => {
  const { data } = await api.post(`/festivals/insights/retag?only_untagged=${onlyUntagged}`);
  return data as { message: string; tours_scanned: number; tours_tagged: number; tours_cleared: number };
};

// Phase 3: insights
export interface PremiumRoute {
  thi_truong: string;
  tuyen_tour: string;
  n_with_festival: number;
  n_without_festival: number;
  avg_price_with_festival: number;
  avg_price_without_festival: number;
  premium_pct: number;
  premium_vnd: number;
}

export interface PricingPremiumResult {
  summary: {
    routes_analyzed: number;
    avg_premium_pct: number;
    tours_with_festival: number;
    tours_without_festival: number;
  };
  top_premium_routes: PremiumRoute[];
  top_discount_routes: PremiumRoute[];
}

export const getPricingPremium = async (topN = 20): Promise<PricingPremiumResult> => {
  const { data } = await api.get(`/festivals/insights/pricing-premium?top_n=${topN}`);
  return data;
};

export interface DemandForecastMonth {
  year: number;
  month: number;
  month_label: string;
  festival_count: number;
  top_region: string;
  by_region: Record<string, number>;
  tour_count: number;
  vtr_tour_count: number;
  competitor_tour_count: number;
  inventory_recommendation: "high" | "medium" | "low";
  inventory_label: string;
  top_festivals: { slug: string; name: string; date_start: string }[];
}

export const getDemandForecast = async (monthsAhead = 6): Promise<{ forecast: DemandForecastMonth[] }> => {
  const { data } = await api.get(`/festivals/insights/demand-forecast?months_ahead=${monthsAhead}`);
  return data;
};

export interface MarketingCalendarItem {
  slug: string;
  name: string;
  date_start: string;
  date_end: string;
  region: string;
  location_text?: string;
  category: string;
  is_lunar: boolean;
  suggested_tours: {
    id: string;
    ten_tour: string;
    gia: number | null;
    so_ngay: number | null;
    link_url: string;
  }[];
  campaign_hint: string;
}

export const getMarketingCalendar = async (monthsAhead = 12): Promise<MarketingCalendarItem[]> => {
  const { data } = await api.get(`/festivals/insights/marketing-calendar?months_ahead=${monthsAhead}`);
  return data;
};

export interface HeatmapRegion {
  region: string;
  region_label: string;
  festival_count: number;
  tour_count: number;
  tour_with_festival: number;
  vtr_tour_count: number;
  festival_coverage_ratio: number;
  is_under_served: boolean;
}

export interface HeatmapProvince {
  province_code: string;
  province_name: string;
  region: string;
  festival_count: number;
  tour_count: number;
  tour_with_festival: number;
  vtr_tour_count: number;
  festival_coverage_ratio: number;
  is_under_served: boolean;
}

export interface HeatmapData {
  regions: HeatmapRegion[];
  provinces: HeatmapProvince[];
  total_festivals: number;
  total_provinces_with_data: number;
}

export const getRegionHeatmap = async (): Promise<HeatmapData> => {
  const { data } = await api.get("/festivals/insights/heatmap");
  return data;
};

// ── Dashboard summary (smart alerts + quick stats + data quality) ──────────
export interface DashboardAlert {
  critical_30d_count: number;
  critical_30d: Array<{
    slug: string;
    name: string;
    date_start: string;
    days_until: number;
    region: FestivalRegion;
    location_text: string;
    category: FestivalCategory;
  }>;
  under_served_count: number;
  under_served: Array<{
    province_code: string;
    province_name: string;
    region: string;
    festival_count: number;
    vtr_tour_count: number;
  }>;
  top_gaps_count: number;
  top_gaps: Array<{
    slug: string;
    name: string;
    vtr_tours: number;
    competitor_tours: number;
    gap_score: number;
    date_start: string;
  }>;
}

export interface DashboardSummary {
  alerts: DashboardAlert;
  quick_stats: {
    upcoming_30d: number;
    upcoming_90d: number;
    tours_tagged_festival: number;
    vtr_tours_tagged_festival: number;
    vtr_cover_ratio: number;
  };
  data_quality: {
    festivals_total: number;
    festivals_with_location_pct: number;
    festivals_with_province_pct: number;
    tours_total: number;
    tours_with_province_pct: number;
    tours_tagged_festival_pct: number;
  };
}

export const getFestivalDashboardSummary = async (): Promise<DashboardSummary> => {
  const { data } = await api.get("/festivals/insights/dashboard-summary");
  return data;
};

export interface LunarEvent {
  slug: string;
  name: string;
  date_start: string;
  date_end: string;
  lunar_month: number | null;
  lunar_day: number | null;
  category: string;
  region: string;
  year: number;
}

export const getLunarPlanner = async (yearsAhead = 3): Promise<{ events: LunarEvent[] }> => {
  const { data } = await api.get(`/festivals/insights/lunar-planner?years_ahead=${yearsAhead}`);
  return data;
};

export const lunarSeed = async () => {
  const { data } = await api.post("/festivals/insights/lunar-seed");
  return data as { message: string; inserted: number; skipped: number };
};

// ── Festival Tour Mapping Rules (Quy tắc phân loại) ─────────────────────────

export interface FestivalMappingRule {
  id: string;
  location_keyword: string;
  market_keyword: string;
  route_keyword: string;
  date_window_days: number;
  active: boolean;
  note: string;
}

export interface FestivalMappingRuleInput {
  location_keyword: string;
  market_keyword?: string;
  route_keyword?: string;
  date_window_days?: number;
  active?: boolean;
  note?: string;
}

export const listFestivalMappingRules = async (): Promise<FestivalMappingRule[]> => {
  const { data } = await api.get("/admin/rules/festival-mapping");
  return data;
};

export const createFestivalMappingRule = async (body: FestivalMappingRuleInput): Promise<FestivalMappingRule> => {
  const { data } = await api.post("/admin/rules/festival-mapping", body);
  return data;
};

export const updateFestivalMappingRule = async (id: string, body: FestivalMappingRuleInput): Promise<FestivalMappingRule> => {
  const { data } = await api.put(`/admin/rules/festival-mapping/${id}`, body);
  return data;
};

export const deleteFestivalMappingRule = async (id: string) => {
  const { data } = await api.delete(`/admin/rules/festival-mapping/${id}`);
  return data;
};

export const applyFestivalMappingRules = async () => {
  const { data } = await api.post("/admin/rules/festival-mapping/apply");
  return data as {
    message: string;
    rules_applied: number;
    tours_tagged: number;
    details: { festival_slug: string; festival_name?: string; tagged: number; skip?: string }[];
  };
};

// ── Festival Mapping Summary & Auto-Suggest (Phase B, Issue #5) ───────────────
// Backend coord: 3 endpoints (Phase A — backend đang implement):
//   GET  /festivals/insights/coverage-gap/mapping-summary
//   GET  /festivals/insights/coverage-gap/mapping-suggestions?limit=N
//   POST /admin/rules/festival-mapping/bulk

export interface FestivalMappingSummary {
  total_festivals: number;
  festivals_with_rule: number;
  festivals_without_rule: number;
  rules_total: number;
  coverage_pct: number;
}

export const getFestivalMappingSummary = async (): Promise<FestivalMappingSummary> => {
  const { data } = await api.get("/festivals/insights/coverage-gap/mapping-summary");
  return data;
};

export interface FestivalMappingSuggestion {
  festival_slug: string;
  festival_name: string;
  location_text: string;
  location_keyword: string;       // = suggested_location_keyword (đã map từ BE)
  suggested_market: string;
  suggested_route: string;
  confidence: number;             // 0..1 (UI: 0..100 %)
  tour_count: number;
  reason?: string;                // = reasoning (đã map từ BE)
}

export const getFestivalMappingSuggestions = async (limit = 20): Promise<{ suggestions: FestivalMappingSuggestion[] }> => {
  // BE: POST /admin/rules/festival-mapping/auto-suggest (trước FE gọi GET path khác → 404).
  const { data } = await api.post(`/admin/rules/festival-mapping/auto-suggest?limit=${limit}`);
  const suggestions: FestivalMappingSuggestion[] = (data?.suggestions ?? []).map((s: any) => ({
    festival_slug: s.festival_slug,
    festival_name: s.festival_name,
    location_text: s.location_text,
    location_keyword: s.suggested_location_keyword ?? s.location_keyword ?? "",
    suggested_market: s.suggested_market ?? "",
    suggested_route: s.suggested_route ?? "",
    confidence: s.confidence ?? 0,
    tour_count: s.tour_count ?? 0,
    reason: s.reasoning ?? s.reason ?? "",
  }));
  return { suggestions };
};

export const bulkCreateFestivalMappingRules = async (rules: FestivalMappingRuleInput[]) => {
  // BE path đúng là /bulk-create (trước FE gọi /bulk → 404).
  const { data } = await api.post("/admin/rules/festival-mapping/bulk-create", { rules });
  return data as { inserted: number; ids: string[]; skipped?: { index: string; reason: string }[] };
};

// Extended CoverageGapItem fields (Phase A backend will add tagged/implied split + has_rule).
// Existing CoverageGapItem keeps vtr_tours/competitor_tours for back-compat (= tagged values).
export interface CoverageGapItemExt extends CoverageGapItem {
  vtr_tours_tagged?: number;
  vtr_tours_implied?: number;
  competitor_tours_tagged?: number;
  competitor_tours_implied?: number;
  has_rule?: boolean;
  location_text?: string;
}

// ── Compare segment rule (admin) ───────────────────────────────────────────
export interface CompareSegmentRule {
  vtr_tiers: string[];
  market_phan_khuc: string[];
  updated_at: string | null;
  updated_by: string | null;
  is_default: boolean;
  available_vtr_tiers: string[];
  available_market_phan_khuc: string[];
}

export const getCompareSegmentRule = async (): Promise<CompareSegmentRule> => {
  const { data } = await api.get("/admin/compare-segment-rule");
  return data;
};

export const updateCompareSegmentRule = async (payload: {
  vtr_tiers: string[];
  market_phan_khuc: string[];
}): Promise<CompareSegmentRule> => {
  const { data } = await api.put("/admin/compare-segment-rule", payload);
  return data;
};
