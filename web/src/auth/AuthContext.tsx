import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { authApi, getSession, onSessionChange } from "../api/client";
import type { RegisterResponse, User } from "../api/types";

interface AuthState {
  user: User | null;
  login: (identifier: string, password: string) => Promise<void>;
  register: (
    email: string,
    username: string,
    password: string,
    passwordConfirm: string,
    displayName: string,
  ) => Promise<RegisterResponse>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => getSession()?.user ?? null);

  useEffect(() => onSessionChange((session) => setUser(session?.user ?? null)), []);

  // validate a stored session on load (refreshes the token if it has expired)
  useEffect(() => {
    if (getSession()) authApi.me().catch(() => undefined);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      login: async (identifier, password) => {
        await authApi.login(identifier, password);
      },
      register: (email, username, password, passwordConfirm, displayName) =>
        authApi.register(email, username, password, passwordConfirm, displayName),
      logout: () => authApi.logout(),
    }),
    [user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const state = useContext(AuthContext);
  if (!state) throw new Error("useAuth must be used inside AuthProvider");
  return state;
}
