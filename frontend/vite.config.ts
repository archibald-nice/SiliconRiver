import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "0.0.0.0",  // 允许外部访问
    proxy: {
      // 反向代理所有 /api 请求到后端服务器
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path,  // 保持路径不变
      },
      // 健康检查端点也代理
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
        secure: false,
      },
    },
    hmr: {
      protocol: "ws",
      host: "localhost",  // 改为你的服务器地址或 IP
      port: 5173,
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          "three": ["three"],
          "react-vendor": ["react", "react-dom"],
          "ui-vendor": ["@headlessui/react", "@heroicons/react"],
        },
      },
    },
  },
  optimizeDeps: {
    include: ["react", "react-dom", "three"],
  },
});