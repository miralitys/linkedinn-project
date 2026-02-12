#!/usr/bin/env python3
"""
Миграция таблицы users: добавление колонок plan_name, approval_status (если нет).
Запуск: из корня проекта с DATABASE_URL на Supabase в .env

  python -m scripts.migrate_users_schema
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


async def main():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    url = os.environ.get("DATABASE_URL", "").strip().strip('"').strip("'")
    if not url or "sqlite" in url.lower():
        print("Задайте DATABASE_URL (Supabase) в .env")
        sys.exit(1)

    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        for sql in (
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS approval_status VARCHAR(16) DEFAULT 'approved'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_name VARCHAR(32)",
        ):
            try:
                await conn.execute(text(sql))
                print(f"OK: {sql[:60]}...")
            except Exception as e:
                print(f"Ошибка: {e}")
    await engine.dispose()
    print("Миграция users завершена.")


if __name__ == "__main__":
    asyncio.run(main())
