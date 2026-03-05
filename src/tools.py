"""
PDF 翻译工具 - OpenClaw Agent Tool 入口

提供三个工具函数：
1. extract_pdf_text - 提取 PDF 文本（Agent 编排模式用）
2. build_translated_pdf_tool - 将翻译写回 PDF（Agent 编排模式用）
3. translate_pdf - 一键翻译（Pipeline 管道模式用）
"""

import os
import asyncio

try:
    from .parser import extract_pdf
    from .builder import build_translated_pdf
    from .pipeline import translate_pdf_pipeline
    from .models import TranslateMode, TranslateResult
except ImportError:
    from parser import extract_pdf
    from builder import build_translated_pdf
    from pipeline import translate_pdf_pipeline
    from models import TranslateMode, TranslateResult


# ============================================================
# 工具 1: 提取 PDF 文本
# ============================================================

def extract_pdf_text(
    path: str,
    pages: str = "all",
) -> dict:
    """
    提取 PDF 的文本内容，返回结构化数据。

    参数:
        path: PDF 文件路径（绝对路径或相对路径）
        pages: 页码范围，"all" 表示全部，"0-4,7,9" 指定页（从0开始）

    返回:
        {
            "total_pages": 15,
            "total_chars": 28000,
            "pages": [
                {
                    "page_num": 0,
                    "blocks": [
                        {
                            "text": "Abstract. We propose a novel...",
                            "bbox": [72.0, 90.5, 540.0, 120.3],
                            "font_size": 10.0,
                            "is_bold": false,
                            "block_type": "text"
                        }
                    ]
                }
            ]
        }

    使用场景:
        Agent 调用此函数获取 PDF 内容，自己阅读并翻译，
        然后调用 build_translated_pdf_tool 写回。
        适合小文件（< 30 页）。
    """
    content = extract_pdf(path, pages)

    # 转为 dict 返回给 Agent
    return {
        "total_pages": content.total_pages,
        "total_chars": content.total_chars,
        "pages": [
            {
                "page_num": p.page_num,
                "blocks": [
                    {
                        "text": b.text,
                        "bbox": list(b.bbox),
                        "font_size": b.font_size,
                        "is_bold": b.is_bold,
                        "block_type": b.block_type.value,
                    }
                    for b in p.blocks
                ],
            }
            for p in content.pages
        ],
    }


# ============================================================
# 工具 2: 将翻译写回 PDF
# ============================================================

def build_translated_pdf_tool(
    original_path: str,
    translations: dict,
    output_path: str | None = None,
    mode: str = "replace",
) -> dict:
    """
    将翻译结果写回 PDF，生成新文件。

    参数:
        original_path: 原始 PDF 路径
        translations: 翻译数据，格式：
            {
                "0": [   # 页码（字符串）
                    {"original": "Abstract...", "translated": "摘要..."},
                    {"original": "We propose...", "translated": "我们提出..."}
                ],
                "1": [...]
            }
        output_path: 输出路径，默认为 {原文件名}_zh.pdf
        mode: "replace"（替换原文）或 "bilingual"（双语对照）

    返回:
        {"status": "success", "output_path": "/path/to/output.pdf"}
    """
    try:
        # 提取原始 PDF 内容
        content = extract_pdf(original_path)

        # 应用翻译
        for page_num_str, page_translations in translations.items():
            page_num = int(page_num_str)

            # 找到对应的页
            if page_num >= len(content.pages):
                continue

            page = content.pages[page_num]

            # 匹配翻译
            for trans_item in page_translations:
                original_text = trans_item.get("original", "")
                translated_text = trans_item.get("translated", "")

                if not original_text or not translated_text:
                    continue

                # 查找匹配的 block（简单匹配：文本相同）
                for block in page.blocks:
                    if block.text == original_text:
                        block.translated = translated_text
                        break

        # 确定输出路径
        if output_path is None:
            base, ext = os.path.splitext(original_path)
            output_path = f"{base}_zh{ext}"

        # 确定翻译模式
        translate_mode = TranslateMode.BILINGUAL if mode == "bilingual" else TranslateMode.REPLACE

        # 重建 PDF
        build_translated_pdf(content, output_path, translate_mode)

        return {
            "status": "success",
            "output_path": output_path,
        }

    except Exception as e:
        return {
            "status": "error",
            "error_message": str(e),
        }


# ============================================================
# 工具 3: 一键翻译（管道模式）
# ============================================================

def translate_pdf(
    input_path: str,
    output_path: str | None = None,
    mode: str = "replace",
    source_lang: str = "en",
    target_lang: str = "zh-CN",
    glossary: dict | None = None,
    pages: str = "all",
) -> dict:
    """
    一键翻译 PDF 文件。适合大文件。

    内部通过 OpenClaw gateway 回调 LLM 自动完成翻译，
    不需要任何外部 API Key。

    参数:
        input_path: 输入 PDF 文件路径
        output_path: 输出路径，默认 {原名}_zh.pdf
        mode: "replace" 替换原文 / "bilingual" 双语对照
        source_lang: 源语言（默认 "en"）
        target_lang: 目标语言（默认 "zh-CN"）
        glossary: 术语表，如 {"transformer": "Transformer模型", "attention": "注意力机制"}
        pages: 页码范围 "all" 或 "0-9,15"

    返回:
        {
            "status": "success",
            "output_path": "/path/to/translated.pdf",
            "pages_translated": 42,
            "total_chars": 85000,
            "cached_chars": 12000
        }

    示例：
        translate_pdf("/downloads/paper.pdf")
        translate_pdf("/downloads/paper.pdf", mode="bilingual", glossary={"LLM": "大语言模型"})
    """
    if output_path is None:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_zh{ext}"

    # 定义进度回调
    def progress_callback(current, total, message):
        if total > 0:
            percent = (current / total) * 100
            print(f"[{percent:.0f}%] {message}")
        else:
            print(message)

    result = asyncio.run(
        translate_pdf_pipeline(
            input_path=input_path,
            output_path=output_path,
            mode=mode,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary=glossary,
            pages=pages,
            on_progress=progress_callback,
        )
    )

    return {
        "status": result.status,
        "output_path": result.output_path,
        "pages_translated": result.pages_translated,
        "total_chars": result.total_chars,
        "cached_chars": result.cached_chars,
        "error_message": result.error_message,
    }


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print("  python tools.py <pdf_path> [output_path] [mode]")
        print()
        print("示例:")
        print("  python tools.py /path/to/file.pdf")
        print("  python tools.py /path/to/file.pdf /path/to/output.pdf bilingual")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    mode = sys.argv[3] if len(sys.argv) > 3 else "replace"

    print(f"翻译 PDF: {input_file}")
    print(f"输出路径: {output_file or '(自动生成)'}")
    print(f"模式: {mode}")
    print()

    result = translate_pdf(
        input_path=input_file,
        output_path=output_file,
        mode=mode,
    )

    print()
    print("翻译结果:")
    for key, value in result.items():
        print(f"  {key}: {value}")
