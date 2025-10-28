import logging
import time
import json
from typing import Dict, Any, Optional
import requests

from aiesvc.config import config_manager, mask_secret

logger = logging.getLogger(__name__)

# 默认重试次数
MAX_RETRIES = 3
# 默认超时时间（秒）
DEFAULT_TIMEOUT = 30
# 默认温度
DEFAULT_TEMPERATURE = 0.3

class SummarizerProvider:
    """
    DeepSeek 概括服务的提供者，负责 API 调用、重试和错误处理。
    """
    def __init__(self):
        self.config = config_manager.config
        self.secrets = config_manager.secrets

    def _get_api_key(self) -> str:
        """获取 API Key，如果为空则抛出异常。"""
        api_key = self.secrets.DEEPSEEK_API_KEY
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY 未配置。")
        return api_key

    def _get_system_prompt(self) -> str:
        """返回 DeepSeek 的系统提示词。"""
        return (
            "你是一个专业的邮件总结助手。你的任务是简洁、准确地概括用户提供的邮件内容。 "
            "请提取邮件的核心主题、关键行动点和重要信息。 "
            "以清晰的、分点的中文形式输出总结，不要包含任何额外的寒暄或解释。"
        )

    def summarize_email(self, email_data: Dict[str, Any]) -> str:
        """
        调用 DeepSeek API 总结邮件内容。
        
        :param email_data: 包含邮件主题、发件人、正文等信息的字典。
        :return: 总结文本或降级提示。
        """
        try:
            api_key = self._get_api_key()
        except ValueError as e:
            logger.error(f"总结失败: {e}")
            return f"[总结服务未配置] {email_data.get('subject', '无主题')}"

        subject = email_data.get('subject', '无主题')
        body_text = email_data.get('body_text', '无正文')

        user_prompt = (
            f"请总结以下邮件:\n\n"
            f"主题: {subject}\n"
            f"发件人: {email_data.get('from', '未知')}\n"
            f"日期: {email_data.get('date', '未知')}\n"
            f"--- 邮件正文 ---\n"
            f"{body_text}"
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.config.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": DEFAULT_TEMPERATURE,
            "stream": False,
        }

        masked_key = mask_secret(api_key)
        
        for attempt in range(MAX_RETRIES):
            try:
                logger.info(f"尝试总结邮件: {subject} (尝试 {attempt + 1}/{MAX_RETRIES})")
                response = requests.post(
                    self.config.DEEPSEEK_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=DEFAULT_TIMEOUT
                )
                
                response.raise_for_status() # 抛出 HTTPError 异常
                
                data = response.json()
                
                if not data.get('choices'):
                    logger.error(f"API 返回空 choices: {data}")
                    raise Exception("API 返回空 choices")
                
                summary = data['choices'][0]['message']['content']
                logger.info(f"总结成功: {subject}")
                return summary.strip()

            except requests.exceptions.RequestException as e:
                status_code = getattr(e.response, 'status_code', 'N/A')
                
                if status_code in [401, 403]:
                    # 认证或权限错误，不重试
                    logger.error(f"API 认证失败 (Key: {masked_key}): {e}")
                    return f"[API 认证失败] 邮件主题: {subject}"
                
                if status_code == 429:
                    # 速率限制，指数退避
                    wait_time = 2 ** attempt
                    logger.warning(f"API 速率限制 (429)。等待 {wait_time} 秒后重试。")
                    time.sleep(wait_time)
                elif attempt < MAX_RETRIES - 1:
                    # 其他网络或服务器错误，等待后重试
                    wait_time = 1
                    logger.warning(f"API 请求失败: {e} (状态码: {status_code})。等待 {wait_time} 秒后重试。")
                    time.sleep(wait_time)
                else:
                    # 最后一次尝试失败
                    logger.error(f"API 请求失败，达到最大重试次数: {e}", exc_info=True)
                    return f"[API 总结失败] 邮件主题: {subject}"

            except Exception as e:
                logger.error(f"处理 API 响应时发生未知错误: {e}", exc_info=True)
                return f"[API 响应错误] 邮件主题: {subject}"

        # 如果所有重试都失败
        return f"[API 总结失败] 邮件主题: {subject}"

# 全局总结器实例
summarizer_provider = SummarizerProvider()

# 确保在其他模块中可以直接导入 summarizer_provider
# from aiesvc.summarizer import summarizer_provider
