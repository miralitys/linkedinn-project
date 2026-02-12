# app/services/usage.py
"""Учёт и проверка лимитов генераций."""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Usage, User
from app.plans import get_plan


def _year_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


async def get_monthly_usage(session: AsyncSession, user_id: int) -> int:
    """Сумма генераций за текущий месяц для пользователя."""
    ym = _year_month()
    r = await session.execute(
        select(func.coalesce(func.sum(Usage.count), 0)).where(
            Usage.user_id == user_id, Usage.year_month == ym
        )
    )
    return int(r.scalar() or 0)


async def get_post_usage(session: AsyncSession, user_id: int) -> int:
    """Генерации постов за текущий месяц (content_agent, news_post_agent)."""
    ym = _year_month()
    r = await session.execute(
        select(func.coalesce(func.sum(Usage.count), 0)).where(
            Usage.user_id == user_id,
            Usage.year_month == ym,
            Usage.agent_name.in_(("content_agent", "news_post_agent")),
        )
    )
    return int(r.scalar() or 0)


async def get_comment_usage(session: AsyncSession, user_id: int) -> int:
    """Генерации комментариев/DM за текущий месяц (comment_agent, outreach_sequencer)."""
    ym = _year_month()
    r = await session.execute(
        select(func.coalesce(func.sum(Usage.count), 0)).where(
            Usage.user_id == user_id,
            Usage.year_month == ym,
            Usage.agent_name.in_(("comment_agent", "outreach_sequencer")),
        )
    )
    return int(r.scalar() or 0)


async def increment_usage(
    session: AsyncSession, user_id: int, agent_name: str, count: int = 1
) -> None:
    """Увеличить счётчик генераций на count."""
    ym = _year_month()
    r = await session.execute(
        select(Usage).where(
            Usage.user_id == user_id,
            Usage.year_month == ym,
            Usage.agent_name == agent_name,
        ).limit(1)
    )
    row = r.scalar_one_or_none()
    if row:
        row.count = (row.count or 0) + count
    else:
        session.add(
            Usage(user_id=user_id, year_month=ym, agent_name=agent_name, count=count)
        )


def _is_post_agent(agent_name: str) -> bool:
    return agent_name in ("content_agent", "news_post_agent")


def _is_comment_agent(agent_name: str) -> bool:
    return agent_name in ("comment_agent", "outreach_sequencer")


async def check_generation_limit(
    session: AsyncSession, user_id: int, agent_name: str
) -> tuple[bool, int, int]:
    """
    Проверка: можно ли сделать ещё одну генерацию.
    Возвращает (ok, current, limit).
    Для Starter: отдельные лимиты post/comment. Для Pro/Enterprise: общий generations_month.
    """
    try:
        user = await session.get(User, user_id)
    except Exception:
        # Если запрос не удался (миграция, схема) — разрешаем генерацию
        return True, 0, 999
    plan_name = getattr(user, "plan_name", None) if user else None
    plan = get_plan(plan_name)

    if plan.get("post_generations_month") is not None and _is_post_agent(agent_name):
        limit = plan.get("post_generations_month", 10)
        current = await get_post_usage(session, user_id)
    elif plan.get("comment_generations_month") is not None and _is_comment_agent(agent_name):
        limit = plan.get("comment_generations_month", 30)
        current = await get_comment_usage(session, user_id)
    else:
        limit = plan.get("generations_month", 500)
        current = await get_monthly_usage(session, user_id)
    return current < limit, current, limit


GENERATION_AGENTS = {"content_agent", "comment_agent", "news_post_agent", "outreach_sequencer"}
