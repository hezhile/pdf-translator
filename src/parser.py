"""PDF 解析模块"""

import fitz  # PyMuPDF
import pdfplumber
import re
from typing import Optional

try:
    from .models import TextBlock, PageContent, PDFContent, BlockType
except ImportError:
    from models import TextBlock, PageContent, PDFContent, BlockType


# 数学字体名称片段，命中则判定为公式
MATH_FONT_PATTERNS = ["CMMI", "CMSY", "CMEX", "Symbol", "Math", "MT Extra"]

# 数学符号的正则 - 匹配包含数学/希腊字母的模式
MATH_SYMBOL_PATTERN = re.compile(
    r'[\u2200-\u22FF\u2A00-\u2AFF\u0391-\u03C9∑∏∫∂∇±×÷√∞≈≠≤≥]'
)

# 最小有效文本长度
MIN_TEXT_LENGTH = 3


def extract_pdf(file_path: str, pages: str = "all") -> PDFContent:
    """
    提取 PDF 内容。

    参数:
        file_path: PDF 文件路径
        pages: 页码范围，"all" 或 "0-4,7,9"（从0开始）

    返回:
        PDFContent 对象
    """
    # 打开 PDF
    try:
        doc = fitz.open(file_path)
    except Exception as e:
        if "not a PDF" in str(e).lower() or "invalid" in str(e).lower():
            raise ValueError(f"Invalid PDF file: {file_path}") from e
        raise

    total_pages = len(doc)

    # 检查加密
    if doc.is_encrypted:
        doc.close()
        raise ValueError(f"PDF is encrypted: {file_path}")

    # 解析页码范围
    page_indices = _parse_page_range(pages, total_pages)

    # 用 pdfplumber 打开同一文件以识别表格
    plumber_pdf = pdfplumber.open(file_path)

    # 提取每一页
    pdf_content = PDFContent(
        file_path=file_path,
        total_pages=total_pages,
        metadata=doc.metadata or {},
    )

    for page_idx in page_indices:
        # 用 fitz 提取文本
        fitz_page = doc[page_idx]
        page_dict = fitz_page.get_text("dict")

        # 用 pdfplumber 识别表格区域
        plumber_page = plumber_pdf.pages[page_idx]
        tables = plumber_page.find_tables()
        table_bboxes = [table.bbox for table in tables] if tables else []

        # 创建 PageContent
        page_content = PageContent(
            page_num=page_idx,
            width=page_dict.get("width", 612.0),
            height=page_dict.get("height", 792.0),
        )

        # 提取文本块
        blocks = _extract_blocks_from_page(page_dict, page_idx, table_bboxes)
        page_content.blocks = blocks
        pdf_content.pages.append(page_content)

    doc.close()
    plumber_pdf.close()

    return pdf_content


def _parse_page_range(pages: str, total: int) -> list[int]:
    """
    解析页码范围字符串。

    "all" → [0, 1, 2, ..., total-1]
    "0-4,7,9" → [0, 1, 2, 3, 4, 7, 9]
    """
    if pages == "all":
        return list(range(total))

    result = []
    parts = pages.split(",")

    for part in parts:
        part = part.strip()
        if "-" in part:
            # 范围
            start_str, end_str = part.split("-", 1)
            start = int(start_str.strip())
            end = int(end_str.strip())
            result.extend(range(start, end + 1))
        else:
            # 单个页码
            result.append(int(part))

    # 过滤掉超出范围的页码
    result = [p for p in result if 0 <= p < total]

    return result


def _is_math_font(font_name: str) -> bool:
    """判断字体是否为数学字体"""
    if not font_name:
        return False
    font_lower = font_name.lower()
    return any(p.lower() in font_lower for p in MATH_FONT_PATTERNS)


def _has_math_symbols(text: str) -> bool:
    """判断文本是否包含大量数学符号"""
    if not text:
        return False
    match = MATH_SYMBOL_PATTERN.search(text)
    return match is not None


def _is_in_table(bbox: tuple, table_bboxes: list) -> bool:
    """判断 bbox 是否在表格区域内"""
    if not table_bboxes:
        return False

    x0, y0, x1, y1 = bbox

    for table_bbox in table_bboxes:
        tx0, ty0, tx1, ty1 = table_bbox
        # 如果文本块中心点在表格内，则认为属于表格
        center_x = (x0 + x1) / 2
        center_y = (y0 + y1) / 2

        if tx0 <= center_x <= tx1 and ty0 <= center_y <= ty1:
            return True

    return False


def _extract_blocks_from_page(
    page_dict: dict,
    page_num: int,
    table_bboxes: list
) -> list[TextBlock]:
    """
    从页面字典中提取文本块。

    步骤：
    1. 遍历 blocks → lines → spans
    2. 合并相邻的 span
    3. 过滤短文本
    4. 标记公式和表格
    """
    blocks = []

    for block in page_dict.get("blocks", []):
        # 只处理文本块（type 0）
        if block.get("type", 0) != 0:
            continue

        # 收集这个 block 中的所有 span
        spans_data = []

        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue

                bbox = span.get("bbox", (0, 0, 0, 0))
                font_name = span.get("font", "")
                font_size = span.get("size", 12.0)
                flags = span.get("flags", 0)
                is_bold = bool(flags & 16)  # PDF bold flag

                spans_data.append({
                    "text": text,
                    "bbox": bbox,
                    "font_name": font_name,
                    "font_size": font_size,
                    "is_bold": is_bold,
                })

        # 合并相邻的 span
        merged_blocks = _merge_spans(spans_data, page_dict.get("height", 792.0))

        # 标记公式和表格，过滤短文本
        for block_data in merged_blocks:
            text = block_data["text"]

            # 过滤短文本
            if len(text) < MIN_TEXT_LENGTH:
                continue

            # 判断是否为公式
            block_type = BlockType.TEXT
            if _is_math_font(block_data["font_name"]) or _has_math_symbols(text):
                block_type = BlockType.FORMULA
            # 判断是否在表格内
            elif _is_in_table(block_data["bbox"], table_bboxes):
                block_type = BlockType.TABLE

            text_block = TextBlock(
                page_num=page_num,
                bbox=block_data["bbox"],
                text=text,
                font_name=block_data["font_name"],
                font_size=block_data["font_size"],
                is_bold=block_data["is_bold"],
                block_type=block_type,
            )

            blocks.append(text_block)

    return blocks


def _merge_spans(spans: list[dict], page_height: float) -> list[dict]:
    """
    合并同一段落的碎片 span 为完整的文本块。

    合并规则：
    - 相邻 span 的 y 坐标差 < 行高的 0.5 倍
    - 字体名称和字号相同
    - 合并后 bbox 取并集
    """
    if not spans:
        return []

    # 按 y 坐标排序
    sorted_spans = sorted(spans, key=lambda s: (s["bbox"][1], s["bbox"][0]))

    merged = []
    current = None

    for span in sorted_spans:
        if current is None:
            current = span.copy()
            continue

        # 检查是否可以合并
        curr_y0 = current["bbox"][1]
        curr_y1 = current["bbox"][3]
        span_y0 = span["bbox"][1]
        span_y1 = span["bbox"][3]

        # 计算行高（使用当前块的高度）
        line_height = curr_y1 - curr_y0
        threshold = line_height * 0.5

        # y 坐标接近且字体相同
        y_close = abs(span_y0 - curr_y0) < threshold or abs(span_y1 - curr_y1) < threshold
        same_font = current["font_name"] == span["font_name"] and abs(current["font_size"] - span["font_size"]) < 0.5

        if y_close and same_font:
            # 合并
            current["text"] += " " + span["text"]
            # 更新 bbox（取并集）
            curr_bbox = current["bbox"]
            span_bbox = span["bbox"]
            current["bbox"] = (
                min(curr_bbox[0], span_bbox[0]),
                min(curr_bbox[1], span_bbox[1]),
                max(curr_bbox[2], span_bbox[2]),
                max(curr_bbox[3], span_bbox[3]),
            )
        else:
            # 保存当前块，开始新块
            merged.append(current)
            current = span.copy()

    # 添加最后一个块
    if current:
        merged.append(current)

    return merged
