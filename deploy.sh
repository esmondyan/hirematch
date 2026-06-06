#!/bin/bash
# HireMatch 一键部署脚本
# Usage: bash deploy.sh [server_ip] [user]
# Example: bash deploy.sh 123.45.67.89 root

set -e

SERVER_IP="${1:-}"
SERVER_USER="${2:-root}"
APP_DIR="/opt/hirematch"

if [ -z "$SERVER_IP" ]; then
    echo "用法: bash deploy.sh <服务器IP> [用户名]"
    echo "示例: bash deploy.sh 123.45.67.89 root"
    exit 1
fi

echo "========================================="
echo "  HireMatch 部署脚本"
echo "  目标服务器: ${SERVER_USER}@${SERVER_IP}"
echo "========================================="

# Step 1: Check .env file
if [ ! -f ".env" ]; then
    echo "[错误] 未找到 .env 文件，请先创建并配置 API Key"
    echo "参考 .env.example 创建: cp .env.example .env"
    exit 1
fi

echo "[1/5] 打包项目文件..."
tar --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='uploads/*' \
    --exclude='hirematch.db' \
    --exclude='*.tar.gz' \
    -czf hirematch-deploy.tar.gz \
    app/ static/ Dockerfile docker-compose.yml docker-compose.prod.yml \
    nginx.conf requirements.txt .env .dockerignore

echo "[2/5] 上传到服务器..."
ssh ${SERVER_USER}@${SERVER_IP} "mkdir -p ${APP_DIR}"
scp hirematch-deploy.tar.gz ${SERVER_USER}@${SERVER_IP}:${APP_DIR}/

echo "[3/5] 解压并准备..."
ssh ${SERVER_USER}@${SERVER_IP} "cd ${APP_DIR} && tar -xzf hirematch-deploy.tar.gz && rm hirematch-deploy.tar.gz"

echo "[4/5] 启动 Docker 服务..."
ssh ${SERVER_USER}@${SERVER_IP} "cd ${APP_DIR} && docker compose -f docker-compose.prod.yml up -d --build"

echo "[5/5] 等待服务就绪..."
sleep 5
ssh ${SERVER_USER}@${SERVER_IP} "docker compose -f ${APP_DIR}/docker-compose.prod.yml ps"

echo ""
echo "========================================="
echo "  部署完成！"
echo "  访问地址: http://${SERVER_IP}"
echo "========================================="

# Cleanup local tar
rm -f hirematch-deploy.tar.gz
