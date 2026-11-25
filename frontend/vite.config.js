import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api and /health to the FastAPI backend, so no CORS setup is needed locally.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": process.env.VITE_BACKEND_URL || "http://localhost:8000",
      "/health": process.env.VITE_BACKEND_URL || "http://localhost:8000",
    },
  },
});
