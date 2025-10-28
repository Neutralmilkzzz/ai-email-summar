import logging
import smtplib
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, make_msgid, formatdate
from typing import Optional

from aiesvc.config import config_manager, mask_secret
from aiesvc.storage import storage_manager

logger = logging.getLogger(__name__)

class Notifier:
    """
    SMTP 邮件通知器，用于发送每日总结邮件。
    """
    def __init__(self):
        self.config = config_manager.config
        self.secrets = config_manager.secrets

    def _get_summary_content(self) -> Optional[str]:
        """获取当日总结文件内容"""
        today_str = storage_manager.get_today_summary_filename().split('/')[-1].replace('.txt', '')
        content = storage_manager.get_summary_file_content(today_str)
        if not content:
            logger.info("当日无总结内容，跳过通知。")
            return None
        entries = content.strip().split('\n---\n')
        valid_entries = [e.strip() for e in entries if e.strip()]
        recent_entries = valid_entries[-self.config.AMOUNT_OF_REPORT:]
        if not recent_entries:
            return None
        header = f"【AI 邮件总结】{today_str} 邮件摘要 ({len(recent_entries)}/{len(valid_entries)} 条)\n\n"
        return header + '\n---\n'.join(recent_entries)

    def send_daily_summary(self) -> bool:
        """发送当日邮件总结"""
        if not self.config.ENABLE_SMTP_NOTIFIER:
            logger.info("SMTP 通知未启用，跳过发送。")
            return True

        content = self._get_summary_content()
        if not content:
            return True

        account = self.secrets.EMAIL_ACCOUNT
        password = self.secrets.EMAIL_PASSWORD
        recipient = self.secrets.RECIPIENT_EMAIL
        server = self.config.SMTP_SERVER
        port = self.config.SMTP_PORT

        if not all([account, password, recipient, server]):
            logger.error("SMTP 配置不完整（账号、授权码、收件人、服务器）")
            return False

        masked_account = mask_secret(account)
        masked_recipient = mask_secret(recipient)

        try:
            # === ✅ 构造标准 RFC5322 邮件 ===
            msg = MIMEMultipart()
            msg['From'] = formataddr(("AI 邮件总结", account))                # 发件人
            msg['To'] = formataddr(("收件人", recipient))                    # 收件人
            msg['Reply-To'] = account                                        # 回复地址
            msg['Subject'] = f"【AI 邮件总结】{datetime.date.today().isoformat()} 每日摘要"
            msg['Date'] = formatdate(localtime=True)                         # 日期头
            msg['Message-ID'] = make_msgid(domain=account.split('@')[-1])    # 全局唯一ID
            msg['MIME-Version'] = "1.0"                                      # 明确 MIME 版本

            # === ✅ 添加正文 ===
            body = MIMEText(content, 'plain', 'utf-8')
            msg.attach(body)

            # === ✅ 连接并发送 ===
            logger.info(f"📡 连接 SMTP: {server}:{port} (发件人: {masked_account} → 收件人: {masked_recipient})")
            smtp = smtplib.SMTP_SSL(server, port, timeout=10)
            smtp.login(account, password)
            smtp.sendmail(account, [recipient], msg.as_string())
            smtp.quit()

            logger.info("✅ 每日总结邮件发送成功。")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP 认证失败，请检查邮箱账号和授权码。", exc_info=True)
        except smtplib.SMTPException as e:
            logger.error(f"SMTP 发送邮件失败: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"发送邮件时发生未知错误: {e}", exc_info=True)
        return False


# === 全局实例 ===
notifier = Notifier()
