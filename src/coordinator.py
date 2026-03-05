#!/usr/bin/env python3
"""
翻译协调器 - 提取文本块并生成翻译任务

这个脚本只负责：
1. 提取 PDF 文本块
2. 生成翻译任务文件
3. 等待 main agent 用 sessions_spawn 翻译
4. 重建 PDF

不直接调用 LLM，由 main agent 协调。
"""

import json
import os
import time
import sys

# 添加 src 到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import extract_pdf
from builder import build_translated_pdf
from cache import init_cache, get_cached, set_cached
from classifier import classify_blocks, category_from_str, _is_skip_by_pattern
from models import TranslateMode


# 任务队列目录
QUEUE_DIR = os.path.expanduser("~/.openclaw/pdf_translate_queue")
os.makedirs(QUEUE_DIR, exist_ok=True)


def prepare_translation_tasks(
    input_path: str,
    output_path: str | None = None,
    mode: str = "replace",
    batch_size: int = 5,
) -> dict:
    """
    准备翻译任务。
    
    返回:
        {
            "status": "prepared",
            "task_file": "任务文件路径",
            "total_blocks": 总块数,
            "batches": 批次数,
            "output_path": "输出文件路径"
        }
    """
    print(f"[1/4] 提取 PDF 内容...")
    content = extract_pdf(input_path)
    
    print(f"[2/4] 分类 {len(content.translatable_blocks)} 个文本块...")
    
    # 本地规则预过滤
    blocks_to_translate = []
    for block in content.translatable_blocks:
        if _is_skip_by_pattern(block.text):
            continue
        blocks_to_translate.append(block)
    
    print(f"   跳过 {len(content.translatable_blocks) - len(blocks_to_translate)} 个块（C类）")
    
    # 检查缓存
    print(f"[3/4] 检查缓存...")
    import asyncio
    asyncio.run(init_cache())
    
    uncached_blocks = []
    for block in blocks_to_translate:
        cached = asyncio.run(get_cached(block.text, "en", "zh-CN"))
        if cached:
            block.translated = cached
        else:
            uncached_blocks.append(block)
    
    print(f"   缓存命中: {len(blocks_to_translate) - len(uncached_blocks)} 个")
    print(f"   需要翻译: {len(uncached_blocks)} 个")
    
    if not uncached_blocks:
        # 全部命中缓存，直接生成 PDF
        print(f"[4/4] 全部命中缓存，生成 PDF...")
        if output_path is None:
            base, ext = os.path.splitext(input_path)
            output_path = f"{base}_zh{ext}"
        
        translate_mode = TranslateMode.BILINGUAL if mode == "bilingual" else TranslateMode.REPLACE
        build_translated_pdf(content, output_path, translate_mode)
        
        return {
            "status": "completed",
            "output_path": output_path,
            "cached": True,
        }
    
    # 分批
    batches = []
    for i in range(0, len(uncached_blocks), batch_size):
        batches.append(uncached_blocks[i:i+batch_size])
    
    # 生成任务文件
    task_id = f"translate-{int(time.time())}"
    task_file = os.path.join(QUEUE_DIR, f"{task_id}.json")
    
    task_data = {
        "task_id": task_id,
        "input_path": input_path,
        "output_path": output_path or f"{os.path.splitext(input_path)[0]}_zh.pdf",
        "mode": mode,
        "batches": [
            {
                "batch_idx": i,
                "texts": [b.text for b in batch],
            }
            for i, batch in enumerate(batches)
        ],
        "results": {},
        "status": "pending",
    }
    
    # 保存内容对象（用于后续重建）
    content_file = os.path.join(QUEUE_DIR, f"{task_id}_content.json")
    
    # 序列化 content（简化版）
    content_data = {
        "file_path": content.file_path,
        "total_pages": content.total_pages,
        "pages": [
            {
                "page_num": p.page_num,
                "width": p.width,
                "height": p.height,
                "blocks": [
                    {
                        "page_num": b.page_num,
                        "bbox": list(b.bbox),
                        "text": b.text,
                        "font_name": b.font_name,
                        "font_size": b.font_size,
                        "is_bold": b.is_bold,
                        "block_type": b.block_type.value if hasattr(b.block_type, 'value') else b.block_type,
                        "translated": b.translated,
                    }
                    for b in p.blocks
                ]
            }
            for p in content.pages
        ]
    }
    
    with open(task_file, "w") as f:
        json.dump(task_data, f, indent=2)
    
    with open(content_file, "w") as f:
        json.dump(content_data, f, indent=2)
    
    print(f"[4/4] 已生成翻译任务:")
    print(f"   任务 ID: {task_id}")
    print(f"   任务文件: {task_file}")
    print(f"   批次数: {len(batches)}")
    print(f"   输出路径: {task_data['output_path']}")
    print()
    print("=" * 60)
    print("请 main agent 用 sessions_spawn 翻译每个批次")
    print("=" * 60)
    
    return {
        "status": "prepared",
        "task_id": task_id,
        "task_file": task_file,
        "content_file": content_file,
        "total_blocks": len(uncached_blocks),
        "batches": len(batches),
        "output_path": task_data["output_path"],
    }


def apply_translations_and_build(
    task_id: str,
    translations: dict[int, list[str]],
) -> dict:
    """
    应用翻译结果并重建 PDF。
    
    参数:
        task_id: 任务 ID
        translations: {batch_idx: [翻译结果列表]}
    """
    task_file = os.path.join(QUEUE_DIR, f"{task_id}.json")
    content_file = os.path.join(QUEUE_DIR, f"{task_id}_content.json")
    
    with open(task_file) as f:
        task_data = json.load(f)
    
    with open(content_file) as f:
        content_data = json.load(f)
    
    # 重建 content 对象
    from models import PDFContent, PageContent, TextBlock, BlockType
    
    content = PDFContent(
        file_path=content_data["file_path"],
        total_pages=content_data["total_pages"],
    )
    
    for p_data in content_data["pages"]:
        page = PageContent(
            page_num=p_data["page_num"],
            width=p_data["width"],
            height=p_data["height"],
        )
        for b_data in p_data["blocks"]:
            block = TextBlock(
                page_num=b_data["page_num"],
                bbox=tuple(b_data["bbox"]),
                text=b_data["text"],
                font_name=b_data["font_name"],
                font_size=b_data["font_size"],
                is_bold=b_data["is_bold"],
                block_type=BlockType(b_data["block_type"]),
                translated=b_data["translated"],
            )
            page.blocks.append(block)
        content.pages.append(page)
    
    # 应用翻译结果
    for batch_idx, batch_translations in translations.items():
        batch = task_data["batches"][batch_idx]
        for i, text in enumerate(batch["texts"]):
            if i < len(batch_translations):
                # 找到对应的 block 并设置翻译
                for page in content.pages:
                    for block in page.blocks:
                        if block.text == text and not block.translated:
                            block.translated = batch_translations[i]
                            # 写入缓存
                            import asyncio
                            asyncio.run(set_cached(text, batch_translations[i], "en", "zh-CN"))
                            break
    
    # 重建 PDF
    output_path = task_data["output_path"]
    translate_mode = TranslateMode.BILINGUAL if task_data["mode"] == "bilingual" else TranslateMode.REPLACE
    
    print(f"重建 PDF: {output_path}")
    build_translated_pdf(content, output_path, translate_mode)
    
    # 清理任务文件
    os.remove(task_file)
    os.remove(content_file)
    
    return {
        "status": "completed",
        "output_path": output_path,
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("用法:")
        print("  python coordinator.py <pdf_path> [batch_size]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    batch_size = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    
    result = prepare_translation_tasks(pdf_path, batch_size=batch_size)
    print(json.dumps(result, indent=2))
