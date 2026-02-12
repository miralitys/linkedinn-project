#!/usr/bin/env python3
"""Полностью удалить из БД: компании, контакты, авторы, продукты, ICP, Reddit (saved_subreddits, reddit_posts)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete, func, select, text

from app.db import init_db, async_session_maker
from app.models import (
    Company,
    ContactPost,
    KnowledgeBase,
    Person,
    RedditPost,
    SavedSubreddit,
    Touch,
)


async def wipe_all_user_data():
    """Удаляет все данные: компании, контакты, посты, авторы, продукты, ICP, сабреддиты, reddit посты."""
    await init_db()

    async with async_session_maker() as session:
        counts = {}

        # 1. ContactPost (посты) — перед Person
        r = await session.execute(select(func.count()).select_from(ContactPost))
        counts["posts"] = r.scalar() or 0
        await session.execute(delete(ContactPost))

        # 2. Touch — перед Person
        r = await session.execute(select(func.count()).select_from(Touch))
        counts["touches"] = r.scalar() or 0
        await session.execute(delete(Touch))

        # 3. Person (контакты)
        r = await session.execute(select(func.count()).select_from(Person))
        counts["people"] = r.scalar() or 0
        await session.execute(delete(Person))

        # 4. Company (компании)
        r = await session.execute(select(func.count()).select_from(Company))
        counts["companies"] = r.scalar() or 0
        await session.execute(delete(Company))

        # 5. RedditPost
        r = await session.execute(select(func.count()).select_from(RedditPost))
        counts["reddit_posts"] = r.scalar() or 0
        await session.execute(delete(RedditPost))

        # 6. SavedSubreddit
        r = await session.execute(select(func.count()).select_from(SavedSubreddit))
        counts["saved_subreddits"] = r.scalar() or 0
        await session.execute(delete(SavedSubreddit))

        # 7. KnowledgeBase — авторы, продукты, ICP, tone, goals, saved_subreddits
        kb_keys = [
            "setup_authors", "authors",
            "setup_products", "products",
            "setup_icp_raw", "setup_tone", "setup_goals",
            "saved_subreddits",
        ]
        r = await session.execute(select(KnowledgeBase).where(True))
        all_rows = r.scalars().all()
        to_delete = []
        for row in all_rows:
            # Удалить если ключ точный или начинается с ключа:
            for k in kb_keys:
                if row.key == k or row.key.startswith(k + ":"):
                    to_delete.append(row)
                    break
        counts["knowledge_base"] = len(to_delete)
        for row in to_delete:
            await session.delete(row)

        await session.commit()
        print("✓ Удалено:")
        for k, v in counts.items():
            print(f"  {k}: {v}")
        print("\nГотово. Все данные очищены. Пользователи могут создавать заново.")


if __name__ == "__main__":
    asyncio.run(wipe_all_user_data())
