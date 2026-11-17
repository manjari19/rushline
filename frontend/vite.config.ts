import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev, /api/* is forwarded to the FastAPI backend (the prefix is stripped).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.API_URL ?? "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
