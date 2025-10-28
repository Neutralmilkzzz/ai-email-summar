import os
import logging
import json
import time
import asyncio
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# --- 导入服务组件 ---
from aiesvc.config import config_manager, ConfigModel, SecretConfig, mask_secret, LOG_FILE, SUMMARY_DIR
from aiesvc.runner import runner, Runner
from aiesvc.logging_utils import setup_logging, get_sse_log_queue
from aiesvc.storage import storage_manager

# --- 初始化 ---
# 确保日志系统在应用启动前设置
setup_logging(LOG_FILE, logging.INFO)
logger = logging.getLogger("App")

# 确保 data/logs 目录存在
os.makedirs(os.path.dirname(LOG_FILE) or '.', exist_ok=True)
os.makedirs(SUMMARY_DIR, exist_ok=True)

app = FastAPI(
    title="AI Email Summary Web",
    description="将 AI 邮件总结脚本包装为 Web 应用，提供配置、启停和实时日志功能。",
    version="1.0.0"
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# 配置模板引擎
templates = Jinja2Templates(directory="templates")

# 安全认证
security = HTTPBasic()

def get_current_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """
    BasicAuth 依赖函数，用于验证管理员口令。
    """
    load_dotenv() # 确保最新的 .env 被加载
    admin_password = os.getenv("ADMIN_PASSWORD")
    
    if not admin_password:
        logger.error("ADMIN_PASSWORD 未在 .env 中配置，请设置管理口令。")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="管理口令未设置，请配置 .env 文件。"
        )

    if credentials.username != "admin" or credentials.password != admin_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证失败",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# --- 辅助函数 ---

def _get_masked_config_for_api() -> Dict[str, Any]:
    """获取脱敏后的配置，用于前端展示。"""
    cfg = config_manager.get_config_for_api()
    # 敏感信息在 config_manager.get_config_for_api() 中已置空，这里只处理展示
    secrets = config_manager.secrets
    cfg['EMAIL_ACCOUNT'] = secrets.EMAIL_ACCOUNT
    cfg['RECIPIENT_EMAIL'] = secrets.RECIPIENT_EMAIL
    # 敏感字段留空，前端不展示
    cfg['EMAIL_PASSWORD'] = ""
    cfg['DEEPSEEK_API_KEY'] = ""
    cfg['ADMIN_PASSWORD'] = ""
    return cfg

# --- 路由 ---

@app.get("/", response_class=HTMLResponse, tags=["Web"])
async def index(request: Request):
    """
    主页，渲染配置、控制和日志界面。
    """
    current_config = _get_masked_config_for_api()
    return templates.TemplateResponse(
        "index.html", 
        {"request": request, "config": current_config, "status": runner.get_status()}
    )

@app.get("/healthz", tags=["System"])
async def health_check():
    """
    健康检查接口。
    """
    return {"status": "ok", "runner_status": runner.get_status()['status']}

@app.get("/api/config", tags=["Config"])
async def get_config(admin: str = Depends(get_current_admin)):
    """
    获取当前配置（敏感信息脱敏）。
    """
    return _get_masked_config_for_api()

@app.post("/api/config", tags=["Config"])
async def update_config(data: Dict[str, Any], admin: str = Depends(get_current_admin)):
    """
    更新配置（config.json 和 .env）。
    """
    try:
        # 提取 config.json 的字段
        fields = getattr(ConfigModel, "model_fields", getattr(ConfigModel, "__fields__", {}))
        config_data = {k: v for k, v in data.items() if k in fields}
        
        # 提取 .env 的敏感字段
        secret_data = {
            "EMAIL_ACCOUNT": data.get("EMAIL_ACCOUNT", ""),
            "EMAIL_PASSWORD": data.get("EMAIL_PASSWORD", ""),
            "DEEPSEEK_API_KEY": data.get("DEEPSEEK_API_KEY", ""),
            "RECIPIENT_EMAIL": data.get("RECIPIENT_EMAIL", ""),
            "ADMIN_PASSWORD": data.get("ADMIN_PASSWORD", ""),
        }
        
        new_config, new_secrets = config_manager.update_config(config_data, secret_data)
        
        logger.info("配置已更新。")
        return {"message": "配置更新成功", "config": _get_masked_config_for_api()}
        
    except Exception as e:
        logger.error(f"更新配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"配置验证失败: {e}")

@app.post("/api/start", tags=["Control"])
async def start_task(admin: str = Depends(get_current_admin)):
    """
    启动后台任务。
    """
    if runner.get_status()['status'] == Runner.RUNNING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务已在运行中。")
    
    if runner.start():
        logger.info("任务启动成功。")
        return {"message": "任务已启动", "status": runner.get_status()}
    else:
        logger.error("任务启动失败。")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="任务启动失败。")

@app.post("/api/stop", tags=["Control"])
async def stop_task(admin: str = Depends(get_current_admin)):
    """
    停止后台任务。
    """
    if runner.get_status()['status'] != Runner.RUNNING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务未在运行中。")
        
    if runner.stop():
        logger.info("任务停止成功。")
        return {"message": "任务已停止", "status": runner.get_status()}
    else:
        logger.error("任务停止失败。")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="任务停止失败。")

@app.get("/api/status", tags=["Control"])
async def get_status():
    """
    获取当前任务状态和统计信息。
    """
    return runner.get_status()

@app.get("/api/logs/stream", tags=["Logs"])
async def logs_stream(request: Request):
    """
    SSE 实时日志流。
    """
    log_queue = get_sse_log_queue()

    async def event_generator():
        # 发送心跳和初始消息
        yield f"data: {json.dumps({'message': 'SSE Log Stream Connected'})}\n\n"
        
        while True:
            # 检查客户端是否断开连接
            if await request.is_disconnected():
                logger.info("SSE 客户端断开连接。")
                break
                
            try:
                # 从队列中获取日志，非阻塞
                log_line = log_queue.get_nowait()
                # SSE 格式：data: [data]\n\n
                yield f"data: {log_line}\n\n"
                log_queue.task_done()
            except asyncio.QueueEmpty:
                # 队列为空时，发送心跳
                yield ": heartbeat\n\n"
                await asyncio.sleep(1) # 1秒心跳

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/summaries/list", tags=["Download"])
async def list_summaries():
    """
    罗列历史总结文件列表。
    """
    return storage_manager.list_summary_files()

@app.get("/api/summaries/{date_str}", tags=["Download"])
async def download_summary(date_str: str, admin: str = Depends(get_current_admin)):
    """
    下载指定日期的总结文件。
    """
    # 简单校验日期格式 YYYY-MM-DD
    if not (len(date_str) == 10 and date_str[4] == '-' and date_str[7] == '-'):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="日期格式错误，应为 YYYY-MM-DD")
        
    file_path = os.path.join(SUMMARY_DIR, f"{date_str}.txt")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
        
    return FileResponse(
        path=file_path,
        filename=f"{date_str}-summary.txt",
        media_type='text/plain'
    )

# --- 应用生命周期事件 ---
@app.on_event("startup")
async def startup_event():
    # 启动时可以做一些初始化工作，例如检查配置
    logger.info("FastAPI 应用启动。")

@app.on_event("shutdown")
async def shutdown_event():
    # 确保在应用关闭时停止后台任务
    if runner.get_status()['status'] != Runner.IDLE:
        logger.info("应用关闭，尝试停止后台任务...")
        runner.stop()
    logger.info("FastAPI 应用关闭。")

# 启动 runner 线程
# 注意：在生产环境中，通常不会在主进程中启动后台线程，而是使用 Celery/RQ 等任务队列。
# 但根据需求，这里使用线程实现简单的可控启停。
if __name__ == "__main__":
    import uvicorn
    # 确保日志系统已初始化
    setup_logging(LOG_FILE, logging.INFO)
    logger.info("在 __main__ 中启动应用。")
    uvicorn.run(app, host="0.0.0.0", port=8000)
