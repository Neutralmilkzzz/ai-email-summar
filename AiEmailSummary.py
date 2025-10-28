import logging
import datetime
import time
from typing import Dict, Any, Optional

# --- 导入服务组件 ---
from aiesvc.config import config_manager
from aiesvc.mailbox import mailbox_manager
from aiesvc.parser import parse_email
from aiesvc.summarizer import summarizer_provider
from aiesvc.storage import storage_manager
from aiesvc.notifier import notifier

logger = logging.getLogger("AiEmailSummary")

# --- 改造说明 ---
# 1. 顶部硬编码常量已全部移除，改为从 aiesvc.config.config_manager 动态获取。
# 2. 原有的核心逻辑已拆分为可复用的函数 `process_single_email` 和 `run_once`。
# 3. 原有的主循环 `while True: ...` 已移除，循环逻辑迁移到 `aiesvc/runner.py` 中。
# 4. 邮件解析、总结、存储、通知等功能已通过导入的服务组件实现。

def process_single_email(uid: str, mark_seen: bool = True) -> bool:
    """
    处理单个邮件的完整流程：获取 -> 解析 -> 幂等检查 -> 总结 -> 存储 -> 标记。
    
    :param uid: 邮件的 UID。
    :param mark_seen: 是否在处理成功后标记为已读。
    :return: 邮件是否成功处理（包括幂等跳过）。
    """
    # 1. 幂等检查
    if storage_manager.has_processed(uid, mailbox='INBOX'):
        logger.info(f"邮件 UID={uid} 已处理过，跳过。")
        return True

    # 2. 获取原始邮件
    raw_email = mailbox_manager.fetch_email_raw(uid)
    if not raw_email:
        logger.error(f"无法获取邮件 UID={uid} 的原始数据。")
        return False

    # 3. 解析邮件
    email_data = parse_email(raw_email, uid)
    if not email_data:
        logger.error(f"邮件 UID={uid} 解析失败。")
        return False

    # 4. 总结邮件
    summary_text = summarizer_provider.summarize_email(email_data)
    
    # 5. 存储总结
    summary_entry = {
        "subject": email_data['subject'],
        "from": email_data['from'],
        "date": email_data['date'],
        "summary_text": summary_text,
    }
    storage_manager.update_daily_summary(summary_entry)
    
    # 6. 标记为已处理 (幂等库)
    storage_manager.mark_processed(
        uid=uid, 
        message_id=email_data.get('message_id'), 
        summary_text=summary_text,
        mailbox='INBOX'
    )

    # 7. 可选标记为已读
    if mark_seen:
        mailbox_manager.mark_email_seen(uid)
        
    logger.info(f"成功处理邮件: {email_data['subject']}")
    return True

def run_once() -> Dict[str, Any]:
    """
    执行一次邮件检查和总结流程。
    
    :return: 包含处理结果的字典。
    """
    stats = {
        "total_unseen": 0,
        "processed_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "start_time": datetime.datetime.now().isoformat()
    }
    
    logger.info("--- 开始执行邮件检查和总结流程 (run_once) ---")
    
    # 1. 确保 IMAP 连接
    if not mailbox_manager.reconnect_if_needed():
        logger.error("IMAP 连接失败，本次运行终止。")
        stats['failed_count'] = -1 # 标记连接失败
        return stats
        
    # 2. 搜索未读邮件 UID
    unseen_uids = mailbox_manager.search_unseen_uids()
    stats['total_unseen'] = len(unseen_uids)
    
    if not unseen_uids:
        logger.info("未发现新的未读邮件。")
        return stats
        
    logger.info(f"发现 {len(unseen_uids)} 封未读邮件，开始逐个处理...")
    
    # 3. 逐个处理邮件
    for uid in unseen_uids:
        try:
            if storage_manager.has_processed(uid, mailbox='INBOX'):
                stats['skipped_count'] += 1
                logger.debug(f"邮件 UID={uid} 已处理过，跳过。")
                continue
                
            if process_single_email(uid):
                stats['processed_count'] += 1
            else:
                stats['failed_count'] += 1
                
        except Exception as e:
            stats['failed_count'] += 1
            logger.error(f"处理邮件 UID={uid} 时发生未捕获的异常: {e}", exc_info=True)
            
    # 4. 可选发送通知
    if config_manager.config.ENABLE_SMTP_NOTIFIER and stats['processed_count'] > 0:
        notifier.send_daily_summary()
        
    logger.info("--- 邮件检查和总结流程执行完毕 ---")
    
    return stats

def main():
    """
    原脚本的兼容入口，现在只执行一次 run_once。
    """
    logger.info("AiEmailSummary 兼容入口启动，执行一次流程。")
    config_manager.config.validate_time_gap(config_manager.config.TIME_GAP) # 确保配置已加载
    run_once()
    
if __name__ == '__main__':
    # 确保日志系统已初始化
    from aiesvc.logging_utils import setup_logging
    setup_logging(config_manager.LOG_FILE, logging.INFO)
    main()
