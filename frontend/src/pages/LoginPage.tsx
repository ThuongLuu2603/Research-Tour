import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Plane, Globe2, BarChart3, ShieldCheck, TrendingUp,
  User, Lock, Eye, EyeOff, Loader2, ArrowRight,
} from "lucide-react";
import { login } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

const FEATURES = [
  { icon: BarChart3, label: "So sánh giá & tần suất theo thị trường" },
  { icon: TrendingUp, label: "Theo dõi động lực cung – cầu thị trường" },
  { icon: ShieldCheck, label: "Dữ liệu Vietravel + FindTourGo hợp nhất" },
];

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { setToken } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { access_token, user } = await login(username, password);
      setToken(access_token, user);
      navigate("/");
    } catch {
      setError("Sai tên đăng nhập hoặc mật khẩu");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full flex bg-primary-900 overflow-hidden">
      {/* ── Nền aurora động ───────────────────────────────────────────────── */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div
          className="absolute -top-1/3 -left-1/4 w-[55vw] h-[55vw] rounded-full blur-3xl opacity-40 animate-float-slow"
          style={{ background: "radial-gradient(circle, #3b82f6, transparent 65%)" }}
        />
        <div
          className="absolute top-1/4 -right-1/5 w-[45vw] h-[45vw] rounded-full blur-3xl opacity-30 animate-float"
          style={{ background: "radial-gradient(circle, #06b6d4, transparent 65%)" }}
        />
        <div
          className="absolute -bottom-1/3 left-1/3 w-[40vw] h-[40vw] rounded-full blur-3xl opacity-25 animate-float-slow"
          style={{ background: "radial-gradient(circle, #22d3ee, transparent 65%)" }}
        />
        {/* Lưới mảnh tạo chiều sâu */}
        <div
          className="absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.6) 1px, transparent 1px)",
            backgroundSize: "44px 44px",
          }}
        />
      </div>

      {/* ── Cột thương hiệu (ẩn trên mobile) ──────────────────────────────── */}
      <div className="relative hidden lg:flex flex-col justify-between w-[52%] p-12 xl:p-16 text-white">
        <div className="flex items-center gap-3 animate-fade-in-down">
          <div className="w-11 h-11 rounded-2xl glass flex items-center justify-center shadow-glow">
            <Plane size={22} className="text-white" />
          </div>
          <div>
            <p className="font-bold text-lg leading-tight">VTR Intelligence</p>
            <p className="text-blue-200/80 text-xs">Research Hub</p>
          </div>
        </div>

        <div className="max-w-lg">
          {/* Biểu tượng địa cầu xoay nhẹ */}
          <div className="relative mb-8 inline-flex">
            <Globe2 size={64} className="text-accent-400 animate-spin-slow [animation-duration:24s]" strokeWidth={1.2} />
            <span className="absolute inset-0 rounded-full bg-accent-400/20 blur-2xl" />
          </div>
          <h1 className="text-4xl xl:text-5xl font-extrabold leading-tight animate-fade-in-up">
            Nghiên cứu thị trường <span className="gradient-text">tour du lịch</span>
          </h1>
          <p className="mt-4 text-blue-100/80 text-lg animate-fade-in-up [animation-delay:80ms]">
            Nền tảng phân tích cạnh tranh & định giá cho đội kinh doanh tour.
          </p>

          <ul className="mt-8 space-y-3">
            {FEATURES.map(({ icon: Icon, label }, i) => (
              <li
                key={label}
                className="flex items-center gap-3 text-blue-50/90 animate-fade-in-up"
                style={{ animationDelay: `${160 + i * 80}ms` }}
              >
                <span className="w-9 h-9 rounded-xl glass flex items-center justify-center flex-shrink-0">
                  <Icon size={17} className="text-accent-400" />
                </span>
                <span className="text-sm">{label}</span>
              </li>
            ))}
          </ul>
        </div>

        <p className="text-blue-200/60 text-xs animate-fade-in">
          OTA Research Platform v1.0 · Vietravel + FindTourGo
        </p>
      </div>

      {/* ── Cột form ──────────────────────────────────────────────────────── */}
      <div className="relative flex-1 flex items-center justify-center p-5 sm:p-8">
        <div className="w-full max-w-md animate-scale-in">
          {/* Header gọn cho mobile */}
          <div className="lg:hidden text-center mb-7">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl glass shadow-glow mb-3 animate-float">
              <Plane size={28} className="text-white" />
            </div>
            <h1 className="text-xl font-bold text-white">VTR Intelligence</h1>
            <p className="text-blue-200/80 text-sm">Hệ thống nghiên cứu thị trường tour</p>
          </div>

          {/* Card */}
          <div className="bg-white/95 backdrop-blur-xl rounded-3xl shadow-2xl ring-1 ring-white/40 p-8 sm:p-9">
            <h2 className="text-2xl font-bold text-gray-900">Chào mừng trở lại 👋</h2>
            <p className="text-gray-500 text-sm mt-1 mb-7">Đăng nhập để tiếp tục vào hệ thống.</p>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Tên đăng nhập</label>
                <div className="relative group">
                  <User
                    size={18}
                    className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 transition-colors group-focus-within:text-primary-600"
                  />
                  <input
                    className="input pl-10"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="admin"
                    autoFocus
                    autoComplete="username"
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Mật khẩu</label>
                <div className="relative group">
                  <Lock
                    size={18}
                    className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 transition-colors group-focus-within:text-primary-600"
                  />
                  <input
                    type={showPw ? "text" : "password"}
                    className="input pl-10 pr-10"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    autoComplete="current-password"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((v) => !v)}
                    tabIndex={-1}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-primary-600 transition-colors"
                    aria-label={showPw ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
                  >
                    {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              {error && (
                <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-xl px-3 py-2.5 text-sm text-red-700 animate-shake">
                  <span className="w-1.5 h-1.5 rounded-full bg-red-500 flex-shrink-0" />
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="btn-primary w-full justify-center py-3 text-base rounded-xl group"
              >
                {loading ? (
                  <>
                    <Loader2 size={18} className="animate-spin-slow" />
                    Đang đăng nhập…
                  </>
                ) : (
                  <>
                    Đăng nhập
                    <ArrowRight size={18} className="transition-transform group-hover:translate-x-1" />
                  </>
                )}
              </button>
            </form>
          </div>

          <p className="lg:hidden text-center text-blue-200/70 text-xs mt-6">
            OTA Research Platform v1.0 · Vietravel + FindTourGo
          </p>
        </div>
      </div>
    </div>
  );
}
