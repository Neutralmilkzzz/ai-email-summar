import os
import json
import datetime
import logging
from typing import Optional, Dict, Any
from pydantic import BaseModel
from dotenv import load_dotenv

# ==============================
# 路径与常量定义
# ==============================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(file)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SUMMARY_DIR = os.path.join(DATA_DIR, "summaries")
LOG_DIR = os.path.join(DATA_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
USER_CONFIG_FILE = os.path.join(BASE_DIR, "user_config.json")

os.makedirs(SUMMARY_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# ==============================
# 配置模型定义
# ==============================
class ConfigModel(BaseModel):
    SMTP_SERVER: str = "smtp.163.com"
    SMTP_PORT: int = 465
    IMAP_SERVER: str = "imap.163.com"
    IMAP_PORT: int = 993
    AMOUNT_OF_REPORT: int = 10
    ENABLE_SMTP_NOTIFIER: bool = True


class SecretConfig(BaseModel):
    EMAIL_ACCOUNT: Optional[str] = None
    EMAIL_PASSWORD: Optional[str] = None
    RECIPIENT_EMAIL: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    ADMIN_PASSWORD: Optional[str] = None


# ==============================
# 主配置类
# ==============================
class ConfigManager:
    """
    改进版配置管理器：
    优先读取 user_config.json，其次读取 .env
    """

    def init(self):
        self.config = ConfigModel()
        self.secrets = SecretConfig()
        self.reload()

    def reload(self):
        """重新加载配置"""
        load_dotenv(override=True)  # 先加载 .env

        # Step 1: 从 user_config.json 加载（如果存在）
        if os.path.exists(USER_CONFIG_FILE):
            try:
                with open(USER_CONFIG_FILE, "r", encoding="utf-8") as f:
                    user_conf = json.load(f)
                logging.info("✅ 从 user_config.json 加载用户配置")
            except Exception as e:
                logging.warning(f"⚠️ 读取 user_config.json 失败: {e}")
                user_conf = {}
        else:
            user_conf = {}

        # Step 2: 从环境变量或默认值加载
        self.config.SMTP_SERVER = user_conf.get("SMTP_SERVER", os.getenv("SMTP_SERVER", "smtp.163.com"))
        self.config.SMTP_PORT = int(user_conf.get("SMTP_PORT", os.getenv("SMTP_PORT", 465)))
        self.config.IMAP_SERVER = user_conf.get("IMAP_SERVER", os.getenv("IMAP_SERVER", "imap.163.com"))
        self.config.IMAP_PORT = int(user_conf.get("IMAP_PORT", os.getenv("IMAP_PORT", 993)))
        self.config.AMOUNT_OF_REPORT = int(user_conf.get("AMOUNT_OF_REPORT", 10))
        self.config.ENABLE_SMTP_NOTIFIER = True

        self.secrets.EMAIL_ACCOUNT = user_conf.get("EMAIL_ACCOUNT", os.getenv("EMAIL_ACCOUNT"))
        self.secrets.EMAIL_PASSWORD = user_conf.get("EMAIL_PASSWORD", os.getenv("EMAIL_PASSWORD"))
        self.secrets.RECIPIENT_EMAIL = user_conf.get("RECIPIENT_EMAIL", os.getenv("RECIPIENT_EMAIL"))
        self.secrets.DEEPSEEK_API_KEY = user_conf.get("DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY"))
        self.secrets.ADMIN_PASSWORD = user_conf.get("ADMIN_PASSWORD", os.getenv("ADMIN_PASSWORD"))

        logging.info("✅ 配置加载完成")

    def save_user_config(self, config_dict: Dict[str, Any]):
        """保存用户配置到 user_config.json + .env"""
        try:
            # 写入 JSON 文件
            with open(USER_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_dict, f, ensure_ascii=False, indent=4)

            # 同步写入 .env
            with open(".env", "w", encoding="utf-8") as f:
                for k, v in config_dict.items():
                    if v is not None:
                        f.write(f"{k}={v}\n")

            logging.info("💾 用户配置已保存")
            self.reload()

        except Exception as e:
            logging.error(f"❌ 保存用户配置失败: {e}", exc_info=True)
    def get_config_for_api(self) -> Dict[str, Any]:
        """返回脱敏后的配置供前端显示"""
        api_config = self.config.dict()
        api_config.update({
            "EMAIL_ACCOUNT": self.secrets.EMAIL_ACCOUNT,
            "RECIPIENT_EMAIL": self.secrets.RECIPIENT_EMAIL,
            "EMAIL_PASSWORD": "",
            "DEEPSEEK_API_KEY": "",
            "ADMIN_PASSWORD": "",
        })
        return api_config


# ==============================
# 工具函数
# ==============================
def mask_secret(secret: Optional[str]) -> str:
    """将敏感字符串脱敏，只显示前4后4位"""
    if not secret:
        return ""
    secret = str(secret).strip()
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"


# ==============================
# 全局实例
# ==============================
config_manager = ConfigManager()