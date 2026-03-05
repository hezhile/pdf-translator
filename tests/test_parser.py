"""测试 PDF 解析模块"""

import sys
import os

# 添加 src 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from parser import extract_pdf, _parse_page_range, _is_math_font, _has_math_symbols
from models import BlockType


def test_extract_basic():
    """测试基本提取功能"""
    pdf_path = "/home/openclaw/.openclaw/workspace/pdfs/welcome-kit.pdf"

    if not os.path.exists(pdf_path):
        print(f"❌ 测试PDF不存在: {pdf_path}")
        return False

    try:
        content = extract_pdf(pdf_path)
        print(f"✅ 提取成功:")
        print(f"  - 总页数: {content.total_pages}")
        print(f"  - 实际提取页数: {len(content.pages)}")
        print(f"  - 总字符数: {content.total_chars}")
        print(f"  - 元数据: {content.metadata}")

        # 验证 pages 不为空
        if len(content.pages) == 0:
            print("❌ 未提取到任何页面")
            return False

        # 验证有文本块
        total_blocks = sum(len(p.blocks) for p in content.pages)
        print(f"  - 总文本块数: {total_blocks}")

        if total_blocks == 0:
            print("❌ 未提取到任何文本块")
            return False

        # 显示前几个文本块示例
        print("\n示例文本块:")
        count = 0
        for page in content.pages[:2]:  # 前两页
            for block in page.blocks[:3]:  # 每页前3个块
                if count >= 5:
                    break
                print(f"  页{block.page_num}: [{block.block_type.value}] {block.text[:80]}...")
                count += 1
            if count >= 5:
                break

        return True

    except Exception as e:
        print(f"❌ 提取失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_extract_page_range():
    """测试页码范围提取"""
    pdf_path = "/home/openclaw/.openclaw/workspace/pdfs/welcome-kit.pdf"

    if not os.path.exists(pdf_path):
        print(f"❌ 测试PDF不存在: {pdf_path}")
        return False

    try:
        # 提取前两页
        content = extract_pdf(pdf_path, pages="0-1")
        print(f"✅ 页码范围测试 (0-1):")
        print(f"  - 提取页数: {len(content.pages)}")

        if len(content.pages) != 2:
            print(f"❌ 期望2页，实际{len(content.pages)}页")
            return False

        return True

    except Exception as e:
        print(f"❌ 页码范围测试失败: {e}")
        return False


def test_block_has_bbox():
    """测试每个文本块都有有效的 bbox"""
    pdf_path = "/home/openclaw/.openclaw/workspace/pdfs/welcome-kit.pdf"

    if not os.path.exists(pdf_path):
        print(f"❌ 测试PDF不存在: {pdf_path}")
        return False

    try:
        content = extract_pdf(pdf_path)

        for page in content.pages:
            for block in page.blocks:
                bbox = block.bbox
                # bbox 应该有4个正数
                if len(bbox) != 4:
                    print(f"❌ bbox 长度不为4: {bbox}")
                    return False

                x0, y0, x1, y1 = bbox
                if not (isinstance(x0, (int, float)) and
                        isinstance(y0, (int, float)) and
                        isinstance(x1, (int, float)) and
                        isinstance(y1, (int, float))):
                    print(f"❌ bbox 包含非数字: {bbox}")
                    return False

        print("✅ 所有文本块都有有效的 bbox")
        return True

    except Exception as e:
        print(f"❌ bbox 测试失败: {e}")
        return False


def test_formula_detection():
    """测试公式检测"""
    # 测试数学字体检测
    assert _is_math_font("CMMI12") == True
    assert _is_math_font("CMSY10") == True
    assert _is_math_font("Arial") == False
    assert _is_math_font("Times New Roman") == False

    # 测试数学符号检测
    assert _has_math_symbols("∑∏∫∂∇") == True
    # 注意：希腊字母在检测范围内
    assert _has_math_symbols("α + β = γ") == True
    assert _has_math_symbols("Hello World") == False

    print("✅ 公式检测测试通过")
    return True


def test_parse_page_range():
    """测试页码范围解析"""
    # "all" 情况
    result = _parse_page_range("all", 10)
    assert result == list(range(10)), f"期望 {list(range(10))}, 实际 {result}"

    # 单个页码
    result = _parse_page_range("5", 10)
    assert result == [5], f"期望 [5], 实际 {result}"

    # 范围
    result = _parse_page_range("0-4", 10)
    assert result == [0, 1, 2, 3, 4], f"期望 [0,1,2,3,4], 实际 {result}"

    # 混合
    result = _parse_page_range("0-2,5,7-8", 10)
    assert result == [0, 1, 2, 5, 7, 8], f"期望 [0,1,2,5,7,8], 实际 {result}"

    print("✅ 页码范围解析测试通过")
    return True


def main():
    """运行所有测试"""
    print("=" * 60)
    print("PDF 解析模块测试")
    print("=" * 60)

    tests = [
        ("test_parse_page_range", test_parse_page_range),
        ("test_formula_detection", test_formula_detection),
        ("test_extract_basic", test_extract_basic),
        ("test_extract_page_range", test_extract_page_range),
        ("test_block_has_bbox", test_block_has_bbox),
    ]

    results = []
    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ 测试异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n" + "=" * 60)
    print("测试结果汇总:")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {name}")

    print(f"\n总计: {passed}/{total} 通过")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
