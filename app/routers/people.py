# app/routers/people.py
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user_id
from app.models import Company, ContactPost, Person, PersonStatus, Segment, Touch
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
    data = body.model_dump()
    if data.get("company_id"):
        c = await session.get(Company, data["company_id"])
        if c and c.user_id is not None and c.user_id != user_id:
            raise HTTPException(400, "Company not found")
    if data.get("segment_id"):
        s = await session.get(Segment, data["segment_id"])
        if s and s.user_id is not None and s.user_id != user_id:
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
    if p.user_id is not None and p.user_id != user_id:
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
    if p.user_id is not None and p.user_id != user_id:
        raise HTTPException(404, "Person not found")
    for k, v in body.model_dump(exclude_unset=True).items():
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
    if p.user_id is not None and p.user_id != user_id:
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
    if p.user_id is not None and p.user_id != user_id:
        raise HTTPException(404, "Person not found")
    # Удаляем связанные посты и касания до удаления контакта (person_id NOT NULL)
    await session.execute(delete(ContactPost).where(ContactPost.person_id == id))
    await session.execute(delete(Touch).where(Touch.person_id == id))
    await session.delete(p)
    await session.commit()
