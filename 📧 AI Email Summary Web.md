# 📧 AI Email Summary Web

本项目是将一个 AI 邮件总结脚本包装成一个功能完整的 Web 应用。用户可以通过网页界面配置邮箱和 AI 密钥、控制后台任务的启停、实时查看运行日志，并下载每日总结文件。

## ✨ 特性

*   **配置管理**: 通过 `config.json` 和 `.env` 分离可见配置和敏感密钥，支持网页端配置。
*   **可控启停**: 后台任务使用线程实现优雅的启动和停止。
*   **实时日志**: 基于 Server-Sent Events (SSE) 实现实时、结构化的日志推送。
*   **幂等处理**: 使用 SQLite 数据库记录已处理邮件的 UID，确保同一封邮件不重复总结。
*   **邮件增强**: 支持 `text/plain` 和 `text/html` 邮件解析，并实现 Token 感知的智能截断。
*   **安全**: 敏感信息（密钥、授权码）在日志和前端界面中脱敏处理，核心操作需通过 BasicAuth 认证。
*   **部署友好**: 提供 `requirements.txt`、`Dockerfile`、`docker-compose.yml` 和 `systemd` 示例。

## 🚀 快速开始

### 1. 克隆项目

```bash
git clone <repository_url>
cd email-summary-web
```

### 2. 配置环境

#### 2.1. 敏感配置 (`.env`)

编辑根目录下的 `.env` 文件，填入您的敏感信息。

```
# AI Email Summary Web 敏感配置
# 请替换以下占位符为您的实际值

EMAIL_ACCOUNT="your_email@example.com"
EMAIL_PASSWORD="your_email_auth_code" # 邮箱授权码
DEEPSEEK_API_KEY="your_deepseek_api_key"
RECIPIENT_EMAIL="your_recipient@example.com" # SMTP 通知收件人
ADMIN_PASSWORD="your_admin_password" # 网站管理口令
```

#### 2.2. 可见配置 (`config.json`)

`config.json` 包含非敏感的配置项，如 IMAP/SMTP 服务器地址、端口、轮询间隔等。您也可以在网站启动后通过前端界面修改。

### 3. 本地运行 (推荐)

```bash
# 1. 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动应用
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

应用将在 `http://127.0.0.1:8000` 运行。首次访问时，需要输入 `.env` 中设置的 `ADMIN_PASSWORD` 作为管理口令。

### 4. Docker 部署 (生产环境)

```bash
# 1. 构建镜像
docker build -t ai-email-summary-web .

# 2. 运行容器
docker-compose up -d
```

容器将暴露 `8000` 端口。`data/` 和 `logs/` 目录将被挂载，以保证数据和日志的持久化。

## 📁 项目结构

```
email_summary_web/
├── app.py                         # FastAPI 入口
├── aiesvc/                        # 服务模块
│   ├── config.py                  # 配置读取/校验/脱敏
│   ├── mailbox.py                 # IMAP 客户端
│   ├── parser.py                  # 邮件解析与智能截断
│   ├── summarizer.py              # DeepSeek API Provider
│   ├── storage.py                 # 总结文件与 SQLite 幂等处理
│   ├── notifier.py                # SMTP 通知
│   ├── runner.py                  # 后台任务状态机与主循环
│   └── logging_utils.py           # 结构化日志、SSE 适配
├── static/
│   ├── style.css                  # UI 样式
│   └── script.js                  # 前端逻辑
├── templates/
│   ├── index.html                 # 主页面
│   └── login.html                 # 基础认证登录页
├── data/                          # 运行时数据 (自动创建)
│   ├── summaries/                 # 总结文件
│   └── db.sqlite3                 # SQLite 数据库
├── logs/                          # 运行时日志 (自动创建)
├── AiEmailSummary.py              # 改造后的核心执行脚本
├── config.json                    # 可见配置
├── .env                           # 敏感配置
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── run_gunicorn.sh                # Gunicorn 启动脚本
├── email-summary-web.service      # systemd 单元示例
└── README.md                      # 本文件
```
