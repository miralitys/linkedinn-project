# app/routers/people.py
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user_id
from app.models import Company, ContactPost, Person, PersonStatus, Segment, Touch, User
from app.plans import get_plan
from app.services.limits import get_priority_profiles_count, get_rss_sources_count
from app.schemas import PersonCreate, PersonRead, PersonStatusUpdate, PersonUpdate
from app.state_machine import can_transition

router = APIRouter(prefix="/people", tags=["people"])


@router.get("", response_model=list[PersonRead])
async def list_people(
    status: Optional[str] = None,
    segment_id: Optional[int] = None,
    company_id: Optional[int] = None,
    is_kol: Optional[bool] = None,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    q = select(Person).where(Person.user_id == user_id).order_by(func.lower(Person.full_name))
    if status:
        q = q.where(Person.status == status)
    if segment_id is not None:
        q = q.where(Person.segment_id == segment_id)
    if company_id is not None:
        q = q.where(Person.company_id == company_id)
    if is_kol is not None:
        q = q.where(Person.is_kol == is_kol)
    r = await session.execute(q)
    return list(r.scalars().all())


@router.post("", response_model=PersonRead)
async def create_person(
    body: PersonCreate,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    # Проверка лимита людей
    user = await session.get(User, user_id)
    plan = get_plan(user.plan_name if user else None)
    r = await session.execute(select(func.count()).select_from(Person).where(Person.user_id == user_id))
    people_count = r.scalar() or 0
    if people_count >= plan.get("people", 25):
        raise HTTPException(
            status_code=403,
            detail=f"Limit reached: {people_count}/{plan.get('people')} people. Upgrade your plan.",
        )

    # Лимит приоритетных профилей (watchlist / is_kol)
    if plan.get("priority_profiles") is not None and getattr(body, "is_kol", False):
        kol_count = await get_priority_profiles_count(session, user_id)
        if kol_count >= plan.get("priority_profiles", 3):
            raise HTTPException(
                status_code=403,
                detail=f"Limit reached: {kol_count}/{plan.get('priority_profiles')} priority profiles. Upgrade your plan.",
            )

    # Лимит RSS-источников (feed_url) для Starter
    if plan.get("rss_sources") is not None and (body.feed_url or "").strip():
        rss_count = await get_rss_sources_count(session, user_id)
        if rss_count >= plan.get("rss_sources", 2):
            raise HTTPException(
                status_code=403,
                detail=f"Limit reached: {rss_count}/{plan.get('rss_sources')} RSS sources. Upgrade your plan.",
            )

    data = body.model_dump()
    if data.get("company_id"):
        c = await session.get(Company, data["company_id"])
        if c and c.user_id != user_id:
            raise HTTPException(400, "Company not found")
    if data.get("segment_id"):
        s = await session.get(Segment, data["segment_id"])
        if s and s.user_id != user_id:
            raise HTTPException(400, "Segment not found")
    data["user_id"] = user_id
    p = Person(**data)
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


@router.get("/{id}", response_model=PersonRead)
async def get_person(
    id: int,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    p = await session.get(Person, id)
    if not p:
        raise HTTPException(404, "Person not found")
    if p.user_id != user_id:
        raise HTTPException(404, "Person not found")
    return p


@router.patch("/{id}", response_model=PersonRead)
async def update_person(
    id: int,
    body: PersonUpdate,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    p = await session.get(Person, id)
    if not p:
        raise HTTPException(404, "Person not found")
    if p.user_id != user_id:
        raise HTTPException(404, "Person not found")
    user = await session.get(User, user_id)
    plan = get_plan(user.plan_name if user else None)
    updates = body.model_dump(exclude_unset=True)
    # Лимит приоритетных профилей: при включении is_kol контакту, у которого его не было
    if plan.get("priority_profiles") is not None and "is_kol" in updates and updates.get("is_kol"):
        was_kol = getattr(p, "is_kol", False)
        if not was_kol:
            kol_count = await get_priority_profiles_count(session, user_id)
            if kol_count >= plan.get("priority_profiles", 3):
                raise HTTPException(
                    status_code=403,
                    detail=f"Limit reached: {kol_count}/{plan.get('priority_profiles')} priority profiles. Upgrade your plan.",
                )

    # Лимит RSS: при добавлении feed_url контакту, у которого его не было
    if plan.get("rss_sources") is not None and "feed_url" in updates:
        new_feed = (updates.get("feed_url") or "").strip()
        had_feed = (getattr(p, "feed_url") or "").strip()
        if new_feed and not had_feed:
            rss_count = await get_rss_sources_count(session, user_id)
            if rss_count >= plan.get("rss_sources", 2):
                raise HTTPException(
                    status_code=403,
                    detail=f"Limit reached: {rss_count}/{plan.get('rss_sources')} RSS sources. Upgrade your plan.",
                )
    for k, v in updates.items():
        setattr(p, k, v)
    await session.commit()
    await session.refresh(p)
    return p


@router.patch("/{id}/status", response_model=PersonRead)
async def update_person_status(
    id: int,
    body: PersonStatusUpdate,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    p = await session.get(Person, id)
    if not p:
        raise HTTPException(404, "Person not found")
    if p.user_id != user_id:
        raise HTTPException(404, "Person not found")
    to_status = body.status
    if not can_transition(p.status, to_status):
        raise HTTPException(
            400,
            f"Transition from {p.status} to {to_status} not allowed",
        )
    p.status = to_status
    await session.commit()
    await session.refresh(p)
    return p


@router.delete("/{id}", status_code=204)
async def delete_person(
    id: int,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    p = await session.get(Person, id)
    if not p:
        raise HTTPException(404, "Person not found")
    if p.user_id != user_id:
        raise HTTPException(404, "Person not found")
    # Удаляем связанные посты и касания до удаления контакта (person_id NOT NULL)
    await session.execute(delete(ContactPost).where(ContactPost.person_id == id))
    await session.execute(delete(Touch).where(Touch.person_id == id))
    await session.delete(p)
    await session.commit()
