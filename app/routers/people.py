# app/routers/people.py
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Person, PersonStatus
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
):
    q = select(Person).order_by(func.lower(Person.full_name))
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
async def create_person(body: PersonCreate, session: AsyncSession = Depends(get_session)):
    p = Person(**body.model_dump())
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


@router.get("/{id}", response_model=PersonRead)
async def get_person(id: int, session: AsyncSession = Depends(get_session)):
    p = await session.get(Person, id)
    if not p:
        raise HTTPException(404, "Person not found")
    return p


@router.patch("/{id}", response_model=PersonRead)
async def update_person(id: int, body: PersonUpdate, session: AsyncSession = Depends(get_session)):
    p = await session.get(Person, id)
    if not p:
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
):
    p = await session.get(Person, id)
    if not p:
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
async def delete_person(id: int, session: AsyncSession = Depends(get_session)):
    p = await session.get(Person, id)
    if not p:
        raise HTTPException(404, "Person not found")
    await session.delete(p)
    await session.commit()
