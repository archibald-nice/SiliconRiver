import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(() => {
  // 从环境变量读取配置，提供合理的默认值
  const apiTarget = process.env.VITE_API_TARGET || "http://localhost:8000";
  const hmrHost = process.env.VITE_HMR_HOST || "localhost";
  const hmrPort = parseInt(process.env.VITE_HMR_PORT || "5173");

  return {
    plugins: [react()],
    server: {
      port: 5173,
      host: "0.0.0.0",  // 允许外部访问
      proxy: {
        // 反向代理所有 /api 请求到后端服务器
        "/api": {
          target: apiTarget,
          changeOrigin: true,
          secure: false,
          rewrite: (path) => path,  // 保持路径不变
        },
        // 健康检查端点也代理
        "/health": {
          target: apiTarget,
          changeOrigin: true,
          secure: false,
        },
      },
      hmr: {
        protocol: "ws",
        host: hmrHost,  // 从环境变量读取
        port: hmrPort,
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
  };
});