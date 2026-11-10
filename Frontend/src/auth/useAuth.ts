import { createContext, useContext } from "react";

import type { User } from "./user";
export type { User } from "./user";

export interface AuthContextValue {
  user: User | null;
  loading: boolean;
  offline: boolean;
  passwordChanged: boolean;
  markOffline: () => void;
  markOnline: () => void;
  refreshSession: (signal?: AbortSignal) => Promise<User | null>;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  changePassword: (
    currentPassword: string,
    newPassword: string,
  ) => Promise<void>;
  logout: () => Promise<void>;
  clearSession: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
