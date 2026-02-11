# app/routers/touches.py
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user_id
from app.models import Person, Touch
from app.schemas import TouchCreate, TouchRead

router = APIRouter(prefix="/touches", tags=["touches"])


@router.get("", response_model=list)
async def list_touches(
    person_id: Optional[int] = None,
    type: Optional[str] = None,
    limit: int = Query(100, le=500),
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    person_subq = select(Person.id).where(Person.user_id == user_id)
    q = select(Touch).where(Touch.person_id.in_(person_subq)).order_by(Touch.created_at.desc()).limit(limit)
    if person_id is not None:
        q = q.where(Touch.person_id == person_id)
    if type:
        q = q.where(Touch.type == type)
    r = await session.execute(q)
    return list(r.scalars().all())


@router.post("", response_model=TouchRead)
async def create_touch(
    body: TouchCreate,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    p = await session.get(Person, body.person_id)
    if not p:
        raise HTTPException(404, "Person not found")
    if p.user_id is not None and p.user_id != user_id:
        raise HTTPException(404, "Person not found")
    t = Touch(**body.model_dump())
    session.add(t)
    # Update person last_touch_at
    if p:
        p.last_touch_at = datetime.utcnow()
    await session.commit()
    await session.refresh(t)
    return t
