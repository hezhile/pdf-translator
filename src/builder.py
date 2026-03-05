"""PDF 重建模块"""

import fitz
import os

try:
    from .models import PDFContent, TextBlock, TranslateMode, BlockType
except ImportError:
    from models import PDFContent, TextBlock, TranslateMode, BlockType


# 中文字体路径
FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")
CHINESE_FONT_PATH = os.path.join(FONT_DIR, "NotoSansSC-Regular.ttf")


def _is_inside_image(bbox: tuple, image_rects: list) -> bool:
    """
    检查 bbox 是否完全在某个图片区域内。
    """
    x0, y0, x1, y1 = bbox
    
    for img_rect in image_rects:
        ix0, iy0, ix1, iy1 = img_rect
        # 检查 bbox 是否完全在图片内
        if x0 >= ix0 and y0 >= iy0 and x1 <= ix1 and y1 <= iy1:
            return True
    return False


def _get_image_rects(page: fitz.Page) -> list:
    """获取页面上所有图片的矩形区域"""
    image_rects = []
    images = page.get_images()
    for img in images:
        xref = img[0]
        rects = page.get_image_rects(xref)
        image_rects.extend(rects)
    return image_rects


def _subtract_image_from_bbox(bbox: tuple, image_rects: list) -> list:
    """
    从 bbox 中减去图片区域，返回不与图片重叠的矩形列表。
    
    简单策略：如果与图片重叠，将 bbox 分割为左右两部分或上下两部分。
    """
    x0, y0, x1, y1 = bbox
    
    for img_rect in image_rects:
        ix0, iy0, ix1, iy1 = img_rect
        
        # 检查是否重叠
        if not (x1 < ix0 or x0 > ix1 or y1 < iy0 or y0 > iy1):
            # 有重叠，尝试分割
            # 策略1：如果图片在左侧，保留右侧
            if ix1 < x1:  # 图片右边还有空间
                return [(ix1 + 2, y0, x1, y1)]
            # 策略2：如果图片在右侧，保留左侧
            if ix0 > x0:  # 图片左边还有空间
                return [(x0, y0, ix0 - 2, y1)]
            # 策略3：如果图片在上方，保留下方
            if iy1 < y1:
                return [(x0, iy1 + 2, x1, y1)]
            # 策略4：如果图片在下方，保留上方
            if iy0 > y0:
                return [(x0, y0, x1, iy0 - 2)]
            # 完全被图片覆盖，返回空
            return []
    
    # 无重叠，返回原 bbox
    return [bbox]


def _merge_overlapping_bboxes(blocks: list) -> list[dict]:
    """
    合并重叠的 bbox，返回合并后的区域列表。
    
    返回格式: [{"bbox": (x0,y0,x1,y1), "blocks": [block1, block2, ...]}, ...]
    """
    if not blocks:
        return []
    
    # 按 y0 坐标排序
    sorted_blocks = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
    
    merged = []
    
    for block in sorted_blocks:
        bbox = block.bbox
        
        # 检查是否与已有区域重叠
        merged_into = False
        for region in merged:
            region_bbox = region["bbox"]
            
            # 检查两个 bbox 是否重叠（y轴上有交集且x轴上有交集）
            if _bboxes_overlap(bbox, region_bbox):
                # 合并到该区域
                region["blocks"].append(block)
                # 更新区域 bbox（取并集）
                region["bbox"] = (
                    min(region_bbox[0], bbox[0]),
                    min(region_bbox[1], bbox[1]),
                    max(region_bbox[2], bbox[2]),
                    max(region_bbox[3], bbox[3]),
                )
                merged_into = True
                break
        
        if not merged_into:
            # 创建新区域
            merged.append({
                "bbox": bbox,
                "blocks": [block],
            })
    
    return merged


def _bboxes_overlap(bbox1: tuple, bbox2: tuple) -> bool:
    """
    检查两个 bbox 是否重叠。
    允许一定的边距误差（5像素）。
    """
    margin = 5
    
    x0_1, y0_1, x1_1, y1_1 = bbox1
    x0_2, y0_2, x1_2, y1_2 = bbox2
    
    # 检查 x 轴是否有交集
    x_overlap = not (x1_1 + margin < x0_2 or x1_2 + margin < x0_1)
    # 检查 y 轴是否有交集
    y_overlap = not (y1_1 + margin < y0_2 or y1_2 + margin < y0_1)
    
    return x_overlap and y_overlap


def build_translated_pdf(
    content: PDFContent,
    output_path: str,
    mode: TranslateMode = TranslateMode.REPLACE,
) -> str:
    """
    根据翻译结果生成新的 PDF。

    参数:
        content: 包含翻译结果的 PDFContent（每个 TextBlock.translated 已填充）
        output_path: 输出文件路径
        mode: REPLACE（替换）或 BILINGUAL（双语对照）

    返回:
        输出文件路径
    """
    # 打开原始 PDF
    doc = fitz.open(content.file_path)

    # 注册中文字体
    font_name = _register_chinese_font(doc)

    # 确保输出目录存在
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # 遍历每一页
    for page_content in content.pages:
        page = doc[page_content.page_num]

        # REPLACE 模式：先收集所有需要 redact 的区域，再一次性应用
        if mode == TranslateMode.REPLACE:
            redact_blocks = []
            
            # 获取页面上的所有图片区域
            image_rects = _get_image_rects(page)
            
            # 第一轮：收集需要处理的块
            for block in page_content.blocks:
                if block.block_type in (BlockType.IMAGE, BlockType.FORMULA):
                    continue
                if not block.translated:
                    continue
                redact_blocks.append(block)
            
            # 合并重叠的 bbox
            merged_regions = _merge_overlapping_bboxes(redact_blocks)
            
            # 过滤掉与图片重叠的区域，或调整区域
            safe_regions = []
            protected_count = 0
            for region in merged_regions:
                # 检查该区域是否完全在图片内
                if _is_inside_image(region["bbox"], image_rects):
                    # 区域完全在图片内，跳过 redact，但保留翻译
                    protected_count += 1
                    safe_regions.append({
                        "bbox": region["bbox"],
                        "blocks": region["blocks"],
                        "skip_redact": True,  # 标记不进行 redact
                    })
                    continue
                
                # 检查是否与图片重叠，如果重叠则调整区域
                adjusted_bboxes = _subtract_image_from_bbox(region["bbox"], image_rects)
                for adjusted_bbox in adjusted_bboxes:
                    safe_regions.append({
                        "bbox": adjusted_bbox,
                        "blocks": region["blocks"],
                        "skip_redact": False,
                    })
            
            if protected_count > 0:
                print(f"  ⚠️  第{page_content.page_num + 1}页: 保护了 {protected_count} 个图片区域（跳过redact）")
            
            # 添加所有 redaction 标记（只处理不与图片重叠的区域）
            for region in safe_regions:
                if not region.get("skip_redact", False):
                    page.add_redact_annot(region["bbox"], fill=(1, 1, 1))
            
            # 一次性应用所有 redactions
            if safe_regions:
                page.apply_redactions()
            
            # 第二轮：插入所有译文
            for region in safe_regions:
                # 合并该区域内所有块的翻译文本
                combined_text = "\n".join(b.translated for b in region["blocks"])
                
                font_size = _fit_text_in_bbox(
                    page,
                    region["bbox"],
                    combined_text,
                    font_name,
                    region["blocks"][0].font_size,
                )
                
                page.insert_textbox(
                    region["bbox"],
                    combined_text,
                    fontname=font_name,
                    fontsize=font_size,
                    color=(0, 0, 0),
                    align=0,
                )

        # BILINGUAL 模式
        else:
            for block in page_content.blocks:
                if block.block_type in (BlockType.IMAGE, BlockType.FORMULA):
                    continue
                if not block.translated:
                    continue
                
                bbox = block.bbox
                
                # 计算新 bbox（在原文下方）
                original_height = bbox[3] - bbox[1]
                new_y0 = bbox[3] + 2
                new_y1 = new_y0 + original_height * 0.75
                new_bbox = (bbox[0], new_y0, bbox[2], new_y1)

                font_size = block.font_size * 0.75
                font_size = _fit_text_in_bbox(
                    page,
                    new_bbox,
                    block.translated,
                    font_name,
                    font_size,
                )

                # 插入翻译文本（灰色）
                page.insert_textbox(
                    new_bbox,
                    block.translated,
                    fontname=font_name,
                    fontsize=font_size,
                    color=(0.4, 0.4, 0.4),
                    align=0,
                )

    # 保存（使用压缩选项，避免 redaction 后文件变大）
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()

    return output_path


def _register_chinese_font(doc: fitz.Document) -> str:
    """
    注册中文字体，返回字体名称。
    """
    if os.path.exists(CHINESE_FONT_PATH):
        try:
            font_name = "NotoSansSC"
            # 读取字体并将其作为字节流嵌入当前文档
            with open(CHINESE_FONT_PATH, "rb") as f:
                font_buffer = f.read()
            doc.insert_font(fontname=font_name, fontbuffer=font_buffer)
            print(f"✅ 已注册自定义字体: {font_name} (从 {CHINESE_FONT_PATH})")
            return font_name
        except Exception as e:
            print(f"⚠️  注册自定义字体失败: {e}，回退使用内建字体")

    print(f"⚠️  中文字体文件不存在: {CHINESE_FONT_PATH}")
    print("   使用 PyMuPDF 内建的 china-s 字体")
    return "china-s"


def _fit_text_in_bbox(
    page: fitz.Page,
    bbox: tuple,
    text: str,
    font_name: str,
    max_font_size: float,
    min_font_size: float = 6.0,
) -> float:
    """
    找到能将文本放入 bbox 的最大字号。优化版：复用临时文档以提升性能。
    """
    bbox_width = bbox[2] - bbox[0]
    bbox_height = bbox[3] - bbox[1]

    font_size = max_font_size

    # 优化：在循环外部创建一个临时文档，    test_doc = fitz.open()
    test_page = test_doc.new_page(width=bbox_width + 100, height=bbox_height + 100)
    test_bbox = (50, 50, 50 + bbox_width, 50 + bbox_height)

    try:
        while font_size >= min_font_size:
            # 执行纯净测试
            rc = test_page.insert_textbox(
                test_bbox,
                text,
                fontname=font_name,
                fontsize=font_size,
                color=(0, 0, 0),
            )

            # rc > 0 表示成功放下了
            if rc > 0:
                return font_size

            font_size -= 0.5  # 步长改为0.5，获取更精确的排版
    finally:
        # 无论如何确保关闭临时文档
        test_doc.close()

    return min_font_size
