#!/usr/bin/env python3
"""Очистить все посты в разделе Комментарии (contact_posts) для всех пользователей."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete, func, select

from app.db import init_db, async_session_maker
from app.models import ContactPost


async def clear_all_posts():
    """Удаляет все записи из contact_posts."""
    await init_db()

    async with async_session_maker() as session:
        # Считаем до удаления
        r = await session.execute(select(func.count()).select_from(ContactPost))
        count = r.scalar() or 0

        if count == 0:
            print("Постов в разделе Комментарии нет, база уже пуста.")
            return

        await session.execute(delete(ContactPost))
        await session.commit()
        print(f"✓ Удалено постов: {count}")
        print("Раздел Комментарии очищен.")


if __name__ == "__main__":
    asyncio.run(clear_all_posts())
