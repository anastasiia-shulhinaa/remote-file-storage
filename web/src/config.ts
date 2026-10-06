// Client-safe configuration. Only VITE_* variables are exposed to the browser,
// so privileged credentials must never be defined with that prefix.
const DEFAULT_API_URL = "http://127.0.0.1:8000";

export const config = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_URL).replace(/\/+$/, ""),
} as const;
