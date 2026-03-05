"""工具函数"""

import re
import tiktoken


def estimate_tokens(text: str, model: str = "gpt-4o") -> int:
    """估算文本的 token 数量"""
    try:
        enc = tiktoken.encoding_for_model(model)
        return len(enc.encode(text))
    except Exception:
        # 粗略估算：中文 ~1.5 token/字，英文 ~0.25 token/词
        return len(text) // 3


def detect_language(text: str) -> str:
    """
    简单的语言检测。

    规则：
    - 中文字符占比 > 30% → "zh"
    - 否则默认 "en"
    """
    if not text:
        return "en"
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    ratio = chinese_chars / len(text)
    return "zh" if ratio > 0.3 else "en"


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    return re.sub(r'[<>:"/\\|?*]', '_', name)
