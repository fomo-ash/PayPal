import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "./api";
import type { PublicConfig, Role, User } from "./types";

interface Auth {
  user: User | null;
  config: PublicConfig | null;
  ready: boolean;
  demoLogin: (role: Role) => Promise<User>;
  paypalLogin: (role: "buyer" | "worker") => Promise<void>;
  finishPayPalLogin: (code: string, state: string) => Promise<User>;
  logout: () => void;
}

const Ctx = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    api<PublicConfig>("/public-config").then(setConfig).catch(() => setConfig(null));
    if (!getToken()) {
      setReady(true);
      return;
    }
    api<User>("/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setReady(true));
  }, []);

  const demoLogin = useCallback(async (role: Role) => {
    const r = await api<{ token: string; user: User }>("/auth/demo", { body: { role } });
    setToken(r.token);
    setUser(r.user);
    return r.user;
  }, []);

  const paypalLogin = useCallback(async (role: "buyer" | "worker") => {
    const r = await api<{ url: string }>(`/auth/paypal/login?role=${role}`);
    window.location.assign(r.url);
  }, []);

  const finishPayPalLogin = useCallback(async (code: string, state: string) => {
    const r = await api<{ token: string; user: User }>("/auth/paypal/callback", { body: { code, state } });
    setToken(r.token);
    setUser(r.user);
    return r.user;
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  return (
    <Ctx.Provider value={{ user, config, ready, demoLogin, paypalLogin, finishPayPalLogin, logout }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth(): Auth {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
