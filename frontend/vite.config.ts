import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  // ID build duy nhất mỗi lần build → dùng để vô hiệu hoá cache localStorage cũ sau deploy
  // (tránh hydrate dữ liệu schema cũ vào code mới gây crash trang).
  define: { __APP_BUILD_ID__: JSON.stringify(String(Date.now())) },
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
