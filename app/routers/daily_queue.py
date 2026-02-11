# app/routers/daily_queue.py
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.deps import get_current_user_id
from app.models import Draft, DraftStatus, DraftType, LeadMagnet, Offer, Person, PersonStatus, SalesAvatar, Segment, Touch
from app.schemas import DailyQueueResponse
from app.state_machine import may_send_dm
from agents.registry import run_agent

router = APIRouter(prefix="/daily-queue", tags=["daily-queue"])

first_month_strict = bool(settings.lfas_first_month_strict)


def _avatar_str(avatar) -> str:
    if not avatar:
        return ""
    parts = [avatar.positioning or "", avatar.tone_guidelines or ""]
    if avatar.do_say:
        parts.append("Do: " + ", ".join(avatar.do_say))
    if avatar.dont_say:
        parts.append("Don't: " + ", ".join(avatar.dont_say))
    return "\n".join(p for p in parts if p)


@router.get("", response_model=DailyQueueResponse)
async def get_daily_queue(
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """Return current queue: comments (KOL posts to comment), posts (content ideas), dm_queue (warm contacts + draft)."""
    comments: list[dict] = []
    posts: list[dict] = []
    dm_queue: list[dict] = []

    # Лидеры мнений = контакты с is_kol=True (для комментариев под постами)
    r = await session.execute(
        select(Person)
        .where(Person.user_id == user_id, Person.is_kol == True)
        .order_by(Person.priority.desc(), Person.id)
        .limit(20)
    )
    kol_people = list(r.scalars().all())
    for p in kol_people:
        comments.append({"kol_id": p.id, "kol_name": p.full_name, "post_text": "", "drafts": []})

    # Content: suggest 2–3 posts (need avatar + segment + offer)
    r = await session.execute(select(SalesAvatar).where(SalesAvatar.user_id == user_id).limit(1))
    avatar = r.scalar_one_or_none()
    r = await session.execute(select(Segment).where(Segment.user_id == user_id).limit(1))
    seg = r.scalar_one_or_none()
    r = await session.execute(select(Offer).where(Offer.user_id == user_id).limit(1))
    offer = r.scalar_one_or_none()
    if avatar and (seg or offer):
        posts.append({
            "idea": "Пост про ценность продукта для сегмента",
            "segment_name": seg.name if seg else "",
            "offer_or_lead_magnet": offer.name if offer else "",
            "draft": None,
        })

    # DM queue: Warm contacts
    r = await session.execute(
        select(Person)
        .where(Person.user_id == user_id, Person.status == PersonStatus.WARM.value)
        .order_by(Person.priority.desc(), Person.last_touch_at)
        .limit(20)
    )
    warm_people = list(r.scalars().all())
    r = await session.execute(select(SalesAvatar).where(SalesAvatar.user_id == user_id).limit(1))
    avatar = r.scalar_one_or_none()
    for p in warm_people:
        # Touches summary
        r2 = await session.execute(select(Touch).where(Touch.person_id == p.id).order_by(Touch.created_at.desc()).limit(5))
        touches = list(r2.scalars().all())
        touches_summary = "\n".join([f"{t.type} ({t.direction}): {t.content[:80] if t.content else '-'}" for t in touches])
        seg_name = ""
        if p.segment_id:
            seg_obj = await session.get(Segment, p.segment_id)
            if seg_obj:
                seg_name = seg_obj.name
        allowed, reason = may_send_dm(p.status, has_warm_context=True, first_month_strict=first_month_strict)
        if not allowed:
            dm_queue.append({
                "person_id": p.id,
                "person_name": p.full_name,
                "status": p.status,
                "draft": None,
                "next_touch_date": None,
                "reason": reason,
            })
            continue
        # Optionally call sequencer for one to get draft (expensive); for GET just list
        dm_queue.append({
            "person_id": p.id,
            "person_name": p.full_name,
            "status": p.status,
            "draft": None,
            "next_touch_date": None,
            "reason": None,
        })

    return DailyQueueResponse(comments=comments, posts=posts, dm_queue=dm_queue)


@router.post("")
async def generate_daily_queue(
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """Generate drafts for daily queue (comment drafts for first N KOL, post drafts, DM drafts for warm). Can be called by scheduler."""
    # Same as GET but optionally trigger agent runs; for MVP we just return GET result
    return await get_daily_queue(session, user_id)
