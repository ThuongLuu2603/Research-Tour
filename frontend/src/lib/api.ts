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

export interface User { id: number; username: string; display_name: string }

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
