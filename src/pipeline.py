"""大文件自动翻译管道"""

import asyncio

try:
    from .parser import extract_pdf
    from .builder import build_translated_pdf
    from .cache import init_cache, get_cached, set_cached
    from .llm_client import translate_via_openclaw
    from .classifier import classify_blocks, category_from_str
    from .models import PDFContent, TranslateMode, TranslateResult, BlockType, TranslateCategory
except ImportError:
    from parser import extract_pdf
    from builder import build_translated_pdf
    from cache import init_cache, get_cached, set_cached
    from llm_client import translate_via_openclaw
    from classifier import classify_blocks, category_from_str
    from models import PDFContent, TranslateMode, TranslateResult, BlockType, TranslateCategory


# 每批翻译的文本块数量
DEFAULT_BATCH_SIZE = 5

# 每批最大字符数
MAX_BATCH_CHARS = 3000


async def translate_pdf_pipeline(
    input_path: str,
    output_path: str | None = None,
    mode: str = "replace",
    source_lang: str = "en",
    target_lang: str = "zh-CN",
    glossary: dict[str, str] | None = None,
    pages: str = "all",
    gateway_url: str = "http://127.0.0.1:18789",
    batch_size: int = DEFAULT_BATCH_SIZE,
    on_progress: callable = None,
) -> TranslateResult:
    """
    大文件自动翻译管道。

    参数:
        input_path: 输入 PDF 路径
        output_path: 输出路径，默认为 {input}_zh.pdf
        mode: "replace" 或 "bilingual"
        source_lang: 源语言代码
        target_lang: 目标语言代码
        glossary: 术语表
        pages: 页码范围
        gateway_url: OpenClaw gateway 地址
        batch_size: 每批翻译的文本块数量
        on_progress: 进度回调函数 (current_page, total_pages, status_message)

    返回:
        TranslateResult
    """
    try:
        # 1. 初始化缓存
        if on_progress:
            on_progress(0, 0, "初始化缓存...")
        await init_cache()

        # 2. 提取 PDF 内容
        if on_progress:
            on_progress(0, 0, "提取 PDF 内容...")
        content = extract_pdf(input_path, pages)

        # 3. 获取所有可翻译的 blocks
        translatable = content.translatable_blocks

        if not translatable:
            return TranslateResult(
                status="error",
                error_message="未找到可翻译的文本块",
            )

        # 3.5 对文本块进行分类（A/B/C）
        if on_progress:
            on_progress(0, 0, f"分类 {len(translatable)} 个文本块...")
        
        categories = await classify_blocks(translatable, batch_size=50)
        
        # 更新 block 的 category 属性
        for block, cat in zip(translatable, categories):
            block.category = category_from_str(cat)
        
        # 统计分类结果
        cat_stats = {"A": 0, "B": 0, "C": 0}
        for cat in categories:
            cat_stats[cat] = cat_stats.get(cat, 0) + 1
        
        if on_progress:
            on_progress(0, 0, f"分类完成：A(正文){cat_stats['A']} B(卡片){cat_stats['B']} C(跳过){cat_stats['C']}")
        
        # 过滤掉 C 类（跳过）
        translatable = [b for b in translatable if b.category != TranslateCategory.SKIP]

        # 4. 将 blocks 分批
        batches = _split_into_batches(translatable, batch_size, MAX_BATCH_CHARS)

        if on_progress:
            on_progress(0, len(batches), f"准备翻译 {len(translatable)} 个文本块，分为 {len(batches)} 批")

        # 5. 对每一批进行翻译（按分类分开处理）
        total_chars = 0
        cached_chars = 0
        
        # 分离 A 类和 B 类
        paragraph_blocks = [b for b in translatable if b.category == TranslateCategory.PARAGRAPH]
        card_blocks = [b for b in translatable if b.category == TranslateCategory.CARD]
        
        # 5.1 翻译 A 类（正文段落）
        if paragraph_blocks:
            if on_progress:
                on_progress(0, len(paragraph_blocks) + len(card_blocks), f"翻译 {len(paragraph_blocks)} 个正文段落...")
            
            para_batches = _split_into_batches(paragraph_blocks, batch_size, MAX_BATCH_CHARS)
            for batch_idx, batch in enumerate(para_batches):
                if on_progress:
                    on_progress(batch_idx, len(para_batches) + len(card_blocks), f"翻译正文段落 {batch_idx + 1}/{len(para_batches)}...")
                
                uncached_blocks = []
                uncached_texts = []
                
                for block in batch:
                    cached = await get_cached(block.text, source_lang, target_lang)
                    if cached:
                        block.translated = cached
                        cached_chars += len(block.text)
                    else:
                        uncached_blocks.append(block)
                        uncached_texts.append(block.text)
                
                if uncached_texts:
                    try:
                        translations = await translate_via_openclaw(
                            uncached_texts,
                            source_lang,
                            target_lang,
                            glossary,
                            gateway_url,
                            category="paragraph",  # A 类翻译
                        )
                        
                        for block, translation in zip(uncached_blocks, translations):
                            block.translated = translation
                            await set_cached(block.text, translation, source_lang, target_lang)
                            total_chars += len(block.text)
                    
                    except Exception as e:
                        return TranslateResult(
                            status="error",
                            error_message=f"翻译正文失败: {e}",
                        )
        
        # 5.2 翻译 B 类（信息卡片）
        if card_blocks:
            if on_progress:
                on_progress(len(paragraph_blocks), len(paragraph_blocks) + len(card_blocks), f"翻译 {len(card_blocks)} 个信息卡片...")
            
            card_batches = _split_into_batches(card_blocks, batch_size, MAX_BATCH_CHARS)
            for batch_idx, batch in enumerate(card_batches):
                if on_progress:
                    on_progress(len(paragraph_blocks) + batch_idx, len(paragraph_blocks) + len(card_blocks), f"翻译信息卡片 {batch_idx + 1}/{len(card_batches)}...")
                
                uncached_blocks = []
                uncached_texts = []
                
                for block in batch:
                    cached = await get_cached(block.text, source_lang, target_lang)
                    if cached:
                        block.translated = cached
                        cached_chars += len(block.text)
                    else:
                        uncached_blocks.append(block)
                        uncached_texts.append(block.text)
                
                if uncached_texts:
                    try:
                        translations = await translate_via_openclaw(
                            uncached_texts,
                            source_lang,
                            target_lang,
                            glossary,
                            gateway_url,
                            category="card",  # B 类翻译
                        )
                        
                        for block, translation in zip(uncached_blocks, translations):
                            block.translated = translation
                            await set_cached(block.text, translation, source_lang, target_lang)
                            total_chars += len(block.text)
                    
                    except Exception as e:
                        return TranslateResult(
                            status="error",
                            error_message=f"翻译卡片失败: {e}",
                        )

        # 6. 生成输出文件
        if output_path is None:
            import os
            base, ext = os.path.splitext(input_path)
            output_path = f"{base}_zh{ext}"

        if on_progress:
            on_progress(len(batches), len(batches), "生成翻译后的 PDF...")

        # 确定翻译模式
        translate_mode = TranslateMode.BILINGUAL if mode == "bilingual" else TranslateMode.REPLACE

        # 重建 PDF
        build_translated_pdf(content, output_path, translate_mode)

        # 7. 返回结果
        return TranslateResult(
            status="success",
            output_path=output_path,
            pages_translated=len(content.pages),
            total_chars=total_chars + cached_chars,
            cached_chars=cached_chars,
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return TranslateResult(
            status="error",
            error_message=str(e),
        )


def _split_into_batches(
    blocks: list,
    batch_size: int,
    max_chars: int,
) -> list[list]:
    """
    将 blocks 分批。

    规则：
    - 每批最多 batch_size 个块
    - 每批总字符数不超过 max_chars
    - 两个条件满足其一就切分
    """
    if not blocks:
        return []

    batches = []
    current_batch = []
    current_chars = 0

    for block in blocks:
        block_chars = len(block.text)

        # 检查是否需要切分
        if len(current_batch) >= batch_size or current_chars + block_chars > max_chars:
            # 当前批次已满，开始新批次
            if current_batch:
                batches.append(current_batch)
            current_batch = []
            current_chars = 0

        # 添加到当前批次
        current_batch.append(block)
        current_chars += block_chars

    # 添加最后一个批次
    if current_batch:
        batches.append(current_batch)

    return batches
