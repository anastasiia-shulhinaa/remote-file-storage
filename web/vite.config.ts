import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the browser talks to Vite, which forwards REST calls to FastAPI.
// The Web client never talks to PostgreSQL or Supabase Storage directly.
// NASTUSHA_API_URL: the old name, still accepted
const API_TARGET = process.env.MINIDRIVE_API_URL ?? process.env.NASTUSHA_API_URL ?? "http://127.0.0.1:8000";
const API_PATHS = ["/auth", "/folders", "/files", "/sync", "/synchronizations", "/settings", "/health"];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(API_PATHS.map((path) => [path, { target: API_TARGET, changeOrigin: true }])),
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
