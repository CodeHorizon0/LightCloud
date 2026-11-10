import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { ApiError, isRecord, requestJson } from "../api";
import { clearPreviewCache } from "../utils/previewCache";
import {
  SESSION_KEY,
  allowSession,
  clearSnapshot,
  forgetSession,
  isSignedOut,
  rememberSession,
  savedSession,
} from "../utils/offlineStore";
import { parseUser, sameUser } from "./user";
import type { User } from "./user";
import { AuthContext } from "./useAuth";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [passwordChanged, setPasswordChanged] = useState(false);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(!navigator.onLine);
  const revision = useRef(0);
  const currentUser = useRef<User | null>(null);
  const activeEpoch = useRef<string | null>(null);
  const pendingLogout = useRef<Promise<void> | null>(null);

  const acceptUser = useCallback(function acceptUser(
    incoming: User,
    persist = true,
  ): User {
    const previous = currentUser.current;
    const next = incoming;
    currentUser.current = next;
    if (persist) rememberSession(next);
    activeEpoch.current = savedSession()?.epoch ?? null;
    if (!sameUser(previous, next)) setUser(next);
    return next;
  }, []);

  const clearSession = useCallback(function clearSession() {
    revision.current += 1;
    const persisted = forgetSession();
    const account = currentUser.current?.id ?? persisted;
    if (account) void clearPreviewCache(account);
    currentUser.current = null;
    activeEpoch.current = null;
    setUser(null);
    setLoading(false);
  }, []);

  const markOffline = useCallback(function markOffline() {
    setOffline(true);
  }, []);
  const markOnline = useCallback(function markOnline() {
    setOffline(false);
    if (!currentUser.current || isSignedOut()) return;
    const saved = savedSession();
    if (!saved || Date.now() - saved.verified > 60_000)
      rememberSession(currentUser.current);
  }, []);
  const refreshSession = useCallback(
    async function refreshSession(signal?: AbortSignal): Promise<User | null> {
      const current = ++revision.current;
      if (isSignedOut()) {
        currentUser.current = null;
        setUser(null);
        setLoading(false);
        return null;
      }
      const saved = savedSession();
      try {
        const timeout = AbortSignal.timeout(6000);
        const data = await requestJson("/auth/me", {
          signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
          cache: "no-store",
        });
        const identity = isRecord(data) ? parseUser(data.user) : null;
        if (!identity) throw new Error("Invalid session response");
        if (current !== revision.current || signal?.aborted || isSignedOut())
          return null;
        const previous = currentUser.current?.id ?? saved?.user.id;
        if (previous && previous !== identity.id) {
          void clearPreviewCache(previous);
          void clearSnapshot(previous);
        }
        setOffline(false);
        return acceptUser(identity);
      } catch (error) {
        if (current !== revision.current || signal?.aborted) throw error;
        if (
          error instanceof ApiError &&
          (error.status === 401 || error.status === 403)
        ) {
          clearSession();
          return null;
        }
        const unavailable =
          error instanceof TypeError ||
          (error instanceof DOMException && error.name === "TimeoutError") ||
          (error instanceof ApiError && error.status >= 500);
        if (unavailable && saved && savedSession()?.epoch === saved.epoch) {
          setOffline(true);
          return acceptUser(saved.user, false);
        }
        setOffline(true);
        throw error;
      } finally {
        if (current === revision.current && !signal?.aborted) setLoading(false);
      }
    },
    [acceptUser, clearSession],
  );

  useEffect(
    function loadSession() {
      const controller = new AbortController();
      function refresh() {
        void refreshSession(controller.signal).catch(function () {});
      }
      function connected() {
        if (!currentUser.current) setOffline(false);
      }
      function changed(event: StorageEvent) {
        if (event.key !== SESSION_KEY && event.key !== null) return;
        const saved = savedSession();
        if (
          saved?.user.id === currentUser.current?.id &&
          saved?.epoch === activeEpoch.current
        ) {
          if (saved) acceptUser(saved.user, false);
          return;
        }
        revision.current += 1;
        if (currentUser.current && currentUser.current.id !== saved?.user.id)
          void clearPreviewCache(currentUser.current.id);
        currentUser.current = null;
        activeEpoch.current = null;
        setUser(null);
        if (saved) refresh();
      }
      refresh();
      window.addEventListener("online", connected);
      window.addEventListener("offline", markOffline);
      window.addEventListener("storage", changed);
      return function cleanup() {
        controller.abort();
        window.removeEventListener("online", connected);
        window.removeEventListener("offline", markOffline);
        window.removeEventListener("storage", changed);
      };
    },
    [refreshSession, markOffline, acceptUser],
  );

  useEffect(
    function expireOfflineSession() {
      if (!offline || !user) return;
      const timer = setInterval(function () {
        if (!savedSession()) clearSession();
      }, 30_000);
      return function cleanup() {
        clearInterval(timer);
      };
    },
    [offline, user, clearSession],
  );

  const login = useCallback(
    async function login(username: string, password: string) {
      await pendingLogout.current;
      await requestJson("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: username.trim(), password }),
      });
      clearSession();
      setPasswordChanged(false);
      allowSession();
      const session = await refreshSession();
      if (!session) {
        clearSession();
        throw new Error(
          "Session cookie was blocked. Check the API address and browser settings.",
        );
      }
    },
    [refreshSession, clearSession],
  );

  const register = useCallback(
    async function register(username: string, password: string) {
      await requestJson("/auth/register", {
        method: "POST",
        body: JSON.stringify({ username: username.trim(), password }),
      });
      await login(username, password);
    },
    [login],
  );

  const logout = useCallback(
    async function logout() {
      clearSession();
      const task = requestJson("/auth/logout", {
        method: "POST",
        signal: AbortSignal.timeout(3000),
      }).then(
        function () {},
        function () {},
      );
      pendingLogout.current = task;
      await task;
      if (pendingLogout.current === task) pendingLogout.current = null;
    },
    [clearSession],
  );

  const changePassword = useCallback(
    async function changePassword(
      currentPassword: string,
      newPassword: string,
    ) {
      try {
        await requestJson("/auth/password", {
          method: "PATCH",
          body: JSON.stringify({
            current_password: currentPassword,
            new_password: newPassword,
          }),
          signal: AbortSignal.timeout(15000),
        });
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) clearSession();
        throw error;
      }
      setPasswordChanged(true);
      clearSession();
    },
    [clearSession],
  );

  const value = useMemo(
    function contextValue() {
      return {
        user,
        loading,
        offline,
        passwordChanged,
        markOffline,
        markOnline,
        refreshSession,
        login,
        register,
        changePassword,
        logout,
        clearSession,
      };
    },
    [
      user,
      loading,
      offline,
      passwordChanged,
      markOffline,
      markOnline,
      refreshSession,
      login,
      register,
      changePassword,
      logout,
      clearSession,
    ],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
