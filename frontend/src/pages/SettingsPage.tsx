import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import {
  updateProfile, changePassword, listUsers, createUser, updateUser, AdminUser,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { User, Lock, Users, Save, Plus, Shield } from "lucide-react";

const AVATAR_PRESETS = ["✈️", "📊", "🌏", "🗺️", "🏖️", "⛰️", "🎯", "💼"];

export default function SettingsPage() {
  const { user, refreshUser } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";

  const [displayName, setDisplayName] = useState(user?.display_name || "");
  const [avatarUrl, setAvatarUrl] = useState(user?.avatar_url || "");
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [newUsername, setNewUsername] = useState("");
  const [newUserPw, setNewUserPw] = useState("");
  const [newUserName, setNewUserName] = useState("");
  const [newUserRole, setNewUserRole] = useState("analyst");
  const [msg, setMsg] = useState("");

  const { data: users } = useQuery({
    queryKey: ["admin-users"],
    queryFn: listUsers,
    enabled: isAdmin,
  });

  const saveProfile = useMutation({
    mutationFn: () => updateProfile({ display_name: displayName, avatar_url: avatarUrl }),
    onSuccess: (u) => { refreshUser(u); setMsg("Đã lưu hồ sơ"); },
  });

  const savePassword = useMutation({
    mutationFn: () => changePassword(currentPw, newPw),
    onSuccess: () => { setCurrentPw(""); setNewPw(""); setMsg("Đã đổi mật khẩu"); },
  });

  const addUser = useMutation({
    mutationFn: () => createUser(newUsername, newUserPw, newUserName, newUserRole),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      setNewUsername(""); setNewUserPw(""); setNewUserName(""); setMsg("Đã tạo user mới");
    },
  });

  const toggleUser = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) =>
      updateUser(id, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const resetUserPw = useMutation({
    mutationFn: ({ id, password }: { id: number; password: string }) =>
      updateUser(id, { password }),
    onSuccess: () => setMsg("Đã reset mật khẩu"),
  });

  return (
    <div className="p-6 max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Cài đặt tài khoản</h1>
        <p className="text-sm text-gray-500">Quản lý hồ sơ, mật khẩu và người dùng</p>
      </div>

      {msg && (
        <div className="card p-3 text-sm text-green-700 bg-green-50 border-green-200">{msg}</div>
      )}

      {/* Profile */}
      <div className="card p-5 space-y-4">
        <h2 className="font-semibold flex items-center gap-2"><User size={18} /> Hồ sơ</h2>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Tên hiển thị</label>
          <input className="input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Avatar (emoji hoặc URL ảnh)</label>
          <input className="input mb-2" value={avatarUrl} onChange={(e) => setAvatarUrl(e.target.value)} placeholder="✈️ hoặc https://..." />
          <div className="flex gap-2 flex-wrap">
            {AVATAR_PRESETS.map((em) => (
              <button key={em} type="button" onClick={() => setAvatarUrl(em)}
                className={cn("w-9 h-9 rounded-lg border text-lg", avatarUrl === em ? "border-primary-600 bg-blue-50" : "border-gray-200")}>
                {em}
              </button>
            ))}
          </div>
        </div>
        <button onClick={() => saveProfile.mutate()} disabled={saveProfile.isPending} className="btn-primary text-sm">
          <Save size={14} /> Lưu hồ sơ
        </button>
      </div>

      {/* Password */}
      <div className="card p-5 space-y-4">
        <h2 className="font-semibold flex items-center gap-2"><Lock size={18} /> Đổi mật khẩu</h2>
        <input className="input" type="password" placeholder="Mật khẩu hiện tại" value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} />
        <input className="input" type="password" placeholder="Mật khẩu mới (≥6 ký tự)" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
        <button onClick={() => savePassword.mutate()} disabled={!currentPw || newPw.length < 6 || savePassword.isPending} className="btn-primary text-sm">
          <Lock size={14} /> Đổi mật khẩu
        </button>
      </div>

      {/* Admin: user management */}
      {isAdmin && (
        <div className="card p-5 space-y-4">
          <h2 className="font-semibold flex items-center gap-2"><Users size={18} /> Quản lý người dùng</h2>

          <div className="grid grid-cols-2 gap-3">
            <input className="input" placeholder="Username" value={newUsername} onChange={(e) => setNewUsername(e.target.value)} />
            <input className="input" placeholder="Tên hiển thị" value={newUserName} onChange={(e) => setNewUserName(e.target.value)} />
            <input className="input" type="password" placeholder="Mật khẩu" value={newUserPw} onChange={(e) => setNewUserPw(e.target.value)} />
            <select className="input" value={newUserRole} onChange={(e) => setNewUserRole(e.target.value)}>
              <option value="analyst">Analyst</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <button onClick={() => addUser.mutate()} disabled={!newUsername || newUserPw.length < 6 || addUser.isPending} className="btn-primary text-sm">
            <Plus size={14} /> Tạo người dùng
          </button>

          <table className="w-full text-sm mt-4">
            <thead>
              <tr className="border-b text-xs text-gray-500">
                <th className="text-left py-2">User</th>
                <th className="text-left py-2">Vai trò</th>
                <th className="text-left py-2">Trạng thái</th>
                <th className="text-left py-2">Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {(users ?? []).map((u: AdminUser) => (
                <tr key={u.id} className="border-b border-gray-100">
                  <td className="py-2">
                    <p className="font-medium">{u.display_name}</p>
                    <p className="text-xs text-gray-400">@{u.username}</p>
                  </td>
                  <td className="py-2">
                    <span className={cn("badge text-xs", u.role === "admin" ? "bg-purple-100 text-purple-800" : "bg-gray-100")}>
                      <Shield size={10} className="inline mr-1" />{u.role}
                    </span>
                  </td>
                  <td className="py-2">{u.is_active ? "Hoạt động" : "Vô hiệu"}</td>
                  <td className="py-2 space-x-2">
                    {u.username !== "admin" && (
                      <>
                        <button className="text-xs text-blue-600" onClick={() => toggleUser.mutate({ id: u.id, is_active: !u.is_active })}>
                          {u.is_active ? "Khóa" : "Mở"}
                        </button>
                        <button className="text-xs text-amber-600" onClick={() => {
                          const pw = prompt(`Mật khẩu mới cho ${u.username}:`);
                          if (pw && pw.length >= 6) resetUserPw.mutate({ id: u.id, password: pw });
                        }}>Reset MK</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Google credentials hint for admin */}
      {isAdmin && (
        <div className="card p-5 bg-blue-50 border-blue-200 text-sm text-blue-900">
          <p className="font-semibold mb-1">Cấu hình Google Sheet (Scraper)</p>
          <p>Trên Render free: vào <strong>Environment</strong> → thêm biến <code className="bg-white px-1 rounded">GOOGLE_CREDENTIALS_JSON</code> → dán toàn bộ nội dung file <code className="bg-white px-1 rounded">credentials.json</code> → Save → Redeploy.</p>
          <p className="mt-1 text-xs text-blue-700">Local: đặt file tại <code>ota-platform/credentials.json</code> hoặc <code>backend/credentials.json</code></p>
        </div>
      )}
    </div>
  );
}
