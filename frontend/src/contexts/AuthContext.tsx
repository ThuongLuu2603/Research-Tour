import React, { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { User, getMe } from "@/lib/api";

interface AuthCtx {
  user: User | null;
  isLoading: boolean;
  setToken: (token: string, user: User) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthCtx>({
  user: null,
  isLoading: true,
  setToken: () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) { setIsLoading(false); return; }
    getMe().then(setUser).catch(() => {
      localStorage.removeItem("access_token");
    }).finally(() => setIsLoading(false));
  }, []);

  const setToken = (token: string, u: User) => {
    localStorage.setItem("access_token", token);
    setUser(u);
  };

  const logout = () => {
    localStorage.removeItem("access_token");
    setUser(null);
    window.location.href = "/login";
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, setToken, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
