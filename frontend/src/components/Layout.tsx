import { Suspense } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import {
  Home, Table2, Scale, FileText, Radio, LogOut, User, Settings, Tags, Microscope, CalendarHeart,
} from "lucide-react";
import { cn } from "@/lib/utils";
import ChunkErrorBoundary from "@/components/ChunkErrorBoundary";

/**
 * Vietravel Brand Wordmark
 * - Chữ "Vietravel" trắng (font weight 800)
 * - Dấu chấm ĐỎ #E30613 trên chữ "i" (dùng "ı" dotless để render dot custom)
 * - Optional ® registered mark
 */
function VietravelWordmark({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const sizing = {
    sm: { text: "text-base", dot: "w-1 h-1 -top-0.5", reg: "text-[7px]" },
    md: { text: "text-lg", dot: "w-1.5 h-1.5 -top-1", reg: "text-[8px]" },
    lg: { text: "text-2xl", dot: "w-2 h-2 -top-1.5", reg: "text-[10px]" },
  }[size];
  return (
    <span className={cn("font-extrabold tracking-tight leading-none text-white inline-flex items-baseline", sizing.text)}>
      <span>V</span>
      <span className="relative inline-block">
        <span
          aria-hidden
          className={cn("absolute left-1/2 -translate-x-1/2 rounded-full bg-accent-500 shadow-[0_0_0_1px_rgba(227,6,19,0.35)]", sizing.dot)}
        />
        {/* dotless i (U+0131) — để render dấu chấm ĐỎ custom */}
        <span>ı</span>
      </span>
      <span>etravel</span>
      <sup className={cn("ml-0.5 text-white/60 font-medium", sizing.reg)}>®</sup>
    </span>
  );
}

function PageFallback() {
  return (
    <div className="p-6 space-y-4">
      <div className="skeleton h-8 w-56" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="skeleton h-24 rounded-xl" />
        ))}
      </div>
      <div className="skeleton h-72 rounded-xl" />
    </div>
  );
}

const NAV = [
  { to: "/", icon: Home, label: "Trang chủ CI" },
  { to: "/compare", icon: Scale, label: "So sánh VTR" },
  { to: "/market-lab", icon: Microscope, label: "Market Lab" },
  { to: "/data", icon: Table2, label: "Sản phẩm & Data" },
  { to: "/festivals", icon: CalendarHeart, label: "Sự kiện & Lễ hội" },
  { to: "/reports", icon: FileText, label: "Báo cáo BGĐ" },
];

const ADMIN_NAV = [
  { to: "/ops", icon: Radio, label: "Vận hành" },
  { to: "/rules", icon: Tags, label: "Quy tắc phân loại" },
  { to: "/settings", icon: Settings, label: "Cài đặt" },
];

function NavItem({ to, icon: Icon, label, end }: { to: string; icon: typeof Home; label: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          "group relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200",
          isActive
            ? "bg-white text-primary-700 shadow-sm"
            : "text-blue-100 hover:bg-white/10 hover:text-white hover:translate-x-0.5"
        )
      }
    >
      {({ isActive }) => (
        <>
          {/* Thanh chỉ báo trang đang chọn */}
          <span
            className={cn(
              "absolute left-0 top-1/2 -translate-y-1/2 h-5 w-1 rounded-r-full bg-accent-400 transition-all duration-300",
              isActive ? "opacity-100" : "opacity-0 -translate-x-1"
            )}
          />
          <Icon size={18} className="transition-transform duration-200 group-hover:scale-110" />
          {label}
        </>
      )}
    </NavLink>
  );
}

export default function Layout() {
  const { user, logout } = useAuth();
  const isAdmin = user?.role === "admin";
  const location = useLocation();

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <aside className="w-56 bg-gradient-to-b from-primary-600 via-primary-700 to-primary-900 flex flex-col flex-shrink-0 shadow-xl">
        {/* Brand header — Vietravel official wordmark + research hub label */}
        <div className="px-4 py-5 border-b border-white/10">
          <VietravelWordmark size="md" />
          <p className="text-blue-100/70 text-[10px] font-semibold tracking-[0.18em] mt-1.5 uppercase">
            Market Research Hub
          </p>
        </div>

        <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto stagger">
          {NAV.map((item) => (
            <NavItem key={item.to} {...item} end={item.to === "/"} />
          ))}
          {isAdmin && (
            <>
              <div className="pt-3 pb-1 px-3 text-[10px] uppercase text-blue-300/80 font-semibold tracking-wider">
                Admin
              </div>
              {ADMIN_NAV.map((item) => (
                <NavItem key={item.to} {...item} />
              ))}
            </>
          )}
        </nav>

        <div className="px-3 py-3 border-t border-white/10 space-y-2">
          {/* User profile */}
          <div className="flex items-center gap-2 px-2 py-2 rounded-lg transition-colors hover:bg-white/5">
            <div className="w-7 h-7 bg-white rounded-full flex items-center justify-center flex-shrink-0 text-sm ring-2 ring-white/20">
              {user?.avatar_url && !user.avatar_url.startsWith("http") ? (
                user.avatar_url
              ) : user?.avatar_url ? (
                <img src={user.avatar_url} alt="" className="w-7 h-7 rounded-full object-cover" />
              ) : (
                <User size={14} className="text-primary-600" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-white text-xs font-medium truncate">{user?.display_name || user?.username}</p>
              <p className="text-blue-100/70 text-xs truncate">@{user?.username}</p>
            </div>
            <button
              onClick={logout}
              title="Đăng xuất"
              className="text-blue-100 hover:text-white hover:bg-white/10 p-1.5 rounded-lg transition-all active:scale-90"
            >
              <LogOut size={16} />
            </button>
          </div>
          {/* Vietravel tagline */}
          <p className="text-center text-blue-100/60 text-[9px] font-semibold tracking-[0.22em] uppercase pb-0.5">
            Your Journey · Your Value
          </p>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        {/* Chuyển trang: nội dung trồi lên nhẹ mỗi khi đổi route */}
        <div key={location.pathname} className="page-enter min-h-full">
          <ChunkErrorBoundary>
            <Suspense fallback={<PageFallback />}>
              <Outlet />
            </Suspense>
          </ChunkErrorBoundary>
        </div>
      </main>
    </div>
  );
}
