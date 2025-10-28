import logging
import logging.handlers
import json
import queue
import time
from typing import Any, Dict, Optional

# SSE 队列的最大容量
LOG_QUEUE_MAX_SIZE = 1000

class SSEQueueHandler(logging.Handler):
    """
    一个将日志记录推送到内存队列的处理器，用于 SSE 实时日志流。
    """
    def __init__(self, log_queue: queue.Queue, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord):
        try:
            # 使用 self.format(record) 确保记录被格式化为字符串
            message = self.format(record)
            if self.log_queue.full():
                # 队列满时，丢弃最旧的记录
                try:
                    self.log_queue.get_nowait()
                except queue.Empty:
                    pass # Should not happen if full() is true
            self.log_queue.put_nowait(message)
        except Exception:
            self.handleError(record)

class JsonFormatter(logging.Formatter):
    """
    将日志记录格式化为 JSON 字符串的格式化器。
    """
    def format(self, record: logging.LogRecord) -> str:
        # 基础字段
        log_record: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "module": record.name,
            "funcName": record.funcName,
            "lineno": record.lineno,
            "message": record.getMessage(),
        }

        # 尝试添加额外的结构化数据
        if hasattr(record, 'extra_data'):
            log_record.update(record.extra_data)

        # 异常信息
        if record.exc_info:
            log_record['exc_info'] = self.formatException(record.exc_info)

        # 堆栈信息
        if record.stack_info:
            log_record['stack_info'] = self.formatStack(record.stack_info)

        # 移除可能导致问题的字段
        if 'extra_data' in log_record:
            del log_record['extra_data']
            
        # 确保 message 是字符串
        log_record['message'] = str(log_record['message'])

        return json.dumps(log_record, ensure_ascii=False)

# 全局日志队列
sse_log_queue: queue.Queue[str] = queue.Queue(maxsize=LOG_QUEUE_MAX_SIZE)

def setup_logging(log_file_path: str, log_level: int = logging.INFO):
    """
    设置全局日志系统，包括文件轮转、JSON 格式化和 SSE 队列适配。
    """
    # 根 Logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 移除所有现有处理器，防止重复
    if root_logger.handlers:
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

    # 1. 文件轮转处理器 (RotatingFileHandler)
    # 10MB * 5 个文件轮转
    file_handler = logging.handlers.RotatingFileHandler(
        log_file_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(JsonFormatter())
    root_logger.addHandler(file_handler)

    # 2. SSE 队列处理器
    sse_handler = SSEQueueHandler(sse_log_queue)
    sse_handler.setFormatter(JsonFormatter()) # SSE 流也使用 JSON 格式
    root_logger.addHandler(sse_handler)

    # 3. 控制台处理器 (可选，用于本地开发)
    console_handler = logging.StreamHandler()
    # 控制台使用更易读的格式
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 确保 requests 等库的日志级别不会太低
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("imapclient").setLevel(logging.WARNING)

def get_sse_log_queue() -> queue.Queue[str]:
    """
    获取用于 SSE 推送的全局日志队列。
    """
    return sse_log_queue

# 示例：结构化日志的使用
# logger.info("Processing email", extra={'extra_data': {'email_id': 123, 'subject': 'Test'}})
# logger.error("Failed to connect", exc_info=True)

if __name__ == '__main__':
    # 最小化测试
    setup_logging("test_runtime.log", logging.DEBUG)
    logger = logging.getLogger("TEST_LOG")
    
    logger.info("系统启动中...")
    logger.debug("这是一个调试信息")
    
    try:
        1 / 0
    except ZeroDivisionError:
        logger.exception("发生了一个异常！")
        
    logger.info("测试结构化日志", extra={'extra_data': {'user_id': 999, 'action': 'login'}})
    
    # 检查 SSE 队列
    print("\nSSE 队列内容:")
    q = get_sse_log_queue()
    while not q.empty():
        print(q.get())
