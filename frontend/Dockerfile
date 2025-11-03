# ===================================================
# Silicon River 前端 Dockerfile
# 适用于在 1Panel 中部署前端到独立服务器
# ===================================================

# ===== 第一阶段：构建前端静态资源 =====

FROM node:20-alpine AS builder

WORKDIR /app

# 复制依赖清单
COPY package.json package-lock.json ./

# 安装依赖（利用 Docker 缓存层）
RUN npm ci --prefer-offline --no-audit

# 复制源代码
COPY . .

# 接收构建参数：后端 API 地址
ARG VITE_API_BASE
ENV VITE_API_BASE=${VITE_API_BASE}

# 构建生产版本
RUN npm run build

# ===== 第二阶段：Nginx 静态文件服务器 =====
FROM nginx:alpine

# 从构建阶段复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制自定义 Nginx 配置（支持 React Router）
COPY --from=builder /app/nginx.conf /etc/nginx/conf.d/default.conf

# 暴露 80 端口
EXPOSE 80

# 启动 Nginx（前台模式）
CMD ["nginx", "-g", "daemon off;"]
