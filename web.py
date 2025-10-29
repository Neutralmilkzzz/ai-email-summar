import os
import logging
import json
import asyncio
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv

# 导入核心服务
from aiesvc.config import config_manager, mask_secret, LOG_FILE, SUMMARY_DIR
from aiesvc.runner import runner
from aiesvc.storage import storage_manager
from aiesvc.notifier import notifier
from aiesvc.logging_utils import setup_logging

# === 初始化 ===
setup_logging(LOG_FILE, logging.INFO)
logger = logging.getLogger("AIEmailWeb")

os.makedirs(os.path.dirname(LOG_FILE) or '.', exist_ok=True)
os.makedirs(SUMMARY_DIR, exist_ok=True)

# FastAPI 应用
app = FastAPI(
    title="AI 邮件总结服务",
    description="通过 Web 界面管理 AI 邮件总结任务（支持配置、日志、邮件发送）。",
    version="2.0.0"
)

import json
from fastapi import Form

CONFIG_FILE = "user_config.json"

@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    """显示配置表单"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user_config = json.load(f)
    else:
        user_config = {}
    return templates.TemplateResponse("config.html", {"request": request, "config": user_config})


@app.post("/config/save")
async def save_config(
    EMAIL_ACCOUNT: str = Form(...),
    EMAIL_PASSWORD: str = Form(...),
    RECIPIENT_EMAIL: str = Form(...),
    SMTP_SERVER: str = Form(...),
    SMTP_PORT: int = Form(...),
    IMAP_SERVER: str = Form(...),
    IMAP_PORT: int = Form(...),
    DEEPSEEK_API_KEY: str = Form(None),
):
    """保存用户配置"""
    user_config = {
        "EMAIL_ACCOUNT": EMAIL_ACCOUNT,
        "EMAIL_PASSWORD": EMAIL_PASSWORD,
        "RECIPIENT_EMAIL": RECIPIENT_EMAIL,
        "SMTP_SERVER": SMTP_SERVER,
        "SMTP_PORT": SMTP_PORT,
        "IMAP_SERVER": IMAP_SERVER,
        "IMAP_PORT": IMAP_PORT,
        "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY,
    }

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(user_config, f, ensure_ascii=False, indent=4)

    return HTMLResponse("<h2>✅ 配置已保存成功！<br>请返回主页并重启服务。</h2>")

# 静态文件 & 模板
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# === BasicAuth ===
security = HTTPBasic()

def get_current_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """
    Basic Auth 管理员认证
    """
    load_dotenv()
    admin_password = os.getenv("ADMIN_PASSWORD")

    if not admin_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="未配置 ADMIN_PASSWORD，请在环境变量中设置。"
        )

    if credentials.username != "admin" or credentials.password != admin_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证失败",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# === 工具函数 ===
def _get_masked_config_for_api() -> Dict[str, Any]:
    """返回脱敏后的配置"""
    cfg = config_manager.get_config_for_api()
    secrets = config_manager.secrets
    cfg.update({
        "EMAIL_ACCOUNT": secrets.EMAIL_ACCOUNT,
        "RECIPIENT_EMAIL": secrets.RECIPIENT_EMAIL,
        "EMAIL_PASSWORD": "",
        "DEEPSEEK_API_KEY": "",
        "ADMIN_PASSWORD": ""
    })
    return cfg


# === 路由定义 ===

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """主页"""
    current_config = _get_masked_config_for_api()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "config": current_config, "status": runner.get_status()}
    )


@app.get("/healthz")
async def health_check():
    """健康检查"""
    return {"status": "ok", "runner_status": runner.get_status()}


@app.get("/api/config")
async def get_config(admin: str = Depends(get_current_admin)):
    """返回配置"""
    return _get_masked_config_for_api()


@app.post("/api/start")
async def start_runner(admin: str = Depends(get_current_admin)):
    """启动任务"""
    if runner.is_running:
        return {"status": "already_running"}

    asyncio.create_task(runner.run_loop())
    return {"status": "started"}


@app.post("/api/stop")
async def stop_runner(admin: str = Depends(get_current_admin)):
    """停止任务"""
    if not runner.is_running:
        return {"status": "not_running"}
    runner.stop()
    return {"status": "stopped"}


@app.post("/api/send_summary")
async def send_summary(admin: str = Depends(get_current_admin)):
    """手动发送每日总结"""
    success = notifier.send_daily_summary()
    return {"status": "success" if success else "failed"}


@app.get("/api/summaries")
async def list_summaries(admin: str = Depends(get_current_admin)):
    """列出所有历史总结文件"""
    return storage_manager.list_summary_files()


@app.get("/api/logs")
async def get_logs(admin: str = Depends(get_current_admin)):
    """读取日志文件"""
    if not os.path.exists(LOG_FILE):
        return {"logs": ""}
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()[-300:]  # 只显示最后300行
    return {"logs": "".join(lines)}


@app.get("/api/about")
async def about():
    """关于信息"""
    return {
        "name": "AI 邮件总结服务",
        "version": "2.0.0",
        "description": "基于 FastAPI + DeepSeek 的智能邮件总结系统。",
    }

