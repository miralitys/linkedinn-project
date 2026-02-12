# app/services/limits.py
"""Проверка лимитов: люди, источники (сабреддиты), приоритетные профили, персоны."""
import json
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeBase, Person, SavedSubreddit

SUBREDDITS_KEY = "saved_subreddits"


def _kb_key(base_key: str, user_id: int) -> str:
    """Ключ KnowledgeBase с user_id (multi-tenant)."""
    return f"{base_key}:{user_id}"


async def get_reddit_sources_count(session: AsyncSession, user_id: int) -> int:
    """Количество Reddit-источников: SavedSubreddit + KnowledgeBase saved_subreddits."""
    return await _get_subreddit_names_count(session, user_id)


async def get_rss_sources_count(session: AsyncSession, user_id: int) -> int:
    """Количество RSS-источников: контакты с feed_url."""
    from app.models import Person
    r = await session.execute(
        select(Person.id).where(
            Person.user_id == user_id,
            Person.feed_url.isnot(None),
            Person.feed_url != "",
        )
    )
    return len(r.fetchall())


async def _get_subreddit_names_count(session: AsyncSession, user_id: int) -> int:
    """Количество уникальных имён сабреддитов."""
    names = set()
    # SavedSubreddit
    r = await session.execute(
        select(SavedSubreddit.name).where(SavedSubreddit.user_id == user_id)
    )
    for row in r.fetchall():
        if row[0]:
            names.add(row[0].lower())
    # KnowledgeBase
    key = _kb_key(SUBREDDITS_KEY, user_id)
    r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == key))
    row = r.scalar_one_or_none()
    if row and row.value:
        try:
            data = json.loads(row.value)
            for n in (data if isinstance(data, list) else []):
                if n:
                    names.add(str(n).strip().lower())
        except Exception:
            pass
    return len(names)


async def get_sources_count(session: AsyncSession, user_id: int) -> int:
    """Общее количество источников: RSS + Reddit (для планов с sources)."""
    rss = await get_rss_sources_count(session, user_id)
    reddit = await _get_subreddit_names_count(session, user_id)
    return rss + reddit


async def get_priority_profiles_count(session: AsyncSession, user_id: int) -> int:
    """Количество приоритетных профилей (watchlist): контакты с is_kol=True."""
    r = await session.execute(
        select(func.count()).select_from(Person).where(
            Person.user_id == user_id,
            Person.is_kol == True,
        )
    )
    return int(r.scalar() or 0)


async def get_authors_count(session: AsyncSession, user_id: int, base_key: str = "setup_authors") -> int:
    """Количество персон (авторов) в setup."""
    key = _kb_key(base_key, user_id)
    r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == key))
    row = r.scalar_one_or_none()
    if not row or not row.value:
        return 0
    try:
        data = json.loads(row.value)
        return len(data) if isinstance(data, list) else 0
    except Exception:
        return 0
