import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import {
  Home, Table2, Scale, FileText, Radio, LogOut, User, Settings, Tags, Microscope,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", icon: Home, label: "Trang chủ CI" },
  { to: "/compare", icon: Scale, label: "So sánh VTR" },
  { to: "/market-lab", icon: Microscope, label: "Market Lab" },
  { to: "/data", icon: Table2, label: "Sản phẩm & Data" },
  { to: "/reports", icon: FileText, label: "Báo cáo BGĐ" },
];

const ADMIN_NAV = [
  { to: "/ops", icon: Radio, label: "Vận hành" },
  { to: "/rules", icon: Tags, label: "Quy tắc phân loại" },
  { to: "/settings", icon: Settings, label: "Cài đặt" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <aside className="w-56 bg-primary-600 flex flex-col flex-shrink-0">
        <div className="px-4 py-5 border-b border-primary-700">
          <div className="flex items-center gap-2">
            <span className="text-2xl">✈️</span>
            <div>
              <p className="text-white font-bold text-sm leading-tight">VTR Intelligence</p>
              <p className="text-blue-200 text-xs">Research Hub</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                  isActive ? "bg-white text-primary-600" : "text-blue-100 hover:bg-primary-700 hover:text-white"
                )
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
          {isAdmin && (
            <>
              <div className="pt-3 pb-1 px-3 text-[10px] uppercase text-blue-300 font-semibold">Admin</div>
              {ADMIN_NAV.map(({ to, icon: Icon, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                      isActive ? "bg-white text-primary-600" : "text-blue-100 hover:bg-primary-700 hover:text-white"
                    )
                  }
                >
                  <Icon size={18} />
                  {label}
                </NavLink>
              ))}
            </>
          )}
        </nav>

        <div className="px-3 py-4 border-t border-primary-700">
          <div className="flex items-center gap-2 px-2 py-2 rounded-lg">
            <div className="w-7 h-7 bg-white rounded-full flex items-center justify-center flex-shrink-0 text-sm">
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
              <p className="text-blue-300 text-xs truncate">@{user?.username}</p>
            </div>
            <button onClick={logout} title="Đăng xuất" className="text-blue-200 hover:text-white transition-colors">
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
