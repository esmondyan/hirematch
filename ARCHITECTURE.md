# HireMatch 系统架构文档

## 概述

HireMatch 是一款智能面试助手，帮助技术团队高效筛选候选人简历、分析匹配度、生成个性化面试题、评估面试表现，并输出结构化招聘建议。

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| Web 框架 | FastAPI 0.136+ | 异步 Web 框架，提供 REST API |
| 模板引擎 | Jinja2 3.1+ | 服务端渲染 HTML 页面 |
| 数据库 | SQLite + SQLAlchemy 2.0 | 轻量级关系数据库，JSON 列存储复杂结构 |
| LLM 接口 | OpenAI SDK / DashScope | 统一抽象，支持 DeepSeek / Qwen / OpenAI |
| PDF 解析 | PyMuPDF (fitz) 1.27+ | 文本提取 + Tesseract OCR 回退 |
| Word 解析 | python-docx | .docx 文件文本提取 |
| 容器化 | Docker + Docker Compose | 一键部署 |

## 项目目录结构

```
hirematch/
├── app/
│   ├── main.py                  # FastAPI 应用入口，路由注册，模板配置
│   ├── config.py                # 配置管理（环境变量映射）
│   ├── models/
│   │   ├── database.py          # SQLAlchemy ORM（Job / Candidate 模型）
│   │   └── schemas.py           # Pydantic 请求/响应模型
│   ├── routers/
│   │   ├── jobs.py              # 职位管理路由
│   │   └── candidates.py        # 候选人管理路由（核心）
│   ├── services/
│   │   ├── llm_service.py       # LLM 抽象层（DeepSeek/Qwen/OpenAI）
│   │   ├── resume_parser.py     # 简历解析（PDF/Word → 文本）
│   │   ├── resume_cleaner.py    # 文本清洗 + LLM 结构重组
│   │   ├── matcher.py           # 候选人与 JD 匹配分析
│   │   ├── credibility.py       # 简历可信度分析
│   │   ├── interviewer.py       # 面试题生成 + 换题
│   │   ├── summarizer.py        # 面试总结生成
│   │   └── comparator.py        # 多候选人对比排序
│   └── templates/
│       ├── base.html            # 基础布局模板
│       ├── index.html           # 首页（上传简历 + 历史记录）
│       ├── results.html         # 结果列表（通过/拒绝/处理中）
│       ├── detail.html          # 候选人详情 + 面试管理
│       └── compare.html         # 候选人对比页
├── static/
│   ├── css/style.css            # 全局样式
│   └── js/app.js                # 全局脚本
├── uploads/                     # 上传文件存储
├── Dockerfile                   # Docker 构建文件
├── docker-compose.yml           # Docker 编排
├── .env                         # 环境变量配置
├── requirements.txt             # Python 依赖
└── hirematch.db                 # SQLite 数据库文件
```

## 数据模型

### Job（职位）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| title | VARCHAR(200) | 职位名称 |
| description | TEXT | 职位描述（JD） |
| threshold | INTEGER | 匹配阈值（0-100，默认 60） |
| comparison_result | TEXT(JSON) | 多候选人对比结果 |
| created_at | DATETIME | 创建时间 |

### Candidate（候选人）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| job_id | FK → jobs.id | 关联职位 |
| name | VARCHAR(100) | 候选人姓名（自动提取） |
| filename | VARCHAR(500) | 原始文件名 |
| resume_text | TEXT | 解析后的简历文本 |
| resume_file_path | VARCHAR(500) | 原始文件磁盘路径 |
| overall_score | INTEGER | 综合匹配分（0-100） |
| passed | BOOLEAN | 是否通过初筛 |
| match_result | TEXT(JSON) | 匹配分析详情 |
| credibility_result | TEXT(JSON) | 可信度分析详情 |
| interview_result | TEXT(JSON) | 面试题和评估数据 |
| answers | TEXT(JSON) | 面试官点评 + 逐点评分 |
| final_summary | TEXT(JSON) | 最终面试总结 |
| status | VARCHAR(20) | pending/processing/completed/failed |
| marked_for_interview | BOOLEAN | 是否标记为待面试 |
| error_message | TEXT | 处理失败时的错误信息 |

> JSON 列通过 Python property 自动序列化/反序列化，业务代码直接操作 dict。

## 核心业务流程

### 1. 简历上传与解析
```
用户上传文件 → resume_parser.py → 判断 PDF/Word
  ├── PDF: PyMuPDF 提取文本
  │   └── 文本 < 50 字符 → Tesseract OCR 回退
  └── Word: python-docx 提取文本
→ resume_cleaner.py → 清洗噪声/水印 → LLM 结构重组
→ 提取姓名 → 存储 candidates 表
```

### 2. 匹配分析（后台异步）
```
_process_candidates():
  1. clean_resume_text()       # 文本清洗
  2. restructure_resume_markdown() # LLM 重组简历结构
  3. analyze_credibility()     # 可信度分析
  4. match_candidate()         # JD 匹配打分
  → 更新 candidate 状态为 completed
```

### 3. 面试题生成（两阶段）
```
阶段 1: POST /candidates/{id}/generate-focus
  → LLM 基于 JD + 简历 + 匹配缺口 + 可信度预警
  → 生成 3-6 条面试重点方向
  → 返回 State B（面试重点编辑页）

阶段 2: POST /candidates/{id}/generate-questions
  → LLM 基于确认后的面试重点
  → 生成 4-5 道具体问题（技术/行为/缺口探查）
  → 每题为面试官提供预期回答点和评分维度
  → 严格控制在 22 分钟以内
  → 返回 State C（面试题 + 评分页）
```

### 4. 面试评估
```
面试官逐点评分（1-5级）+ 可选文字点评
→ 客户端 evalCache 缓存
→ POST /candidates/{id}/evaluations 自动保存
→ POST /candidates/{id}/final-summary
→ LLM 综合分析 → 输出两种格式报告
```

### 5. 最终总结输出
```
格式一：面试官印象
  - 8 维度评分（1-5分）：基本知识、专业知识、实际经验、特性、
    态度、工作经历、发展潜力、判断决策能力
  - 总体评定：很好/很合格/合格/仅合格/不令人满意
  - 综合评语

格式二：综合评估
  - 基本信息：学历、性别、年龄、学校、工作经验
  - 工作技术：开发能力、沟通能力、其他
  - 招聘意见
```

## API 路由表

### 职位管理 (`/jobs`)
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /jobs/create | 创建职位JD |
| POST | /jobs/{id}/delete | 删除职位 |
| POST | /jobs/{id}/update | 更新职位信息 |
| POST | /jobs/{id}/set-threshold | 设置匹配阈值 |
| POST | /jobs/{id}/reanalyze-all | 重新分析所有候选人 |

### 候选人管理 (`/candidates`)
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /candidates/upload | 上传简历 |
| GET | /candidates/{id} | 获取候选人详情 |
| GET | /candidates/{id}/download | 下载原始简历 |
| POST | /candidates/{id}/answers | 保存面试官点评 |
| POST | /candidates/{id}/evaluations | 保存逐点评分 |
| POST | /candidates/{id}/voice/{qkey} | 上传录音（预留） |
| POST | /candidates/{id}/replace-question | 换一道题 |
| POST | /candidates/{id}/generate-focus | 生成面试重点 |
| POST | /candidates/{id}/generate-questions | 生成面试题 |
| POST | /candidates/{id}/mark-for-interview | 切换面试标记 |
| POST | /candidates/{id}/final-summary | 生成面试总结 |
| POST | /candidates/{id}/reanalyze | 重新分析单个简历 |
| POST | /candidates/{id}/reject | 将已通过候选人改为拒绝 |
| DELETE | /candidates/{id} | 删除候选人 |
| POST | /candidates/update-name/{id} | 编辑候选人姓名 |
| POST | /candidates/batch-mark | 批量标记面试 |
| POST | /candidates/batch-generate-questions | 批量生成面试题 |
| POST | /candidates/compare | 多候选人对比 |

## 前端页面状态机

```
State A（无面试数据）
  └─ if candidate.passed → 显示"生成面试问题"按钮

State B（面试重点编辑）
  └─ if interview_result.question_count == 0
     → 显示面试重点列表 + "确认出题"和"重定重点"按钮
     → 支持添加/编辑/删除重点条目

State C（面试题已生成）
  └─ if interview_result.question_count > 0
     → 显示完整面试题卡片 + 逐点评分区域
     → "重新出题"和"重定重点"按钮
     → 面试总结卡片（评分后可用）

Processing（处理中）
  └─ status == "processing" → 显示加载动画，自动轮询刷新
```

## LLM 服务抽象

```python
BaseLLMService (ABC)
  ├── DeepSeekService    # 默认，使用 OpenAI 兼容接口
  ├── QwenService        # DashScope API
  └── OpenAIService      # GPT-4o
```

- 统一 `chat()` 和 `chat_json()` 接口
- 温度控制：确定性场景 0.1，生成多样性场景 0.7
- 高温度时自动启用 presence_penalty / frequency_penalty
- JSON 自动提取（支持 markdown 代码块、裸 JSON）

## 关键设计决策

1. **SQLite 单文件数据库**：适合单机部署，无需额外数据库服务。JSON 列存储复杂结构避免过度关联。
2. **服务端渲染 (SSR)**：Jinja2 模板直出 HTML，无需前端构建工具，首屏加载快。
3. **后台线程异步处理**：简历分析在 ThreadPoolExecutor 中执行，不阻塞 API 响应。
4. **LLM 抽象层**：Provider 可切换，支持多个主流 LLM API。
5. **面试两阶段生成**：先定重点方向，确认后再出题，给面试官留有调整空间。
6. **客户端评分缓存**：evalCache 在前端暂存评分，自动同步后端，减少请求。

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| LLM_PROVIDER | LLM 提供商 (deepseek/qwen/openai) | deepseek |
| DEEPSEEK_API_KEY | DeepSeek API 密钥 | - |
| DEEPSEEK_BASE_URL | DeepSeek API 地址 | https://api.deepseek.com |
| DASHSCOPE_API_KEY | 阿里云 DashScope 密钥 | - |
| OPENAI_API_KEY | OpenAI API 密钥 | - |
| MATCH_THRESHOLD | 匹配阈值 (0-100) | 60 |
| MAX_UPLOAD_SIZE_MB | 上传文件大小限制 (MB) | 5 |
| DATABASE_URL | 数据库连接串 | sqlite:///./hirematch.db |
