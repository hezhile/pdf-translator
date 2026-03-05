"""文本块分类器 - 使用 LLM 对文本块进行翻译分类"""

import subprocess
import asyncio
import shutil
import re
from typing import Optional

# 尝试导入 TranslateCategory，支持两种运行模式
try:
    from .models import TranslateCategory
except ImportError:
    try:
        from models import TranslateCategory
    except ImportError:
        # 如果都失败，定义本地版本
        from enum import Enum
        class TranslateCategory(Enum):
            """文本块的翻译分类"""
            PARAGRAPH = "paragraph"
            CARD = "card"
            SKIP = "skip"


CLASSIFY_SYSTEM_PROMPT = """你是一个文本分类器，判断文本块应该采用哪种翻译策略。

分类规则：
A. PARAGRAPH - 正文段落（必须合并同一行的多个span）
   - 完整的句子或段落
   - 论文正文、说明文字、描述性内容
   - 示例："This paper presents a novel approach to..."

B. CARD - 结构化信息卡片（逐行独立翻译，不合并）
   - 姓名+职位+地点的组合
   - 列表项、标签、独立短语
   - 示例："John Smith\nSoftware Engineer\nUnited States"

C. SKIP - 不需要翻译（跳过）
   - arXiv ID：arXiv:2401.12345v1
   - DOI：DOI: 10.1234/5678
   - 页码、参考文献编号
   - 纯数字、纯符号
   - URL、邮箱

输出格式：只输出分类字母（A、B 或 C），每行一个，不要其他内容。"""


# C类规则（本地预过滤，减少 LLM 调用）
SKIP_PATTERNS = [
    r'^arXiv:',           # arXiv ID
    r'^DOI:',             # DOI
    r'^doi:',             # doi
    r'^\d+$',             # 纯数字（页码）
    r'^\[\d+\]$',         # 参考文献编号 [1]
    r'^https?://',        # URL
    r'^[\w.-]+@',         # 邮箱
    r'^[©©]',             # 版权符号
    r'^\d{4}-\d{2}-\d{2}$',  # 日期
    r'^[IVXLCDM]+$',      # 罗马数字
    r'^pp?\.\s*\d+',      # 页码引用
]

# 人名模式（纯人名，跳过翻译）
# 匹配：名 姓，名 中间名 姓，带称谓的人名
NAME_PATTERNS = [
    # 带称谓的人名：Mr. John Smith, Dr. Jane Doe, President Trump
    r'^(Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.|President|Secretary|Senator|Governor|Director|CEO|CFO)\s+[A-Z][a-z]+(\s+[A-Z][a-z]+)*$',
    # 纯人名（2-4个单词，每个首字母大写）：John Smith, Pete Hegseth
    r'^[A-Z][a-z]+(\s+[A-Z][a-z]+){1,3}$',
    # 单个人名（知名人物）：Trump, Biden, Xi
    r'^[A-Z][a-z]{2,15}$',
]


def _is_likely_name(text: str) -> bool:
    """判断文本是否可能是人名"""
    text = text.strip()
    
    # 太长或太短不太可能是人名
    if len(text) < 3 or len(text) > 50:
        return False
    
    # 检查人名模式
    for pattern in NAME_PATTERNS:
        if re.match(pattern, text):
            return True
    
    # 额外检查：如果全是首字母大写的单词，可能是人名
    words = text.split()
    if 1 <= len(words) <= 4:
        if all(re.match(r'^[A-Z][a-z]+$', w) for w in words):
            # 排除常见的非人名词汇
            non_name_words = {'The', 'This', 'That', 'These', 'Those', 'What', 'When', 
                            'Where', 'Which', 'While', 'University', 'College', 'School',
                            'Department', 'Institute', 'Center', 'Program', 'Project'}
            if not any(w in non_name_words for w in words):
                return True
    
    return False


def _is_skip_by_pattern(text: str) -> bool:
    """本地规则判断是否为 C 类（跳过）"""
    text = text.strip()
    if len(text) < 2:
        return True
    
    # 检查跳过模式
    for pattern in SKIP_PATTERNS:
        if re.match(pattern, text):
            return True
    
    # 检查是否是人名
    if _is_likely_name(text):
        return True
    
    return False


def _find_openclaw_binary() -> str:
    """查找 openclaw 可执行文件路径"""
    path = shutil.which("openclaw")
    if path is None:
        raise FileNotFoundError("找不到 openclaw 命令")
    return path


async def classify_blocks(
    blocks: list,
    batch_size: int = 50,
) -> list[str]:
    """
    对文本块进行分类。
    
    参数:
        blocks: TextBlock 列表
        batch_size: 每批分类的块数量
    
    返回:
        分类结果列表：["A", "B", "C", ...]
    """
    results = ["A"] * len(blocks)  # 默认为 A 类
    
    # 1. 本地规则预过滤 C 类
    for i, block in enumerate(blocks):
        if _is_skip_by_pattern(block.text):
            results[i] = "C"
    
    # 2. 收集需要 LLM 分类的块
    uncached_indices = [i for i, r in enumerate(results) if r != "C"]
    
    if not uncached_indices:
        return results
    
    # 3. 分批调用 LLM 分类
    uncached_blocks = [blocks[i] for i in uncached_indices]
    
    # 将块分批
    batches = []
    for i in range(0, len(uncached_blocks), batch_size):
        batches.append(uncached_blocks[i:i+batch_size])
    
    openclaw_bin = _find_openclaw_binary()
    
    for batch_idx, batch in enumerate(batches):
        # 构建分类 prompt
        prompt = _build_classify_prompt(batch)
        
        # 生成唯一的 session ID，避免阻塞 main agent
        import uuid
        session_id = f"classify-{uuid.uuid4().hex[:8]}"
        
        # 调用 OpenClaw（使用独立 session）
        process = await asyncio.create_subprocess_exec(
            openclaw_bin,
            "agent",
            "--agent", "main",
            "--session-id", session_id,
            "--message", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=120,  # 增加到 120 秒
            )
        except asyncio.TimeoutError:
            process.kill()
            print(f"⚠️ 分类超时，使用默认分类 A")
            continue
        
        output = stdout.decode().strip()
        
        # 解析分类结果
        batch_results = _parse_classify_output(output, len(batch))
        
        # 写入结果
        for j, cat in enumerate(batch_results):
            global_idx = uncached_indices[batch_idx * batch_size + j]
            results[global_idx] = cat
    
    return results


def _build_classify_prompt(blocks: list) -> str:
    """构建分类 prompt"""
    lines = [
        CLASSIFY_SYSTEM_PROMPT,
        "",
        f"请对以下 {len(blocks)} 个文本块进行分类：",
        "",
    ]
    
    for i, block in enumerate(blocks):
        # 截断过长的文本
        text = block.text[:200] + "..." if len(block.text) > 200 else block.text
        lines.append(f"{i+1}. {text}")
    
    lines.append("")
    lines.append("只输出分类字母（A/B/C），每行一个：")
    
    return "\n".join(lines)


def _parse_classify_output(output: str, expected_count: int) -> list[str]:
    """解析 LLM 分类输出"""
    # 过滤警告信息
    lines = output.split("\n")
    clean_lines = []
    for line in lines:
        if "Config warnings" in line or "duplicate plugin" in line:
            continue
        clean_lines.append(line.strip())
    
    # 提取分类字母
    results = []
    for line in clean_lines:
        line = line.strip().upper()
        if line in ["A", "B", "C"]:
            results.append(line)
        elif line.startswith(("A", "B", "C")):
            # 处理 "A."、"A、"等格式
            results.append(line[0])
    
    # 补齐数量
    while len(results) < expected_count:
        results.append("A")  # 默认为 A
    
    return results[:expected_count]


def category_from_str(s: str):
    """从字符串获取 TranslateCategory"""
    mapping = {
        "A": TranslateCategory.PARAGRAPH,
        "B": TranslateCategory.CARD,
        "C": TranslateCategory.SKIP,
        "PARAGRAPH": TranslateCategory.PARAGRAPH,
        "CARD": TranslateCategory.CARD,
        "SKIP": TranslateCategory.SKIP,
    }
    return mapping.get(s.upper(), TranslateCategory.PARAGRAPH)
