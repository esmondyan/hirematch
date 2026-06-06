# HireMatch 云服务器部署指南

## 前置条件

- 一台云服务器（阿里云 ECS / 腾讯云轻量 / 任何 VPS）
- 操作系统：Ubuntu 22.04+ 或 Debian 12+
- 最低配置：1 核 CPU、1 GB 内存、20 GB 磁盘

## 架构概述

```
用户浏览器 → Nginx (:80) → FastAPI (:53500) → SQLite
                                ↓
                         DeepSeek API (LLM)
```

Nginx 负责静态文件服务和反向代理，FastAPI 处理业务逻辑，SQLite 存储数据。全部容器化，一个 `docker compose` 命令启动。

---

## 快速部署（推荐：GitHub 方式）

项目已托管在 GitHub，通过 `git clone` 拉取代码，后续更新只需 `git pull`。

### 第一步：服务器初始化

```bash
ssh root@<服务器IP>

# 安装 Docker（已安装则跳过）
curl -fsSL https://get.docker.com | bash
systemctl enable docker && systemctl start docker
```

### 第二步：克隆项目

```bash
cd /opt
git clone https://github.com/esmondyan/hirematch.git
cd hirematch
```

### 第三步：配置并启动

```bash
# 创建 .env 配置文件
cp .env.example .env
nano .env   # 填入真实 API Key（必填项见下方）
```

.env 最小配置：

```ini
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxx
DATABASE_URL=sqlite:///./data/hirematch.db
SESSION_SECRET_KEY=<生成随机字符串>
```

```bash
# 启动服务
docker compose -f docker-compose.prod.yml up -d

# 确认运行状态
docker compose -f docker-compose.prod.yml ps
```

访问 `http://<服务器IP>` 即可使用。

### 后续更新

```bash
cd /opt/hirematch
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

---

## 备选部署（直接上传，无需 GitHub）

如果服务器无法访问 GitHub，可直接上传项目文件：

```bash
# 在本地打包
tar --exclude='.venv' --exclude='.git' --exclude='uploads/*' --exclude='__pycache__' \
    -czf hirematch.tar.gz .

# 上传到服务器
scp hirematch.tar.gz root@<服务器IP>:/opt/hirematch/

# 在服务器解压并启动
cd /opt/hirematch && tar -xzf hirematch.tar.gz
cp .env.example .env && nano .env
docker compose -f docker-compose.prod.yml up -d
```

也可以使用项目自带的部署脚本：

```bash
bash deploy.sh <服务器IP> root
```

---

## 云服务商安全组配置

部署后需要在云控制台开放端口，否则外网无法访问。

### 阿里云 ECS

1. 控制台 → 实例 → 安全组 → 配置规则
2. 入方向添加：

| 端口 | 协议 | 来源 | 说明 |
|------|------|------|------|
| 80 | TCP | 0.0.0.0/0 | HTTP 访问 |
| 443 | TCP | 0.0.0.0/0 | HTTPS（可选） |
| 22 | TCP | 0.0.0.0/0 | SSH 管理 |

### 腾讯云轻量

1. 控制台 → 轻量应用服务器 → 防火墙
2. 添加规则：TCP 80、TCP 443

### 华为云 HECS

1. 控制台 → 安全组 → 配置规则
2. 入方向添加：TCP 80、TCP 443、TCP 22

> **重要**：不要开放 53500 端口。Nginx 在 80 端口对外服务，应用运行在内网。

---

## 配置 HTTPS（可选但推荐）

使用 Let's Encrypt 免费证书：

```bash
# 安装 certbot
apt install -y certbot

# 先停掉 nginx 释放 80 端口
docker compose -f docker-compose.prod.yml stop nginx

# 获取证书（替换为你的域名）
certbot certonly --standalone -d your-domain.com

# 编辑 nginx.conf，取消注释 HTTPS server 块，替换域名为 your-domain.com
# 编辑 docker-compose.prod.yml，取消注释 443 端口和证书挂载

# 重启
docker compose -f docker-compose.prod.yml up -d
```

---

## 完整 .env 配置参考

```ini
LLM_PROVIDER=deepseek                        # deepseek | qwen | openai
DEEPSEEK_API_KEY=sk-your-key-here           # 必填
DEEPSEEK_BASE_URL=https://api.deepseek.com
DASHSCOPE_API_KEY=                          # 使用 Qwen 时填写
OPENAI_API_KEY=                             # 使用 OpenAI 时填写
MATCH_THRESHOLD=60                          # 匹配阈值，低于此分自动拒绝
MAX_UPLOAD_SIZE_MB=5                        # 上传文件大小限制
DATABASE_URL=sqlite:///./data/hirematch.db   # 数据库路径，默认即可
SESSION_SECRET_KEY=随机字符串                 # Session 加密密钥，生产环境必须修改
```

---

## 日常维护

### 查看日志
```bash
docker compose -f docker-compose.prod.yml logs --tail=100 hirematch
docker compose -f docker-compose.prod.yml logs -f   # 实时跟踪
```

### 重启服务
```bash
docker compose -f docker-compose.prod.yml restart
```

### 停止服务
```bash
docker compose -f docker-compose.prod.yml down
```

### 备份数据
```bash
# 数据库和上传文件都在 /opt/hirematch 目录下
tar -czf backup-$(date +%Y%m%d-%H%M).tar.gz data/ uploads/
```

### 恢复数据
```bash
tar -xzf backup-20260606-1200.tar.gz
docker compose -f docker-compose.prod.yml restart
```

---

## 成本估算

| 服务商 | 最低配置 | 月费用 | 新用户优惠 |
|--------|----------|--------|-----------|
| 阿里云 ECS | 1c1g 20G | ~¥34/月 | 新客首年 ¥99 |
| 腾讯云轻量 | 1c1g 25G | ~¥28/月 | 新客 3 年 ¥198 |
| 华为云 HECS | 1c1g 20G | ~¥30/月 | 新客首单优惠 |

> DeepSeek API 费用另计，约 ¥1-2/百万 token，单个候选人分析约消耗 5000-10000 token。

---

## 安全建议

1. **安全组**：仅开放 80、443、22 端口，不暴露 53500
2. **API Key**：使用独立的 API Key，不要与其他项目共用
3. **HTTPS**：生产环境务必启用，Let's Encrypt 免费且自动续期
4. **系统更新**：`apt update && apt upgrade -y` 定期执行
5. **备份**：设置 cron 定期备份数据库
   ```
   0 3 * * * cd /opt/hirematch && tar -czf backup-$(date +\%Y\%m\%d).tar.gz data/ uploads/
   ```
