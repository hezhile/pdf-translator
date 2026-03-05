# PDF Translator

PDF翻译工具，作为OpenClaw的Agent Tool使用。

## 功能

- 将英语或其他语言PDF翻译成中文
- 支持两种模式：
  - **替换模式**：用中文替换原文
  - **双语模式**：保留原文，在下方添加中文翻译
- 支持大文件自动分批翻译
- 翻译缓存，避免重复翻译

## 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 方法1：一键翻译（推荐）

```python
from tools import translate_pdf

result = translate_pdf(
    input_path="/path/to/file.pdf",
    mode="bilingual",
)

print(result)
```

### 方法2：Agent编排模式（小文件）

```python
from tools import extract_pdf_text, build_translated_pdf_tool

# 1. 提取文本
content = extract_pdf_text("/path/to/file.pdf")

# 2. 自己翻译（Agent完成）
translations = {
    "0": [
        {"original": "Hello", "translated": "你好"},
    ]
}

# 3. 写回PDF
result = build_translated_pdf_tool(
    original_path="/path/to/file.pdf",
    translations=translations,
    mode="replace",
)
```

## 测试

```bash
cd /home/openclaw/.openclaw/workspace/extensions/pdf-translator/src
python3 ../tests/test_parser.py
python3 ../tests/test_builder.py
```

## 注意事项

- 需要OpenClaw Gateway运行在 `http://127.0.0.1:18789`
- 中文字体：优先使用 `fonts/NotoSansSC-Regular.ttf`，否则使用PyMuPDF内建字体
