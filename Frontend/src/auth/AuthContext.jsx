import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:3000";

const AuthContext = createContext(null);

const USERNAME_REGEX = /^[a-zA-Z0-9._]{3,32}$/;
const PASSWORD_MIN_LENGTH = 8;
const PASSWORD_MAX_LENGTH = 128;

function AuthValidationError(message) {
  this.name = "AuthValidationError";
  this.message = message;
  if (Error.captureStackTrace) {
    Error.captureStackTrace(this, AuthValidationError);
  } else {
    this.stack = new Error(message).stack;
  }
}
AuthValidationError.prototype = Object.create(Error.prototype);
AuthValidationError.prototype.constructor = AuthValidationError;

async function readJson(response) {
  try {
    return await response.json();
  } catch (error) {
    return null;
  }
}

function normalizeUsername(value) {
  return String(value || "").trim();
}

function validateUsername(username) {
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

function validatePassword(password) {
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

function prepareCredentials(username, password) {
  return {
    username: validateUsername(normalizeUsername(username)),
    password: validatePassword(password),
  };
}

async function jsonRequest(path, body, method) {
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

export function AuthProvider(props) {
  const children = props.children;
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refreshSession = useCallback(async function refreshSession() {
    try {
      const response = await fetch(API_BASE + "/auth/me", {
        method: "GET",
        credentials: "include",
        headers: {
          Accept: "application/json",
        },
      });

      if (!response.ok) {
        setUser(null);
        return null;
      }

      const data = await readJson(response);
      const nextUser = data && data.user ? data.user : null;
      setUser(nextUser);
      return nextUser;
    } catch (error) {
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(function () {
    void refreshSession();
  }, [refreshSession]);

  const login = useCallback(
    async function login(username, password) {
      const payload = prepareCredentials(username, password);
      await jsonRequest("/auth/login", payload, "POST");
      await refreshSession();
    },
    [refreshSession]
  );

  const register = useCallback(
    async function register(username, password) {
      const payload = prepareCredentials(username, password);
      await jsonRequest("/auth/register", payload, "POST");
      await login(payload.username, payload.password);
    },
    [login]
  );

  const logout = useCallback(async function logout() {
    try {
      await fetch(API_BASE + "/auth/logout", {
        method: "POST",
        credentials: "include",
        headers: {
          Accept: "application/json",
        },
      });
    } finally {
      setUser(null);
    }
  }, []);

  const value = useMemo(
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

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return ctx;
}

export { AuthValidationError, validateUsername, validatePassword };