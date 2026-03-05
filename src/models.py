"""数据结构定义"""

from dataclasses import dataclass, field
from enum import Enum


class BlockType(Enum):
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    FORMULA = "formula"


class TranslateCategory(Enum):
    """文本块的翻译分类"""
    PARAGRAPH = "paragraph"    # A类：正文段落，需要合并同一行的span
    CARD = "card"              # B类：结构化信息卡片，逐行独立翻译
    SKIP = "skip"              # C类：跳过不翻译（arXiv、DOI、页码等）


class TranslateMode(Enum):
    REPLACE = "replace"       # 替换原文
    BILINGUAL = "bilingual"   # 双语对照


@dataclass
class TextBlock:
    """一个文本块"""
    page_num: int                                # 所在页码（从 0 开始）
    bbox: tuple[float, float, float, float]      # (x0, y0, x1, y1) 坐标
    text: str                                    # 原始文本内容
    font_name: str = ""                          # 字体名称
    font_size: float = 12.0                      # 字号
    is_bold: bool = False                        # 是否粗体
    block_type: BlockType = BlockType.TEXT        # 块类型
    category: TranslateCategory = None           # 翻译分类（A/B/C）
    translated: str = ""                         # 翻译后的文本（初始为空）


@dataclass
class PageContent:
    """一页的内容"""
    page_num: int
    width: float
    height: float
    blocks: list[TextBlock] = field(default_factory=list)


@dataclass
class PDFContent:
    """整个 PDF 的内容"""
    file_path: str
    total_pages: int
    pages: list[PageContent] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def total_chars(self) -> int:
        return sum(len(b.text) for p in self.pages for b in p.blocks)

    @property
    def translatable_blocks(self) -> list[TextBlock]:
        """返回所有需要翻译的文本块（排除图片和公式）"""
        return [
            b for p in self.pages for b in p.blocks
            if b.block_type in (BlockType.TEXT, BlockType.TABLE)
        ]


@dataclass
class TranslateResult:
    """翻译结果"""
    status: str                    # "success" | "error"
    output_path: str = ""
    pages_translated: int = 0
    total_chars: int = 0
    cached_chars: int = 0          # 命中缓存的字符数
    error_message: str = ""
