import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vite";

// 约定：后端 FastAPI 本地开发地址（你也可以改成 env）
// - 目的：前端 fetch /api/* 时无需处理 CORS，统一走 Vite proxy
const BACKEND_TARGET = process.env.VITE_BACKEND_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],

  // 关键：提供 @/ 绝对导入（与 tsconfig paths 对齐）
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },

  // 关键：联调时统一走 /api 前缀，避免 CORS & 让服务端路由更清晰
  server: {
    proxy: {
      "/api": {
        target: BACKEND_TARGET,
        changeOrigin: true,
        secure: false,
      },
    },
  },

  // 可选但推荐：统一构建产物目录（便于后端静态托管/部署）
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
