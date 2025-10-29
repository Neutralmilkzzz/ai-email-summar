from fastapi import FastAPI
from aiesvc.notifier import notifier
from aiesvc.storage import storage_manager

app = FastAPI(title="AI 邮件总结服务")

@app.get("/")
def home():
    return {"message": "AI 邮件总结服务已启动 🚀"}

@app.post("/send_summary")
def send_summary():
    ok = notifier.send_daily_summary()
    return {"status": "success" if ok else "failed"}

@app.get("/summaries")
def list_summaries():
    return storage_manager.list_summary_files()
