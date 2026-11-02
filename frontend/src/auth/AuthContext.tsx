import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, setStoredToken, setUnauthorizedHandler, getStoredToken, ApiError } from "@/lib/api";
import type { TokenResponse, User } from "@/lib/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  /** True once the initial token check has completed. */
  ready: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
  refresh: () => Promise<void>;
  /** Permission check; `*` grants everything (Super Administrator). */
  can: (permission: string) => boolean;
  canAny: (...permissions: string[]) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => {
    setStoredToken(null);
    setUser(null);
  }, []);

  const refresh = useCallback(async () => {
    if (!getStoredToken()) {
      setUser(null);
      return;
    }
    setLoading(true);
    try {
      const me = await api.get<User>("/auth/me");
      setUser(me);
    } catch (error) {
      // A rejected token is cleared so the app falls back to the login screen.
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        setStoredToken(null);
      }
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    setLoading(true);
    try {
      const token = await api.post<TokenResponse>("/auth/login", { email, password });
      setStoredToken(token.access_token);
      const me = await api.get<User>("/auth/me");
      setUser(me);
      return me;
    } finally {
      setLoading(false);
    }
  }, []);

  // Restore the session on first load.
  useEffect(() => {
    void refresh().finally(() => setReady(true));
  }, [refresh]);

  // Sign out when any request is rejected with 401.
  useEffect(() => {
    setUnauthorizedHandler(() => logout());
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  const can = useCallback(
    (permission: string) => {
      if (!user) return false;
      if (user.roles.includes("super_admin")) return true;
      return user.permissions.includes(permission);
    },
    [user],
  );

  const canAny = useCallback(
    (...permissions: string[]) => permissions.some((p) => can(p)),
    [can],
  );

  const value = useMemo<AuthState>(
    () => ({ user, loading, ready, login, logout, refresh, can, canAny }),
    [user, loading, ready, login, logout, refresh, can, canAny],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
