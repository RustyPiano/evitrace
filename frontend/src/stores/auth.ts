import { defineStore } from "pinia";

import { apiClient } from "@/api/client";

export const AUTH_TOKEN_STORAGE_KEY = "evitrace_token";

const AUTH_USER_STORAGE_KEY = "evitrace_user";

export interface AuthUser {
  id: string;
  username: string;
  role: "analyst" | "admin";
  is_active?: boolean;
}

interface LoginPayload {
  username: string;
  password: string;
}

interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  user: AuthUser;
}

interface AuthState {
  token: string;
  user: AuthUser | null;
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    token: localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) ?? "",
    user: parseStoredUser()
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token),
    isAdmin: (state) => state.user?.role === "admin"
  },
  actions: {
    setSession(token: string, user: AuthUser) {
      this.token = token;
      this.user = user;
      localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
      localStorage.setItem(AUTH_USER_STORAGE_KEY, JSON.stringify(user));
    },
    setToken(token: string) {
      this.token = token;
      localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
    },
    clearToken() {
      this.clearSession();
    },
    clearSession() {
      this.token = "";
      this.user = null;
      localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
      localStorage.removeItem(AUTH_USER_STORAGE_KEY);
    },
    async login(payload: LoginPayload) {
      const response = await apiClient.post<LoginResponse>("/auth/login", payload);
      this.setSession(response.data.access_token, response.data.user);
      return response.data.user;
    },
    logout() {
      this.clearSession();
    },
    async fetchMe() {
      const response = await apiClient.get<AuthUser>("/auth/me");
      this.user = response.data;
      localStorage.setItem(AUTH_USER_STORAGE_KEY, JSON.stringify(response.data));
      return response.data;
    }
  }
});

function parseStoredUser(): AuthUser | null {
  const raw = localStorage.getItem(AUTH_USER_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    localStorage.removeItem(AUTH_USER_STORAGE_KEY);
    return null;
  }
}
