#!/bin/bash

# Silicon River 前端 502 错误修复脚本
# 使用说明：在服务器上运行 bash fix-502.sh

set -e

echo "================================================"
echo "  Silicon River 前端 502 错误完全修复脚本"
echo "================================================"

PROJECT_DIR="/opt/SiliconRiver"
COMPOSE_FILE="docker-compose.frontend-only.yml"

# 检查项目目录是否存在
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ 错误：项目目录 $PROJECT_DIR 不存在"
    exit 1
fi

cd "$PROJECT_DIR"

echo -e "\n[步骤 1/6] 停止并删除旧容器"
echo "=========================================="
docker-compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true
sleep 2
echo "✅ 完成"

echo -e "\n[步骤 2/6] 删除旧镜像（强制重建）"
echo "=========================================="
CONTAINER_NAME="silicon-river-frontend"
IMAGE_ID=$(docker images | grep "$CONTAINER_NAME\|silicon.river.frontend" | awk '{print $3}' | head -1)
if [ ! -z "$IMAGE_ID" ]; then
    docker rmi -f "$IMAGE_ID" 2>/dev/null || true
    echo "✅ 删除了旧镜像"
else
    echo "ℹ️  没有找到旧镜像"
fi

sleep 2

echo -e "\n[步骤 3/6] 验证配置文件"
echo "=========================================="

# 检查必要文件
if [ ! -f "frontend/Dockerfile" ]; then
    echo "❌ 错误：frontend/Dockerfile 不存在"
    exit 1
fi
echo "✅ frontend/Dockerfile 存在"

if [ ! -f "frontend/nginx.conf" ]; then
    echo "❌ 错误：frontend/nginx.conf 不存在"
    exit 1
fi
echo "✅ frontend/nginx.conf 存在"

if [ ! -f "frontend/package.json" ]; then
    echo "❌ 错误：frontend/package.json 不存在"
    exit 1
fi
echo "✅ frontend/package.json 存在"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "❌ 错误：$COMPOSE_FILE 不存在"
    exit 1
fi
echo "✅ $COMPOSE_FILE 存在"

echo -e "\n[步骤 4/6] 构建 Docker 镜像"
echo "=========================================="
echo "这可能需要 3-5 分钟，请耐心等待..."

if docker-compose -f "$COMPOSE_FILE" build --no-cache 2>&1 | tee build.log; then
    echo "✅ 镜像构建成功"
else
    echo "❌ 镜像构建失败！"
    echo "请查看上面的错误信息，通常是："
    echo "  1. npm install 失败（检查网络和依赖）"
    echo "  2. npm run build 失败（检查代码编译错误）"
    echo "  3. nginx.conf 语法错误"
    exit 1
fi

echo -e "\n[步骤 5/6] 启动容器"
echo "=========================================="
docker-compose -f "$COMPOSE_FILE" up -d

echo "✅ 容器已启动"
echo "等待 10 秒让容器完全启动..."
sleep 10

echo -e "\n[步骤 6/6] 验证部署"
echo "=========================================="

# 检查容器状态
CONTAINER_STATUS=$(docker-compose -f "$COMPOSE_FILE" ps --services 2>/dev/null | wc -l)
if [ "$CONTAINER_STATUS" -gt 0 ]; then
    echo "✅ 容器运行正常"
else
    echo "❌ 容器未运行"
    docker-compose -f "$COMPOSE_FILE" logs
    exit 1
fi

# 检查 dist 文件
DIST_FILES=$(docker exec silicon-river-frontend ls /usr/share/nginx/html/ 2>/dev/null | wc -l)
if [ "$DIST_FILES" -gt 1 ]; then
    echo "✅ 前端文件存在（$DIST_FILES 个）"
else
    echo "⚠️  警告：前端文件可能缺失"
    docker exec silicon-river-frontend ls -la /usr/share/nginx/html/
fi

# 检查 Nginx 进程
if docker exec silicon-river-frontend ps aux | grep -v grep | grep nginx > /dev/null; then
    echo "✅ Nginx 进程正常运行"
else
    echo "❌ Nginx 进程未运行"
    exit 1
fi

# 检查 Nginx 配置
if docker exec silicon-river-frontend nginx -t 2>&1 | grep -i "successful\|ok" > /dev/null; then
    echo "✅ Nginx 配置正确"
else
    echo "❌ Nginx 配置有错误"
    docker exec silicon-river-frontend nginx -t
    exit 1
fi

# 本地连接测试
echo -e "\n测试本地连接..."
if docker exec silicon-river-frontend curl -s http://localhost/ > /dev/null 2>&1; then
    echo "✅ 本地连接正常"
else
    echo "⚠️  本地连接测试失败，但容器可能仍在启动中"
fi

echo -e "\n================================================"
echo "  ✅ 修复完成！"
echo "================================================"

echo -e "\n现在测试访问："
echo "在浏览器中访问：http://$(hostname -I | awk '{print $1}'):8080"
echo ""
echo "如果还是 502 错误，请执行："
echo "  docker logs silicon-river-frontend"
echo ""
echo "并分享日志内容。"

exit 0
