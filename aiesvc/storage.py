import os
import sqlite3
import datetime
import logging
from typing import Optional, Dict, Any, List

from aiesvc.config import SQLITE_DB_PATH, SUMMARY_DIR

logger = logging.getLogger(__name__)

class StorageManager:
    """
    负责总结文件写入和邮件幂等性处理的存储管理器。
    """
    def __init__(self):
        self._ensure_db_and_table()

    def _get_db_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(SQLITE_DB_PATH)

    def _ensure_db_and_table(self):
        """确保数据库文件和 processed_emails 表存在"""
        os.makedirs(os.path.dirname(SQLITE_DB_PATH) or '.', exist_ok=True)
        
        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            # message_id 可能会为空，因此使用 uid 和 mailbox 作为主键
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_emails (
                    uid TEXT NOT NULL,
                    mailbox TEXT NOT NULL,
                    message_id TEXT,
                    processed_at DATETIME NOT NULL,
                    summary_hash TEXT,
                    PRIMARY KEY (mailbox, uid)
                )
            """)
            conn.commit()
        logger.info(f"SQLite 数据库已初始化: {SQLITE_DB_PATH}")

    # --- 幂等性处理 ---

    def has_processed(self, uid: str, mailbox: str = 'INBOX') -> bool:
        """
        检查给定 UID 的邮件是否已被处理。
        """
        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM processed_emails WHERE uid = ? AND mailbox = ?",
                (uid, mailbox)
            )
            return cursor.fetchone() is not None

    def mark_processed(self, uid: str, message_id: Optional[str], summary_text: str, mailbox: str = 'INBOX'):
        """
        标记一封邮件已处理。
        """
        import hashlib
        summary_hash = hashlib.sha256(summary_text.encode('utf-8')).hexdigest()
        
        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO processed_emails 
                    (uid, mailbox, message_id, processed_at, summary_hash) 
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (uid, mailbox, message_id, datetime.datetime.now().isoformat(), summary_hash)
                )
                conn.commit()
                logger.debug(f"已标记邮件 UID={uid} 为已处理。")
            except sqlite3.IntegrityError:
                # 理论上在 has_processed 检查后不应发生，但作为兜底
                logger.warning(f"尝试重复标记已处理邮件 UID={uid}。")

    # --- 总结文件处理 ---
    
    def get_today_summary_filename(self) -> str:
        """
        获取今日总结文件的完整路径。
        """
        today_str = datetime.date.today().isoformat()
        return os.path.join(SUMMARY_DIR, f"{today_str}.txt")

    def update_daily_summary(self, summary_entry: Dict[str, Any]):
        """
        将一条新的总结条目追加到当日的总结文件中。
        
        :param summary_entry: 包含邮件主题、发件人、日期和总结文本的字典。
        """
        filename = self.get_today_summary_filename()
        
        # 格式化总结条目
        subject = summary_entry.get('subject', '无主题')
        from_addr = summary_entry.get('from', '未知发件人')
        date_str = summary_entry.get('date', '未知日期')
        summary_text = summary_entry.get('summary_text', '无内容')
        
        entry_text = f"""
---
主题: {subject}
发件人: {from_addr}
日期: {date_str}
总结:
{summary_text.strip()}
---
"""
        try:
            with open(filename, 'a', encoding='utf-8') as f:
                f.write(entry_text)
            logger.info(f"总结已追加到文件: {filename}")
        except IOError as e:
            logger.error(f"写入总结文件失败: {e}", exc_info=True)

    def get_summary_file_content(self, date_str: str) -> Optional[str]:
        """
        获取指定日期的总结文件内容。
        
        :param date_str: 日期字符串，格式 YYYY-MM-DD。
        :return: 文件内容或 None。
        """
        filename = os.path.join(SUMMARY_DIR, f"{date_str}.txt")
        if not os.path.exists(filename):
            return None
        
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return f.read()
        except IOError:
            logger.error(f"读取总结文件失败: {filename}", exc_info=True)
            return None

    def list_summary_files(self) -> List[Dict[str, Any]]:
        """
        列出所有历史总结文件。
        """
        files = []
        for filename in os.listdir(SUMMARY_DIR):
            if filename.endswith('.txt'):
                date_str = filename.replace('.txt', '')
                try:
                    file_path = os.path.join(SUMMARY_DIR, filename)
                    stat = os.stat(file_path)
                    files.append({
                        "date": date_str,
                        "filename": filename,
                        "size": stat.st_size,
                        "modified_at": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
                except Exception as e:
                    logger.warning(f"获取文件 {filename} 信息失败: {e}")
        
        # 按日期倒序排列
        files.sort(key=lambda x: x['date'], reverse=True)
        return files

# 全局存储管理器实例
storage_manager = StorageManager()

# 确保在其他模块中可以直接导入 storage_manager
# from aiesvc.storage import storage_manager
