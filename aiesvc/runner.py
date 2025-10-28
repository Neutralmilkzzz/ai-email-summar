import threading
import time
import logging
import datetime
from typing import Dict, Any, Optional

from aiesvc.config import config_manager
from aiesvc.mailbox import mailbox_manager
from aiesvc.storage import storage_manager
from aiesvc.notifier import notifier
from AiEmailSummary import run_once # 导入核心执行逻辑

logger = logging.getLogger("Runner")

class Runner:
    """
    后台任务运行器，使用线程实现可控启停和主循环。
    """
    
    # 状态机
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._status = self.IDLE
        self._last_run_stats: Dict[str, Any] = {}
        self._last_success_time: Optional[datetime.datetime] = None
        self._total_processed_count: int = 0
        self._total_failed_count: int = 0

    def get_status(self) -> Dict[str, Any]:
        """
        返回当前运行状态和指标。
        """
        return {
            "status": self._status,
            "is_running": self._thread is not None and self._thread.is_alive(),
            "last_run_stats": self._last_run_stats,
            "last_success_time": self._last_success_time.isoformat() if self._last_success_time else None,
            "total_processed_count": self._total_processed_count,
            "total_failed_count": self._total_failed_count,
            "time_gap": config_manager.config.TIME_GAP,
        }

    def start(self) -> bool:
        """
        启动后台任务线程。
        """
        if self._status != self.IDLE:
            logger.warning(f"任务已在 {self._status} 状态，无法启动。")
            return False

        logger.info("启动后台邮件总结任务...")
        self._stop_event.clear()
        self._status = self.RUNNING
        self._thread = threading.Thread(target=self._run_loop, name="EmailSummaryRunner")
        self._thread.daemon = True
        self._thread.start()
        return True

    def stop(self) -> bool:
        """
        优雅地停止后台任务线程。
        """
        if self._status != self.RUNNING:
            logger.warning(f"任务不在 RUNNING 状态 ({self._status})，无法停止。")
            return False

        logger.info("接收到停止指令，尝试优雅退出...")
        self._status = self.STOPPING
        self._stop_event.set()
        
        # 等待线程结束，最多等待 5 秒
        self._thread.join(timeout=5)
        
        if self._thread.is_alive():
            logger.error("线程未能在 5 秒内优雅退出，可能存在阻塞。")
            # 此时无法强制杀死线程，只能等待其自然结束
            self._status = self.ERROR
            return False
        
        self._status = self.IDLE
        self._thread = None
        logger.info("后台邮件总结任务已停止。")
        return True

    def _run_loop(self):
        """
        后台任务的主循环逻辑。
        """
        logger.info("Runner 线程开始运行。")
        
        try:
            while not self._stop_event.is_set():
                start_time = time.time()
                
                # 1. 执行核心逻辑
                try:
                    self._last_run_stats = run_once()
                    
                    # 2. 更新总统计数据
                    self._total_processed_count += self._last_run_stats.get('processed_count', 0)
                    self._total_failed_count += self._last_run_stats.get('failed_count', 0)
                    
                    if self._last_run_stats.get('failed_count', 0) >= 0: # 排除连接失败 (-1) 的情况
                        self._last_success_time = datetime.datetime.now()
                        self._status = self.RUNNING # 保持 RUNNING 状态
                    else:
                        self._status = self.ERROR
                        logger.error("本次运行因 IMAP 连接失败而终止，将等待下一个周期重试。")
                        
                except Exception as e:
                    logger.error(f"执行 run_once 时发生未捕获的异常: {e}", exc_info=True)
                    self._status = self.ERROR
                    self._last_run_stats = {"error": str(e)}

                # 3. 计算休眠时间
                end_time = time.time()
                elapsed_time = end_time - start_time
                time_gap = config_manager.config.TIME_GAP
                sleep_time = max(0, time_gap - elapsed_time)
                
                logger.info(f"本次运行耗时 {elapsed_time:.2f} 秒。休眠 {sleep_time:.2f} 秒。")

                # 4. 优雅休眠 (等待停止事件或超时)
                self._stop_event.wait(sleep_time)

        except Exception as e:
            logger.critical(f"Runner 线程发生致命错误: {e}", exc_info=True)
            self._status = self.ERROR
        finally:
            # 确保 IMAP 连接关闭
            mailbox_manager.close()
            logger.info("Runner 线程退出。")
            
# 全局运行器实例
runner = Runner()

# 确保在其他模块中可以直接导入 runner
# from aiesvc.runner import runner
