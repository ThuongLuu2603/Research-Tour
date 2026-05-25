import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import {
  LayoutDashboard, Table2, BarChart3, PieChart,
  Building2, Radio, LogOut, User, Settings
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/data", icon: Table2, label: "Research Grid" },
  { to: "/price", icon: BarChart3, label: "Phân tích Giá" },
  { to: "/market", icon: PieChart, label: "Thị trường" },
  { to: "/competitor", icon: Building2, label: "Đối thủ" },
  { to: "/scraper", icon: Radio, label: "Scraper Hub" },
  { to: "/settings", icon: Settings, label: "Cài đặt" },
];

export default function Layout() {
  const { user, logout } = useAuth();

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {/* Sidebar */}
      <aside className="w-56 bg-primary-600 flex flex-col flex-shrink-0">
        {/* Brand */}
        <div className="px-4 py-5 border-b border-primary-700">
          <div className="flex items-center gap-2">
            <span className="text-2xl">✈️</span>
            <div>
              <p className="text-white font-bold text-sm leading-tight">OTA Research</p>
              <p className="text-blue-200 text-xs">Platform</p>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                  isActive
                    ? "bg-white text-primary-600"
                    : "text-blue-100 hover:bg-primary-700 hover:text-white"
                )
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* User */}
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
            <button
              onClick={logout}
              title="Đăng xuất"
              className="text-blue-200 hover:text-white transition-colors"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
