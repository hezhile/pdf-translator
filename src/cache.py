"""翻译缓存模块 - 使用 SQLite"""

import aiosqlite
import hashlib
import os
import json
from datetime import datetime


DB_PATH = os.path.expanduser("~/.openclaw/pdf_translator_cache.db")


def _make_key(text: str, source_lang: str, target_lang: str) -> str:
    """生成缓存键"""
    raw = f"{text.strip()}|{source_lang}|{target_lang}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def init_cache():
    """
    初始化缓存数据库。创建表（如果不存在）。

    表结构：
    CREATE TABLE IF NOT EXISTS translations (
        key TEXT PRIMARY KEY,
        original TEXT NOT NULL,
        translated TEXT NOT NULL,
        source_lang TEXT NOT NULL,
        target_lang TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """
    # 确保目录存在
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS translations (
                key TEXT PRIMARY KEY,
                original TEXT NOT NULL,
                translated TEXT NOT NULL,
                source_lang TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await db.commit()


async def get_cached(text: str, source_lang: str, target_lang: str) -> str | None:
    """查询缓存，命中返回翻译结果，未命中返回 None"""
    key = _make_key(text, source_lang, target_lang)

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT translated FROM translations WHERE key = ?",
                (key,)
            )
            row = await cursor.fetchone()
            if row:
                return row[0]
            return None
    except Exception as e:
        # 如果数据库损坏，打印警告并返回 None
        print(f"⚠️  缓存读取失败: {e}")
        return None


async def set_cached(text: str, translated: str, source_lang: str, target_lang: str):
    """写入缓存"""
    key = _make_key(text, source_lang, target_lang)
    created_at = datetime.now().isoformat()

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO translations
                (key, original, translated, source_lang, target_lang, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key, text, translated, source_lang, target_lang, created_at)
            )
            await db.commit()
    except Exception as e:
        print(f"⚠️  缓存写入失败: {e}")


async def get_cache_stats() -> dict:
    """返回缓存统计信息：总条数、数据库大小"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM translations")
            row = await cursor.fetchone()
            count = row[0] if row else 0

        # 获取数据库文件大小
        db_size = 0
        if os.path.exists(DB_PATH):
            db_size = os.path.getsize(DB_PATH)

        return {
            "total_entries": count,
            "db_size_bytes": db_size,
            "db_path": DB_PATH,
        }
    except Exception as e:
        print(f"⚠️  获取缓存统计失败: {e}")
        return {
            "total_entries": 0,
            "db_size_bytes": 0,
            "db_path": DB_PATH,
            "error": str(e),
        }


async def clear_cache():
    """清空缓存"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM translations")
            await db.commit()
        print("✅ 缓存已清空")
    except Exception as e:
        print(f"⚠️  清空缓存失败: {e}")


async def repair_cache():
    """修复损坏的缓存数据库"""
    try:
        # 删除旧数据库
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
            print("⚠️  已删除损坏的缓存数据库")

        # 重新初始化
        await init_cache()
        print("✅ 缓存数据库已重建")
    except Exception as e:
        print(f"❌ 修复缓存失败: {e}")
