import { defineStore } from "pinia";

export const AUTH_TOKEN_STORAGE_KEY = "evitrace_token";

interface AuthState {
  token: string;
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    token: localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) ?? ""
  }),
  actions: {
    setToken(token: string) {
      this.token = token;
      localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
    },
    clearToken() {
      this.token = "";
      localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    }
  }
});
