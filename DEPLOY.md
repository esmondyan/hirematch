# HireMatch 云服务器部署指南

## 前置条件

- 一台云服务器（阿里云 ECS / 腾讯云轻量 / 任何 VPS）
- 操作系统：Ubuntu 22.04+ 或 Debian 12+
- 最低配置：1 核 CPU、1 GB 内存、20 GB 磁盘
- 已安装 Docker 和 Docker Compose

## 方案概述

```
用户浏览器 → Nginx (80/443) → FastAPI (8000) → SQLite
                                  ↓
                           DeepSeek API (LLM)
```

Nginx 负责静态文件服务和反向代理，FastAPI 处理业务逻辑，SQLite 存储数据。

## 第一步：服务器初始化

```bash
# 连接服务器
ssh root@<服务器IP>

# 安装 Docker（如未安装）
curl -fsSL https://get.docker.com | bash

# 启动 Docker
systemctl enable docker && systemctl start docker

# 创建应用目录
mkdir -p /opt/hirematch && cd /opt/hirematch
```

## 第二步：上传项目文件

```bash
# 在本地打包项目（排除 .venv 和大文件）
cd /path/to/hirematch
tar --exclude='.venv' --exclude='uploads/*' --exclude='__pycache__' \
    -czf hirematch.tar.gz .

# 上传到服务器
scp hirematch.tar.gz root@<服务器IP>:/opt/hirematch/

# 在服务器解压
cd /opt/hirematch && tar -xzf hirematch.tar.gz
```

## 第三步：配置环境变量

```bash
# 编辑 .env 文件，填入真实 API Key
nano .env
```

```ini
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
MATCH_THRESHOLD=60
MAX_UPLOAD_SIZE_MB=5
DATABASE_URL=sqlite:///./hirematch.db
```

## 第四步：启动服务

```bash
# 使用生产配置启动（含 Nginx 反向代理）
docker compose -f docker-compose.prod.yml up -d

# 查看日志确认启动成功
docker compose -f docker-compose.prod.yml logs -f

# 检查服务状态
docker compose -f docker-compose.prod.yml ps
```

访问 `http://<服务器IP>` 即可使用。

## 第五步（可选）：配置域名和 HTTPS

```bash
# 安装 certbot
apt install -y certbot

# 获取证书
certbot certonly --standalone -d your-domain.com

# 编辑 nginx.conf，取消注释 HTTPS 部分，替换域名
# 编辑 docker-compose.prod.yml，取消 443 端口注释
sed -i 's/# - "443:443"/- "443:443"/' docker-compose.prod.yml
sed -i 's/# - \/etc\/letsencrypt/  - \/etc\/letsencrypt/' docker-compose.prod.yml

# 重启 nginx
docker compose -f docker-compose.prod.yml restart nginx
```

## 日常维护

### 更新代码
```bash
cd /opt/hirematch
# 拉取新代码或重新上传
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d --build
```

### 备份数据
```bash
# 备份数据库和上传文件
tar -czf backup-$(date +%Y%m%d).tar.gz hirematch.db uploads/
```

### 查看日志
```bash
docker compose -f docker-compose.prod.yml logs --tail=100 hirematch
```

### 重启服务
```bash
docker compose -f docker-compose.prod.yml restart
```

## 成本估算

| 服务商 | 最低配置 | 月费用（参考） |
|--------|----------|---------------|
| 阿里云 ECS | 1c1g 20G | ~¥34/月 |
| 腾讯云轻量 | 1c1g 25G | ~¥28/月 |
| 华为云 HECS | 1c1g 20G | ~¥30/月 |

> 新用户通常有首单优惠，年均 ¥200-400 可覆盖。

## 安全建议

1. 配置云服务器安全组：仅开放 80、443、22 端口
2. 定期更新系统：`apt update && apt upgrade -y`
3. 启用 HTTPS（Let's Encrypt 免费证书）
4. 使用强密码的 API Key
5. 定期备份数据库文件
