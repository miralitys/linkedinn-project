# app/routers/companies.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user_id
from app.models import Company
from app.schemas import CompanyCreate, CompanyRead, CompanyUpdate

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyRead])
async def list_companies(
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    q = select(Company).where(Company.user_id == user_id)
    r = await session.execute(q.order_by(func.lower(Company.name)))
    return list(r.scalars().all())


@router.post("", response_model=CompanyRead)
async def create_company(
    body: CompanyCreate,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    data = body.model_dump()
    data["user_id"] = user_id
    c = Company(**data)
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return c


@router.get("/{id}", response_model=CompanyRead)
async def get_company(
    id: int,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    r = await session.get(Company, id)
    if not r:
        raise HTTPException(404, "Company not found")
    if r.user_id != user_id:
        raise HTTPException(404, "Company not found")
    return r


@router.patch("/{id}", response_model=CompanyRead)
async def update_company(
    id: int,
    body: CompanyUpdate,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    c = await session.get(Company, id)
    if not c:
        raise HTTPException(404, "Company not found")
    if c.user_id != user_id:
        raise HTTPException(404, "Company not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    await session.commit()
    await session.refresh(c)
    return c


@router.delete("/{id}", status_code=204)
async def delete_company(
    id: int,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    c = await session.get(Company, id)
    if not c:
        raise HTTPException(404, "Company not found")
    if c.user_id != user_id:
        raise HTTPException(404, "Company not found")
    await session.delete(c)
    await session.commit()
