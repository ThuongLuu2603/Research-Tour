import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } },
  },
  build: {
    // Tách vendor nặng ra chunk riêng → cache lâu, tải lần đầu nhẹ hơn.
    rollupOptions: {
      output: {
        manualChunks: {
          "react-vendor": ["react", "react-dom", "react-router-dom"],
          charts: ["recharts"],
          query: ["@tanstack/react-query"],
        },
      },
    },
    chunkSizeWarningLimit: 900,
  },
});
