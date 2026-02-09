# app/routers/kol.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import KOL
from app.schemas import KOLCreate, KOLRead, KOLUpdate

router = APIRouter(prefix="/kol", tags=["kol"])


@router.get("", response_model=list[KOLRead])
async def list_kol(session: AsyncSession = Depends(get_session)):
    r = await session.execute(select(KOL).order_by(KOL.priority.desc(), KOL.id))
    return list(r.scalars().all())


@router.post("", response_model=KOLRead)
async def create_kol(body: KOLCreate, session: AsyncSession = Depends(get_session)):
    k = KOL(**body.model_dump())
    session.add(k)
    await session.commit()
    await session.refresh(k)
    return k


@router.get("/{id}", response_model=KOLRead)
async def get_kol(id: int, session: AsyncSession = Depends(get_session)):
    k = await session.get(KOL, id)
    if not k:
        raise HTTPException(404, "KOL not found")
    return k


@router.patch("/{id}", response_model=KOLRead)
async def update_kol(id: int, body: KOLUpdate, session: AsyncSession = Depends(get_session)):
    k = await session.get(KOL, id)
    if not k:
        raise HTTPException(404, "KOL not found")
    for k2, v in body.model_dump(exclude_unset=True).items():
        setattr(k, k2, v)
    await session.commit()
    await session.refresh(k)
    return k


@router.delete("/{id}", status_code=204)
async def delete_kol(id: int, session: AsyncSession = Depends(get_session)):
    k = await session.get(KOL, id)
    if not k:
        raise HTTPException(404, "KOL not found")
    await session.delete(k)
    await session.commit()
