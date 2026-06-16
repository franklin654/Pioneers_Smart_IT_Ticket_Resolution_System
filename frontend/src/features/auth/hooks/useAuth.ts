import { useState, useCallback } from "react";
import {
  login as apiLogin,
  logout as apiLogout,
  setClientToken,
  setUnauthorizedHandler,
} from "../../../api/client";
import type { AuthTokenResponse } from "../../../types";

interface AuthState {
  token: string | null;
  username: string | null;
}

const stored = sessionStorage.getItem("token");
const storedUser = sessionStorage.getItem("username");

export function useAuth() {
  const [auth, setAuth] = useState<AuthState>({
    token: stored,
    username: storedUser,
  });

  if (stored) setClientToken(stored);

  const login = useCallback(
    async (username: string, password: string): Promise<AuthTokenResponse> => {
      const res = await apiLogin(username, password);
      setClientToken(res.access_token);
      sessionStorage.setItem("token", res.access_token);
      sessionStorage.setItem("username", username);
      setAuth({ token: res.access_token, username });
      return res;
    },
    [],
  );

  const signOut = useCallback(async () => {
    await apiLogout().catch(() => null);
    sessionStorage.clear();
    setAuth({ token: null, username: null });
  }, []);

  setUnauthorizedHandler(signOut);

  return { ...auth, isAuthenticated: auth.token !== null, login, signOut };
}
