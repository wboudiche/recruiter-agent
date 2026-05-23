/// <reference types="vitest" />
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./test/setup.ts",
    css: true,
    // Playwright e2e specs live under e2e/ and use the @playwright/test
    // runner, not vitest. Excluding the dir keeps `npm test` from
    // attempting to evaluate them in jsdom (which would fail).
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
});
