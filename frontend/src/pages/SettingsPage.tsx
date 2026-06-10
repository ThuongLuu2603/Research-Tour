import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import {
  updateProfile, changePassword, listUsers, createUser, updateUser, AdminUser,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  User, Lock, Users, Save, Plus, Shield, Eye, EyeOff, Pencil, X,
  KeyRound, Lock as LockIcon, Unlock, ChevronDown, ChevronUp, Clock,
} from "lucide-react";

const AVATAR_PRESETS = ["✈️", "📊", "🌏", "🗺️", "🏖️", "⛰️", "🎯", "💼"];

/** Hiển thị avatar: emoji hoặc URL ảnh */
function AvatarDisplay({ value, size = "md" }: { value?: string; size?: "sm" | "md" | "lg" }) {
  const dim = size === "lg" ? "w-16 h-16 text-3xl" : size === "sm" ? "w-9 h-9 text-base" : "w-11 h-11 text-xl";
  const isImg = value && value.startsWith("http");
  return (
    <div className={cn("shrink-0 rounded-full flex items-center justify-center bg-primary-50 ring-1 ring-primary-100 overflow-hidden", dim)}>
      {isImg ? (
        <img src={value} alt="" className="w-full h-full object-cover" />
      ) : value ? (
        <span>{value}</span>
      ) : (
        <User className="text-primary-400" size={size === "lg" ? 28 : 18} />
      )}
    </div>
  );
}

/** Format last_login dễ đọc */
function formatLastLogin(iso: string | null): string {
  if (!iso) return "Chưa đăng nhập";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "Chưa đăng nhập";
  return d.toLocaleString("vi-VN", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export default function SettingsPage() {
  const { user, refreshUser } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";

  const [displayName, setDisplayName] = useState(user?.display_name || "");
  const [avatarUrl, setAvatarUrl] = useState(user?.avatar_url || "");
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [showCurrentPw, setShowCurrentPw] = useState(false);
  const [showNewPw, setShowNewPw] = useState(false);

  // Tạo user mới
  const [showCreate, setShowCreate] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newUserPw, setNewUserPw] = useState("");
  const [newUserName, setNewUserName] = useState("");
  const [newUserRole, setNewUserRole] = useState("analyst");

  // Modal sửa user
  const [editUser, setEditUser] = useState<AdminUser | null>(null);
  const [editName, setEditName] = useState("");
  const [editRole, setEditRole] = useState("analyst");

  // Modal reset mật khẩu
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
  const [resetPw, setResetPw] = useState("");
  const [showResetPw, setShowResetPw] = useState(false);

  // Toast tự ẩn
  const [msg, setMsg] = useState("");
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(""), 3000);
    return () => clearTimeout(t);
  }, [msg]);

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
      setNewUsername(""); setNewUserPw(""); setNewUserName(""); setNewUserRole("analyst");
      setShowCreate(false);
      setMsg("Đã tạo người dùng mới");
    },
  });

  const toggleUser = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) =>
      updateUser(id, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const saveEditUser = useMutation({
    mutationFn: () =>
      updateUser(editUser!.id, { display_name: editName, role: editRole }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      setEditUser(null);
      setMsg("Đã cập nhật người dùng");
    },
  });

  const resetUserPw = useMutation({
    mutationFn: () => updateUser(resetTarget!.id, { password: resetPw }),
    onSuccess: () => {
      setResetTarget(null); setResetPw("");
      setMsg("Đã đặt lại mật khẩu");
    },
  });

  function openEdit(u: AdminUser) {
    setEditUser(u);
    setEditName(u.display_name);
    setEditRole(u.role);
  }

  function submitEdit() {
    if (!editUser) return;
    // Xác nhận khi đổi vai trò
    if (editRole !== editUser.role) {
      const ok = window.confirm(
        `Đổi vai trò của "${editUser.display_name}" từ ${editUser.role} sang ${editRole}?`
      );
      if (!ok) return;
    }
    saveEditUser.mutate();
  }

  function openReset(u: AdminUser) {
    setResetTarget(u);
    setResetPw("");
    setShowResetPw(false);
  }

  const isSuperAdmin = (u: AdminUser) => u.username === "admin";

  return (
    <div className="p-6 max-w-3xl space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Cài đặt tài khoản</h1>
        <p className="text-sm text-gray-500 mt-0.5">Quản lý hồ sơ, mật khẩu{isAdmin ? " và người dùng hệ thống" : ""}.</p>
      </div>

      {/* Toast thành công */}
      {msg && (
        <div className="fixed top-5 right-5 z-50 flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-medium text-white shadow-lg"
          style={{ animation: "settingsToastIn 0.2s ease-out" }}>
          <style>{`@keyframes settingsToastIn{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}`}</style>
          <Save size={15} /> {msg}
        </div>
      )}

      {/* ===== Hồ sơ ===== */}
      <section className="card p-6 space-y-5">
        <h2 className="font-semibold text-gray-900 flex items-center gap-2">
          <User size={18} className="text-primary-600" /> Hồ sơ
        </h2>

        <div className="flex items-start gap-5">
          <AvatarDisplay value={avatarUrl} size="lg" />
          <div className="flex-1 space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Tên hiển thị</label>
              <input className="input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Avatar (emoji hoặc URL ảnh)</label>
              <input className="input mb-2" value={avatarUrl} onChange={(e) => setAvatarUrl(e.target.value)} placeholder="✈️ hoặc https://..." />
              <div className="flex gap-2 flex-wrap">
                {AVATAR_PRESETS.map((em) => (
                  <button key={em} type="button" onClick={() => setAvatarUrl(em)}
                    className={cn("w-9 h-9 rounded-lg border text-lg transition-colors",
                      avatarUrl === em ? "border-primary-600 bg-primary-50 ring-1 ring-primary-200" : "border-gray-200 hover:border-primary-300")}>
                    {em}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <button onClick={() => saveProfile.mutate()} disabled={saveProfile.isPending} className="btn-primary text-sm">
          <Save size={14} /> {saveProfile.isPending ? "Đang lưu..." : "Lưu hồ sơ"}
        </button>
      </section>

      {/* ===== Đổi mật khẩu ===== */}
      <section className="card p-6 space-y-4">
        <h2 className="font-semibold text-gray-900 flex items-center gap-2">
          <Lock size={18} className="text-primary-600" /> Đổi mật khẩu
        </h2>

        <div className="space-y-3">
          <div className="relative">
            <input className="input pr-10" type={showCurrentPw ? "text" : "password"} placeholder="Mật khẩu hiện tại"
              value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} />
            <button type="button" onClick={() => setShowCurrentPw((v) => !v)}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600" aria-label="Hiện/ẩn mật khẩu">
              {showCurrentPw ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          <div>
            <div className="relative">
              <input className="input pr-10" type={showNewPw ? "text" : "password"} placeholder="Mật khẩu mới (≥6 ký tự)"
                value={newPw} onChange={(e) => setNewPw(e.target.value)} />
              <button type="button" onClick={() => setShowNewPw((v) => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600" aria-label="Hiện/ẩn mật khẩu">
                {showNewPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            {newPw.length > 0 && newPw.length < 6 && (
              <p className="text-xs text-accent-600 mt-1">Mật khẩu phải có ít nhất 6 ký tự.</p>
            )}
          </div>
        </div>

        <button onClick={() => savePassword.mutate()}
          disabled={!currentPw || newPw.length < 6 || savePassword.isPending} className="btn-primary text-sm">
          <Lock size={14} /> {savePassword.isPending ? "Đang đổi..." : "Đổi mật khẩu"}
        </button>
      </section>

      {/* ===== Quản lý người dùng (admin) ===== */}
      {isAdmin && (
        <section className="card p-6 space-y-5">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <Users size={18} className="text-primary-600" /> Quản lý người dùng
            </h2>
            <button onClick={() => setShowCreate((v) => !v)} className="btn-secondary text-sm">
              {showCreate ? <ChevronUp size={14} /> : <Plus size={14} />} Tạo người dùng mới
            </button>
          </div>

          {/* Form tạo user — collapsible */}
          {showCreate && (
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <input className="input bg-white" placeholder="Username" value={newUsername} onChange={(e) => setNewUsername(e.target.value)} />
                <input className="input bg-white" placeholder="Tên hiển thị" value={newUserName} onChange={(e) => setNewUserName(e.target.value)} />
                <input className="input bg-white" type="password" placeholder="Mật khẩu (≥6 ký tự)" value={newUserPw} onChange={(e) => setNewUserPw(e.target.value)} />
                <select className="input bg-white" value={newUserRole} onChange={(e) => setNewUserRole(e.target.value)}>
                  <option value="analyst">Analyst</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => addUser.mutate()}
                  disabled={!newUsername || newUserPw.length < 6 || addUser.isPending} className="btn-primary text-sm">
                  <Plus size={14} /> {addUser.isPending ? "Đang tạo..." : "Tạo người dùng"}
                </button>
                <button onClick={() => setShowCreate(false)} className="btn-ghost text-sm">Hủy</button>
              </div>
            </div>
          )}

          {/* Bảng user */}
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-xs font-medium text-gray-500">
                  <th className="text-left py-2.5 px-1">Người dùng</th>
                  <th className="text-left py-2.5 px-1">Vai trò</th>
                  <th className="text-left py-2.5 px-1">Trạng thái</th>
                  <th className="text-left py-2.5 px-1">Đăng nhập gần nhất</th>
                  <th className="text-right py-2.5 px-1">Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {(users ?? []).map((u: AdminUser) => (
                  <tr key={u.id} className="border-b border-gray-100 hover:bg-gray-50/60">
                    <td className="py-3 px-1">
                      <div className="flex items-center gap-3">
                        <AvatarDisplay value={u.avatar_url} size="sm" />
                        <div className="min-w-0">
                          <p className="font-medium text-gray-900 truncate flex items-center gap-1.5">
                            {u.display_name}
                            {isSuperAdmin(u) && (
                              <span className="badge-brand !py-0 text-[10px]">Super admin</span>
                            )}
                          </p>
                          <p className="text-xs text-gray-400">@{u.username}</p>
                        </div>
                      </div>
                    </td>
                    <td className="py-3 px-1">
                      <span className={cn("badge",
                        u.role === "admin" ? "bg-purple-100 text-purple-800" : "bg-gray-100 text-gray-600")}>
                        <Shield size={10} className="mr-1" />{u.role === "admin" ? "Admin" : "Analyst"}
                      </span>
                    </td>
                    <td className="py-3 px-1">
                      <span className={cn("badge",
                        u.is_active ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500")}>
                        {u.is_active ? "Hoạt động" : "Vô hiệu"}
                      </span>
                    </td>
                    <td className="py-3 px-1 text-xs text-gray-500">
                      <span className="inline-flex items-center gap-1">
                        <Clock size={11} className="text-gray-400" />
                        {formatLastLogin(u.last_login)}
                      </span>
                    </td>
                    <td className="py-3 px-1">
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => openEdit(u)} title="Sửa"
                          className="p-1.5 rounded-md text-gray-500 hover:bg-primary-50 hover:text-primary-700 transition-colors">
                          <Pencil size={15} />
                        </button>
                        <button onClick={() => openReset(u)} title="Đặt lại mật khẩu"
                          className="p-1.5 rounded-md text-gray-500 hover:bg-amber-50 hover:text-amber-700 transition-colors">
                          <KeyRound size={15} />
                        </button>
                        {!isSuperAdmin(u) ? (
                          <button
                            onClick={() => toggleUser.mutate({ id: u.id, is_active: !u.is_active })}
                            disabled={toggleUser.isPending}
                            title={u.is_active ? "Khóa" : "Mở khóa"}
                            className={cn("p-1.5 rounded-md transition-colors disabled:opacity-50",
                              u.is_active
                                ? "text-gray-500 hover:bg-accent-50 hover:text-accent-600"
                                : "text-gray-500 hover:bg-green-50 hover:text-green-700")}>
                            {u.is_active ? <LockIcon size={15} /> : <Unlock size={15} />}
                          </button>
                        ) : (
                          <span className="p-1.5 inline-flex" title="Không thể khóa super admin">
                            <LockIcon size={15} className="text-gray-200" />
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {(users ?? []).length === 0 && (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-sm text-gray-400">Chưa có người dùng nào.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ===== Modal SỬA user ===== */}
      {editUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setEditUser(null)}>
          <div className="card w-full max-w-md p-6 space-y-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                <Pencil size={16} className="text-primary-600" /> Sửa người dùng
              </h3>
              <button onClick={() => setEditUser(null)} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>

            <div className="flex items-center gap-3">
              <AvatarDisplay value={editUser.avatar_url} size="md" />
              <p className="text-sm text-gray-500">@{editUser.username}</p>
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Tên hiển thị</label>
              <input className="input" value={editName} onChange={(e) => setEditName(e.target.value)} />
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Vai trò</label>
              {isSuperAdmin(editUser) ? (
                <>
                  <input className="input bg-gray-50 text-gray-500" value="Admin" disabled />
                  <p className="text-xs text-gray-400 mt-1">Không thể đổi vai trò của super admin.</p>
                </>
              ) : (
                <select className="input" value={editRole} onChange={(e) => setEditRole(e.target.value)}>
                  <option value="analyst">Analyst</option>
                  <option value="admin">Admin</option>
                </select>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 pt-1">
              <button onClick={() => setEditUser(null)} className="btn-secondary text-sm">Hủy</button>
              <button onClick={submitEdit} disabled={!editName.trim() || saveEditUser.isPending} className="btn-primary text-sm">
                <Save size={14} /> {saveEditUser.isPending ? "Đang lưu..." : "Lưu thay đổi"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== Modal RESET mật khẩu ===== */}
      {resetTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setResetTarget(null)}>
          <div className="card w-full max-w-md p-6 space-y-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                <KeyRound size={16} className="text-amber-600" /> Đặt lại mật khẩu
              </h3>
              <button onClick={() => setResetTarget(null)} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>

            <p className="text-sm text-gray-500">
              Đặt mật khẩu mới cho <span className="font-medium text-gray-900">{resetTarget.display_name}</span> (@{resetTarget.username}).
            </p>

            <div>
              <div className="relative">
                <input className="input pr-10" type={showResetPw ? "text" : "password"} placeholder="Mật khẩu mới (≥6 ký tự)"
                  value={resetPw} onChange={(e) => setResetPw(e.target.value)} autoFocus />
                <button type="button" onClick={() => setShowResetPw((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600" aria-label="Hiện/ẩn mật khẩu">
                  {showResetPw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {resetPw.length > 0 && resetPw.length < 6 && (
                <p className="text-xs text-accent-600 mt-1">Mật khẩu phải có ít nhất 6 ký tự.</p>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 pt-1">
              <button onClick={() => setResetTarget(null)} className="btn-secondary text-sm">Hủy</button>
              <button onClick={() => resetUserPw.mutate()}
                disabled={resetPw.length < 6 || resetUserPw.isPending} className="btn-primary text-sm">
                <KeyRound size={14} /> {resetUserPw.isPending ? "Đang lưu..." : "Đặt lại"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
