import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  ReactNode,
} from "react";

interface ImportMetaEnv {
  VITE_API_BASE?: string;
}

const API_BASE: string =
  (import.meta.env as ImportMetaEnv).VITE_API_BASE || "http://localhost:3000";

interface User {
  username: string;
}

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  authenticated: boolean;
  refreshSession: () => Promise<User | null>;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const USERNAME_REGEX = /^[a-zA-Z0-9._]{3,32}$/;
const PASSWORD_MIN_LENGTH = 8;
const PASSWORD_MAX_LENGTH = 128;

class AuthValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthValidationError";
  }
}

async function readJson(response: Response): Promise<any> {
  try {
    return await response.json();
  } catch (_) {
    return null;
  }
}

function normalizeUsername(value: unknown): string {
  return String(value || "").trim();
}

function validateUsername(username: string): string {
  if (!username) {
    throw new AuthValidationError("Username is required");
  }
  if (username.length < 3) {
    throw new AuthValidationError("Username must be at least 3 characters");
  }
  if (username.length > 32) {
    throw new AuthValidationError("Username must be at most 32 characters");
  }
  if (!USERNAME_REGEX.test(username)) {
    throw new AuthValidationError(
      "Username may contain only letters, numbers, dot and underscore"
    );
  }
  return username;
}

function validatePassword(password: unknown): string {
  const value = String(password ?? "");
  if (value.length < PASSWORD_MIN_LENGTH) {
    throw new AuthValidationError(
      "Password must be at least " + PASSWORD_MIN_LENGTH + " characters"
    );
  }
  if (value.length > PASSWORD_MAX_LENGTH) {
    throw new AuthValidationError(
      "Password must be at most " + PASSWORD_MAX_LENGTH + " characters"
    );
  }
  return value;
}

function prepareCredentials(username: unknown, password: unknown): { username: string; password: string } {
  return {
    username: validateUsername(normalizeUsername(username)),
    password: validatePassword(password),
  };
}

async function jsonRequest(path: string, body: unknown, method: string): Promise<any> {
  const response = await fetch(API_BASE + path, {
    method: method || "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const data = await readJson(response);

  if (!response.ok) {
    throw new Error((data && (data.detail || data.msg)) || "HTTP " + response.status);
  }

  return data;
}

export function AuthProvider(props: { children: ReactNode }): React.ReactElement {
  const children = props.children;
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const refreshSession = useCallback(function refreshSession(): Promise<User | null> {
    return fetch(API_BASE + "/auth/me", {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: "application/json",
      },
    })
      .then(function (response) {
        if (!response.ok) {
          setUser(null);
          return null;
        }
        return readJson(response);
      })
      .then(function (data) {
        const nextUser = data && data.user ? data.user : null;
        setUser(nextUser);
        return nextUser;
      })
      .catch(function () {
        setUser(null);
        return null;
      })
      .finally(function () {
        setLoading(false);
      });
  }, []);

  useEffect(function () {
    void refreshSession();
  }, [refreshSession]);

  const login = useCallback(
    function login(username: string, password: string): Promise<void> {
      const payload = prepareCredentials(username, password);
      return jsonRequest("/auth/login", payload, "POST")
        .then(function () {
          return refreshSession();
        })
        .then(function () {
          return;
        });
    },
    [refreshSession]
  );

  const register = useCallback(
    function register(username: string, password: string): Promise<void> {
      const payload = prepareCredentials(username, password);
      return jsonRequest("/auth/register", payload, "POST")
        .then(function () {
          return login(payload.username, payload.password);
        })
        .then(function () {
          return;
        });
    },
    [login]
  );

  const logout = useCallback(function logout(): Promise<void> {
    return fetch(API_BASE + "/auth/logout", {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
      },
    })
      .catch(function () {
        // ignore network errors
      })
      .finally(function () {
        setUser(null);
      })
      .then(function () {
        return;
      });
  }, []);

  const value = useMemo<AuthContextValue>(
    function () {
      return {
        user: user,
        loading: loading,
        authenticated: Boolean(user),
        refreshSession: refreshSession,
        login: login,
        register: register,
        logout: logout,
      };
    },
    [user, loading, refreshSession, login, register, logout]
  );

  return React.createElement(AuthContext.Provider, { value: value }, children);
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return ctx;
}

export { AuthValidationError, validateUsername, validatePassword };