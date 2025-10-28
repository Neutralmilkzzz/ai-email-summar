import os
import json
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError
from dotenv import load_dotenv, set_key

# 加载 .env 文件
load_dotenv()

# --- 文件路径常量 ---
CONFIG_FILE = "config.json"
ENV_FILE = ".env"
SUMMARY_DIR = "data/summaries"
SQLITE_DB_PATH = "data/db.sqlite3"
LOG_FILE = "logs/runtime.log"

# --- 配置模型 (config.json) ---
class ConfigModel(BaseModel):
    """
    config.json 中存储的非敏感配置项模型。
    """
    TIME_GAP: int = Field(default=10, description="轮询间隔秒数")
    AMOUNT_OF_REPORT: int = Field(default=5, description="汇总包含的最近邮件条数")
    IMAP_SERVER: str = Field(default="imap.example.com", description="IMAP 服务器地址")
    IMAP_PORT: int = Field(default=993, description="IMAP 服务器端口")
    SMTP_SERVER: str = Field(default="smtp.example.com", description="SMTP 服务器地址")
    SMTP_PORT: int = Field(default=465, description="SMTP 服务器端口")
    DEEPSEEK_API_URL: str = Field(default="https://api.deepseek.com/v1/chat/completions", description="DeepSeek API URL")
    DEEPSEEK_MODEL: str = Field(default="deepseek-chat", description="DeepSeek 模型名称")
    ENABLE_SMTP_NOTIFIER: bool = Field(default=False, description="是否启用 SMTP 邮件通知")
    # ---- 关键新增 ----
    @classmethod
    def get_fields(cls):
        """
        自动兼容 Pydantic v1 / v2 的字段定义访问方式。
        """
        return getattr(cls, "model_fields", getattr(cls, "__fields__", {}))
    
    # 确保 TIME_GAP 是正数
    @classmethod
    def validate_time_gap(cls, value):
        if value <= 0:
            raise ValueError("TIME_GAP 必须大于 0")
        return value

# --- 敏感配置 (环境变量) ---
class SecretConfig:
    """
    从 .env 文件（环境变量）中读取的敏感配置项。
    """
    EMAIL_ACCOUNT: str = os.getenv("EMAIL_ACCOUNT", "")
    EMAIL_PASSWORD: str = os.getenv("EMAIL_PASSWORD", "")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    RECIPIENT_EMAIL: str = os.getenv("RECIPIENT_EMAIL", "")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")

# --- 配置管理类 ---
class ConfigManager:
    """
    负责加载、保存和管理应用配置。
    """
    def __init__(self):
        self.config: ConfigModel = self._load_config_file()
        self.secrets: SecretConfig = SecretConfig()

    def _load_config_file(self) -> ConfigModel:
        """从 config.json 加载配置，如果文件不存在则创建默认配置。"""
        if not os.path.exists(CONFIG_FILE):
            # 创建默认配置
            default_config = ConfigModel()
            self._save_config_file(default_config)
            return default_config
        
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ConfigModel(**data)
        except (IOError, json.JSONDecodeError, ValidationError) as e:
            print(f"配置文件 {CONFIG_FILE} 加载失败或格式错误: {e}. 使用默认配置。")
            return ConfigModel()

    def _save_config_file(self, config_data: ConfigModel):
        """将配置保存到 config.json。"""
        os.makedirs(os.path.dirname(CONFIG_FILE) or '.', exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data.dict(), f, indent=4, ensure_ascii=False)
        self.config = config_data

    def _save_secrets(self, new_secrets: Dict[str, str]):
        """将敏感配置保存到 .env 文件。"""
        # 确保 .env 文件存在
        if not os.path.exists(ENV_FILE):
            with open(ENV_FILE, 'w', encoding='utf-8') as f:
                f.write("# Environment variables for AI Email Summary Web\n")

        # 使用 dotenv.set_key 更新或添加键值对
        for key, value in new_secrets.items():
            if value: # 只有当值非空时才保存
                set_key(ENV_FILE, key, value)
        
        # 重新加载环境变量到 SecretConfig
        load_dotenv(override=True)
        self.secrets = SecretConfig()

    def update_config(self, config_data: Dict[str, Any], secret_data: Dict[str, str]):
        """
        更新并保存配置和敏感信息。
        
        :param config_data: config.json 中的新数据
        :param secret_data: .env 中的新敏感数据
        """
        # 1. 验证并保存 config.json
        new_config = ConfigModel(**config_data)
        self._save_config_file(new_config)

        # 2. 保存 .env
        self._save_secrets(secret_data)
        
        return new_config, self.secrets

    def get_config_for_api(self) -> Dict[str, Any]:
        """
        返回用于 API 接口的配置，敏感信息已脱敏或置空。
        """
        # 复制 config.json 的配置
        api_config = self.config.dict()
        
        # 添加敏感配置的占位符或脱敏值
        api_config.update({
            "EMAIL_ACCOUNT": self.secrets.EMAIL_ACCOUNT,
            "RECIPIENT_EMAIL": self.secrets.RECIPIENT_EMAIL,
            # 敏感信息不返回
            "EMAIL_PASSWORD": "", 
            "DEEPSEEK_API_KEY": "",
            "ADMIN_PASSWORD": "",
        })
        
        return api_config

# --- 脱敏工具 ---
def mask_secret(secret: Optional[str]) -> str:
    """
    将敏感字符串脱敏，只显示前4位和后4位。
    """
    if not secret:
        return ""
    secret = str(secret).strip()
    length = len(secret)
    if length <= 8:
        return "*" * length
    
    return f"{secret[:4]}{'*' * (length - 8)}{secret[-4:]}"

# 全局配置管理器实例
config_manager = ConfigManager()

# 初始化目录
os.makedirs(SUMMARY_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE) or '.', exist_ok=True)

# 确保在其他模块中可以直接导入 config_manager
# from aiesvc.config import config_manager, mask_secret, SQLITE_DB_PATH, LOG_FILE
