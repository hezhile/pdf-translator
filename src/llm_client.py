"""LLM 翻译客户端 - 通过 OpenClaw Gateway HTTP API 调用

使用 OpenAI 兼容的 /v1/chat/completions 端点调用 Gateway 进行翻译。
"""

import httpx
import os
import json
from typing import Optional


# Gateway 配置
GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")

# 默认 token（从 openclaw.json 读取）
def _get_gateway_token() -> str:
    """获取 Gateway token"""
    if GATEWAY_TOKEN:
        return GATEWAY_TOKEN
    
    # 尝试从 openclaw.json 读取
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                # 移除注释（JSON5 格式）
                content = f.read()
                # 简单解析，提取 gateway.auth.token
                import re
                match = re.search(r'"token"\s*:\s*"([^"]+)"', content)
                if match:
                    return match.group(1)
        except Exception:
            pass
    
    # 默认 token（从 departures.md 记录的）
    return "071866236a45cde1b5246f99c66b11584f3800f60ac5b09a"


# 翻译 Prompt 模板
TRANSLATE_PROMPT_PARAGRAPH = """你是专业翻译。将以下英文翻译成中文。

规则：
1. 只输出翻译结果，不要解释
2. 人名、机构、品牌等名字：保留原文。例如：
   - Marc Hecker
   - French Institute of International Relations
   - Les Echos
3. 多个文本用 "|||" 分隔，保持顺序

文本：
{texts}

只输出翻译结果："""

TRANSLATE_PROMPT_CARD = """你是专业翻译。将以下英文信息卡片翻译成中文。

规则：
1. 每行独立翻译，不合并
2. 只输出翻译结果，不要解释
3. 人名、地名、品牌保留原文，括号标注中文
4. 多个卡片用 "|||" 分隔，保持顺序

卡片：
{texts}

只输出翻译结果："""


async def translate_via_openclaw(
    texts: list[str],
    source_lang: str = "en",
    target_lang: str = "zh-CN",
    glossary: dict[str, str] | None = None,
    gateway_url: str = "",
    category: str = "paragraph",
) -> list[str]:
    """
    通过 OpenClaw Gateway HTTP API 翻译文本。

    参数:
        texts: 要翻译的文本列表
        source_lang: 源语言（默认 en）
        target_lang: 目标语言（默认 zh-CN）
        glossary: 术语表（可选）
        gateway_url: Gateway 地址（默认 http://127.0.0.1:18789）
        category: 翻译类别（paragraph 或 card）

    返回:
        翻译结果列表
    """
    if not texts:
        return []

    # 使用传入的 gateway_url 或默认值
    base_url = gateway_url or GATEWAY_URL
    token = _get_gateway_token()

    # 构建 prompt
    combined_text = "|||".join(texts)
    
    if category == "card":
        prompt = TRANSLATE_PROMPT_CARD.format(texts=combined_text)
    else:
        prompt = TRANSLATE_PROMPT_PARAGRAPH.format(texts=combined_text)
    
    # 添加术语表
    if glossary:
        terms = "\n".join(f"- {k} → {v}" for k, v in glossary.items())
        prompt = f"术语表：\n{terms}\n\n" + prompt

    # 调用 Gateway
    url = f"{base_url}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-openclaw-agent-id": "main",
    }
    
    payload = {
        "model": "openclaw",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            
            # 解析翻译结果
            translations = content.split("|||")
            
            # 清理结果
            translations = [t.strip() for t in translations]
            
            # 确保数量匹配
            while len(translations) < len(texts):
                translations.append("")
            
            return translations[:len(texts)]

    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Gateway HTTP 错误: {e.response.status_code} - {e.response.text}")
    except httpx.RequestError as e:
        raise RuntimeError(f"Gateway 连接失败: {e}")
    except Exception as e:
        raise RuntimeError(f"翻译失败: {e}")


# 向后兼容的别名
async def translate_via_gateway(*args, **kwargs) -> list[str]:
    return await translate_via_openclaw(*args, **kwargs)


async def translate_via_subagent(*args, **kwargs) -> list[str]:
    return await translate_via_openclaw(*args, **kwargs)


async def translate_via_openrouter(*args, **kwargs) -> list[str]:
    return await translate_via_openclaw(*args, **kwargs)


async def test_openclaw_connection(gateway_url: str = "") -> bool:
    """测试 Gateway 连接"""
    base_url = gateway_url or GATEWAY_URL
    token = _get_gateway_token()
    
    url = f"{base_url}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-openclaw-agent-id": "main",
    }
    
    payload = {
        "model": "openclaw",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 10,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            print("✅ Gateway 连接正常")
            return True
    except Exception as e:
        print(f"❌ Gateway 连接失败: {e}")
        return False


if __name__ == "__main__":
    import asyncio
    
    async def test():
        # 测试连接
        print("测试 Gateway 连接...")
        await test_openclaw_connection()
        
        # 测试翻译
        print("\n测试翻译...")
        texts = ["Hello World", "This is a test"]
        result = await translate_via_openclaw(texts)
        print(f"原文: {texts}")
        print(f"译文: {result}")
    
    asyncio.run(test())
