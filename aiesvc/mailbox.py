import logging
import imaplib
import socket
import time
from typing import List, Optional, Dict, Any

from aiesvc.config import config_manager, mask_secret

logger = logging.getLogger(__name__)

class MailboxManager:
    """
    IMAP 客户端，负责连接、登录、搜索和获取邮件。
    """
    def __init__(self):
        self.config = config_manager.config
        self.secrets = config_manager.secrets
        self.imap: Optional[imaplib.IMAP4_SSL] = None
        self.is_connected = False

    def _get_masked_account(self) -> str:
        """获取脱敏的邮箱账号。"""
        return mask_secret(self.secrets.EMAIL_ACCOUNT)

    def connect(self) -> bool:
        """
        连接并登录 IMAP 服务器，选择邮箱。
        """
        if self.is_connected:
            return True

        account = self.secrets.EMAIL_ACCOUNT
        password = self.secrets.EMAIL_PASSWORD
        server = self.config.IMAP_SERVER
        port = self.config.IMAP_PORT

        if not account or not password:
            logger.error("邮箱账号或授权码未配置。")
            return False

        masked_account = mask_secret(account)

        try:
            logger.info(f"尝试连接 IMAP 服务器: {server}:{port} (账号: {masked_account})")

            # 1️⃣ 建立 SSL 连接
            self.imap = imaplib.IMAP4_SSL(server, port)

            # 2️⃣ 网易邮箱特殊要求：发送 ID 命令（防止 SELECT 失败）
            imaplib.Commands['ID'] = ('NONAUTH', 'AUTH', 'SELECTED')
            args = ("name", "imaplib", "version", "1.0.0")
            try:
                self.imap._simple_command('ID', '("' + '" "'.join(args) + '")')
                logger.info("📡 已发送 IMAP ID 命令（兼容 163 邮箱）")
            except Exception as e:
                logger.warning(f"发送 ID 命令失败（可忽略）: {e}")

            # 3️⃣ 登录
            self.imap.login(account, password)
            logger.info("✅ IMAP 登录成功")

            # 4️⃣ 查看服务器提供的邮箱文件夹
            typ, mailboxes = self.imap.list()
            if typ == 'OK':
                for mbox in mailboxes:
                    logger.info(f"📬 服务器邮箱文件夹: {mbox.decode(errors='ignore')}")

            # 5️⃣ 尝试选择邮箱
            select_status, _ = self.imap.select("INBOX")
            if select_status != "OK":
                logger.warning("选择 INBOX 失败，尝试使用 '收件箱' ...")
                select_status, _ = self.imap.select("收件箱")

            if select_status != "OK":
                logger.error(f"❌ 选择邮箱失败: {select_status}")
                self.close()
                return False

            self.is_connected = True
            logger.info("✅ IMAP 连接成功并选中邮箱。")
            return True

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP 登录或选择邮箱失败: {e}", exc_info=True)
            self.close()
        except (socket.error, imaplib.IMAP4_SSL.error) as e:
            logger.error(f"IMAP 连接失败: {e}", exc_info=True)
            self.close()
        except Exception as e:
            logger.error(f"连接 IMAP 发生未知错误: {e}", exc_info=True)
            self.close()

        return False

    def close(self):
        """关闭 IMAP 连接。"""
        if self.imap:
            try:
                self.imap.logout()
            except Exception:
                pass
            finally:
                self.imap = None
                self.is_connected = False
                logger.info("IMAP 连接已关闭。")

    def reconnect_if_needed(self) -> bool:
        """检查连接状态，如果断开则尝试重连。"""
        if self.is_connected:
            try:
                self.imap.noop()
                return True
            except Exception:
                logger.warning("IMAP 连接已失效，尝试重连...")
                self.is_connected = False
                self.imap = None

        for attempt in range(3):
            if self.connect():
                try:
                    status, _ = self.imap.select("INBOX")
                    if status == "OK":
                        return True
                except Exception as e:
                    logger.warning(f"重连后选择 INBOX 失败: {e}")
            time.sleep(1)

        logger.error("IMAP 重连失败。")
        return False

    def search_unseen_uids(self) -> List[str]:
        """搜索 INBOX 中所有未读邮件的 UID。"""
        if not self.reconnect_if_needed():
            return []

        try:
            status, data = self.imap.uid('search', None, 'UNSEEN')
            if status != 'OK':
                logger.error(f"IMAP 搜索失败: {status}")
                return []

            uid_list = data[0].split()
            uids = [uid.decode('utf-8') for uid in uid_list]
            logger.info(f"搜索到 {len(uids)} 封未读邮件。")
            return uids

        except Exception as e:
            logger.error(f"搜索未读邮件时发生错误: {e}", exc_info=True)
            self.is_connected = False
            return []

    def fetch_email_raw(self, uid: str) -> Optional[bytes]:
        """根据 UID 获取邮件的原始数据。"""
        if not self.reconnect_if_needed():
            return None

        try:
            status, data = self.imap.uid('fetch', uid, '(RFC822)')
            if status != 'OK':
                logger.error(f"获取邮件 UID={uid} 失败: {status}")
                return None

            raw_data = data[0][1]
            return raw_data

        except Exception as e:
            logger.error(f"获取邮件 UID={uid} 时发生错误: {e}", exc_info=True)
            self.is_connected = False
            return None

    def mark_email_seen(self, uid: str) -> bool:
        """标记邮件为已读 (\Seen)。"""
        if not self.reconnect_if_needed():
            return False

        try:
            status, _ = self.imap.uid('STORE', uid, '+FLAGS', '(\Seen)')
            if status == 'OK':
                logger.debug(f"邮件 UID={uid} 已标记为已读。")
                return True
            else:
                logger.warning(f"标记邮件 UID={uid} 为已读失败: {status}")
                return False
        except Exception as e:
            logger.error(f"标记邮件 UID={uid} 为已读时发生错误: {e}", exc_info=True)
            self.is_connected = False
            return False


# 全局邮箱管理器实例
mailbox_manager = MailboxManager()
