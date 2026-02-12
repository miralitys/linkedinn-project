# app/routers/plans.py
"""API и страницы тарифов."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user_id
from app.models import Person, User
from app.plans import PLANS, get_plan
from app.services.limits import (
    get_authors_count,
    get_priority_profiles_count,
    get_reddit_sources_count,
    get_rss_sources_count,
    get_sources_count,
)
from app.services.usage import get_comment_usage, get_monthly_usage, get_post_usage

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("/current")
async def get_current_plan(
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """Текущий план пользователя и использование."""
    user = await session.get(User, user_id)
    plan_name = (user.plan_name or "starter") if user else "starter"
    plan = get_plan(plan_name)

    r = await session.execute(select(func.count()).select_from(Person).where(Person.user_id == user_id))
    people_count = r.scalar() or 0

    usage = {
        "people": people_count,
        "people_limit": plan.get("people", 25),
    }

    if plan.get("priority_profiles") is not None:
        usage["priority_profiles"] = await get_priority_profiles_count(session, user_id)
        usage["priority_profiles_limit"] = plan.get("priority_profiles", 3)
    if plan.get("personas") is not None:
        usage["personas"] = await get_authors_count(session, user_id)
        usage["personas_limit"] = plan.get("personas", 1)
    if plan.get("rss_sources") is not None:
        usage["rss_sources"] = await get_rss_sources_count(session, user_id)
        usage["rss_sources_limit"] = plan.get("rss_sources", 2)
    if plan.get("reddit_sources") is not None:
        usage["reddit_sources"] = await get_reddit_sources_count(session, user_id)
        usage["reddit_sources_limit"] = plan.get("reddit_sources", 3)
    if plan.get("sources") is not None:
        usage["sources"] = await get_sources_count(session, user_id)
        usage["sources_limit"] = plan.get("sources", 10)

    if plan.get("post_generations_month") is not None:
        usage["post_generations"] = await get_post_usage(session, user_id)
        usage["post_generations_limit"] = plan.get("post_generations_month", 10)
    if plan.get("comment_generations_month") is not None:
        usage["comment_generations"] = await get_comment_usage(session, user_id)
        usage["comment_generations_limit"] = plan.get("comment_generations_month", 30)
    if plan.get("generations_month") is not None:
        usage["generations"] = await get_monthly_usage(session, user_id)
        usage["generations_limit"] = plan.get("generations_month", 500)

    return {"plan_name": plan_name, "plan": plan, "usage": usage}


@router.get("/list")
async def list_plans():
    """Список всех планов (для страницы pricing)."""
    return {"plans": PLANS}
