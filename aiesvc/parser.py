import email
from email.message import Message
from email.header import decode_header
from typing import Dict, Any, Optional, Tuple, List
import logging
import re
from bs4 import BeautifulSoup
import html2text
import tiktoken # 用于 token 感知截断

logger = logging.getLogger(__name__)

# 默认最大 token 数，用于估算截断
MAX_TOKENS = 4096 
# 留给 DeepSeek 总结回复的 token 数
REPLY_TOKEN_RESERVE = 512
# 邮件正文的最大 token 数
MAX_BODY_TOKENS = MAX_TOKENS - REPLY_TOKEN_RESERVE - 100 # 额外预留100个 token 给系统提示词等

# 初始化 tiktoken 编码器
try:
    ENCODER = tiktoken.get_encoding("cl100k_base")
except Exception:
    logger.warning("无法加载 tiktoken 编码器，将使用字符数进行粗略截断。")
    ENCODER = None

def decode_header_to_str(header: Any) -> str:
    """
    解码邮件头，返回可读字符串。
    """
    if not header:
        return ""
    
    parts = decode_header(header)
    decoded_parts = []
    for part, encoding in parts:
        if isinstance(part, bytes):
            try:
                decoded_parts.append(part.decode(encoding or 'utf-8', errors='replace'))
            except:
                decoded_parts.append(part.decode('latin-1', errors='replace'))
        else:
            decoded_parts.append(str(part))
    return "".join(decoded_parts)

def extract_body_text(msg: Message) -> Tuple[str, str]:
    """
    从邮件消息中提取纯文本和 HTML 内容。
    
    :return: (plain_text, html_text)
    """
    plain_text = ""
    html_text = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdispo = str(part.get("Content-Disposition"))
            
            # 忽略附件
            if cdispo.lower().startswith("attachment"):
                continue

            try:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or 'utf-8'
                if payload:
                    text = payload.decode(charset, errors='ignore')
                else:
                    continue
            except Exception:
                continue

            if ctype == "text/plain":
                plain_text += text + "\n"
            elif ctype == "text/html":
                html_text += text + "\n"
    else:
        ctype = msg.get_content_type()
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or 'utf-8'
            if payload:
                text = payload.decode(charset, errors='ignore')
            else:
                text = ""
        except Exception:
            text = ""

        if ctype == "text/plain":
            plain_text += text
        elif ctype == "text/html":
            html_text += text

    return plain_text.strip(), html_text.strip()

def html_to_text(html_content: str) -> str:
    """
    将 HTML 转换为纯文本，使用 html2text 库。
    """
    if not html_content:
        return ""
    
    try:
        # 使用 html2text 库进行转换
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.body_width = 0 # 不限制行宽
        text = h.handle(html_content)
        return text.strip()
    except Exception as e:
        logger.warning(f"html2text 转换失败，尝试使用 BeautifulSoup: {e}")
        try:
            # 备用：使用 BeautifulSoup 提取文本
            soup = BeautifulSoup(html_content, 'lxml')
            return soup.get_text('\n').strip()
        except Exception as e:
            logger.error(f"BeautifulSoup 转换失败: {e}")
            return ""

def smart_truncate_by_token(text: str, max_tokens: int) -> str:
    """
    Token 感知截断策略：按“首段 + 关键信息 + 尾段”拼接。
    
    如果文本长度超过 max_tokens，则取开头和结尾部分。
    """
    if not text:
        return ""

    if ENCODER:
        tokens = ENCODER.encode(text)
        if len(tokens) <= max_tokens:
            return text
        
        # 目标：保留 max_tokens 个 token，平均分配给开头和结尾
        half_tokens = max_tokens // 2
        
        # 解码开头部分
        start_text = ENCODER.decode(tokens[:half_tokens])
        
        # 解码结尾部分
        end_text = ENCODER.decode(tokens[-half_tokens:])
        
        # 拼接并添加省略号
        truncated_text = f"{start_text}\n\n... [邮件正文因过长被智能截断] ...\n\n{end_text}"
        
        return truncated_text
    else:
        # 如果没有 tiktoken，使用字符数进行粗略截断（原脚本的增强版）
        if len(text) <= max_tokens * 4: # 假设平均 4 个字符一个 token
            return text
        
        # 粗略截断：取前 50% 和后 50% 的字符
        half_chars = max_tokens * 2 # 粗略估计的字符数
        
        start_text = text[:half_chars]
        end_text = text[-half_chars:]
        
        truncated_text = f"{start_text}\n\n... [邮件正文因过长被粗略截断] ...\n\n{end_text}"
        return truncated_text

def parse_email(raw_email: bytes, uid: str) -> Optional[Dict[str, Any]]:
    """
    解析原始邮件字节流，提取关键信息并进行智能截断。
    """
    try:
        msg = email.message_from_bytes(raw_email)
        
        subject = decode_header_to_str(msg.get('Subject'))
        from_header = decode_header_to_str(msg.get('From'))
        date_header = decode_header_to_str(msg.get('Date'))
        message_id = msg.get('Message-ID')
        
        plain_text, html_text = extract_body_text(msg)
        
        # 优先使用纯文本，如果纯文本为空则使用 HTML 转换的文本
        body_text = plain_text
        if not body_text and html_text:
            body_text = html_to_text(html_text)
        
        # 清理多余的空白行和首尾空白
        body_text = re.sub(r'\n\s*\n', '\n\n', body_text).strip()
        
        # Token 感知截断
        body_text_truncated = smart_truncate_by_token(body_text, MAX_BODY_TOKENS)
        
        return {
            "subject": subject,
            "from": from_header,
            "date": date_header,
            "body_text": body_text_truncated,
            "message_id": message_id,
            "uid": uid,
            "original_body_length": len(body_text),
            "is_truncated": len(body_text_truncated) < len(body_text)
        }
        
    except Exception as e:
        logger.error(f"解析邮件 UID={uid} 失败: {e}", exc_info=True)
        return None

# 确保 html2text 和 beautifulsoup4 在 requirements.txt 中
# 如果需要更精确的 token 计算，需要安装 tiktoken
