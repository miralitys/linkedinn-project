# app/routers/admin.py — админ-панель: список пользователей
import bcrypt
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import User, UserRole, SubscriptionStatus, UserApprovalStatus
from app.plans import PLANS
from app.translations import get_locale_from_cookie, get_tr

router = APIRouter(prefix="/admin", tags=["admin"])
_templates = Jinja2Templates(directory=str(settings.base_dir / "templates"))


def _is_admin(request: Request) -> bool:
    """Проверяет, является ли пользователь админом."""
    try:
        role = request.session.get("user_role")
        return role == UserRole.ADMIN.value
    except Exception:
        return False


@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Админ-страница: список всех пользователей."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        locale = get_locale_from_cookie(getattr(request, "cookies", None))
        tr = get_tr(locale)
    except Exception:
        from app.translations import RU
        locale = "ru"
        tr = RU
    
    # Получаем всех пользователей
    r = await session.execute(select(User).order_by(User.created_at.desc()))
    users = list(r.scalars().all())

    # Сериализуем для JS (edit/delete/approve)
    users_serialized = [
        {
            "id": u.id,
            "email": u.email,
            "role": u.role,
            "plan_name": u.plan_name or "starter",
            "subscription_status": u.subscription_status,
            "subscription_expires_at": u.subscription_expires_at.isoformat()[:10] if u.subscription_expires_at else None,
            "approval_status": getattr(u, "approval_status", UserApprovalStatus.APPROVED.value),
        }
        for u in users
    ]
    
    # Статистика
    total_users = len(users)
    admin_count = sum(1 for u in users if u.role == UserRole.ADMIN.value)
    active_subscriptions = sum(1 for u in users if u.subscription_status == SubscriptionStatus.ACTIVE.value)
    trial_users = sum(1 for u in users if u.subscription_status == SubscriptionStatus.TRIAL.value)
    pending_users = sum(1 for u in users if getattr(u, "approval_status", UserApprovalStatus.APPROVED.value) == UserApprovalStatus.PENDING.value)
    
    return _templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            "users": users,
            "users_serialized": users_serialized,
            "plans": list(PLANS.keys()),
            "total_users": total_users,
            "admin_count": admin_count,
            "active_subscriptions": active_subscriptions,
            "trial_users": trial_users,
            "pending_users": pending_users,
            "locale": locale,
            "tr": tr,
            "request": request,
        },
    )


class UserCreateRequest(BaseModel):
    email: str
    password: str
    role: str = UserRole.USER.value
    plan_name: str = "starter"
    subscription_status: str = SubscriptionStatus.FREE.value


class UserUpdateRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    plan_name: Optional[str] = None
    subscription_status: Optional[str] = None
    subscription_expires_at: Optional[str] = None


def _hash_password(password: str) -> str:
    """Хеширует пароль с помощью bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


@router.post("/users", response_class=JSONResponse)
async def create_user(
    request: Request,
    body: UserCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Создание нового пользователя (только для админов)."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Валидация email
    email_lower = body.email.strip().lower()
    if not email_lower or "@" not in email_lower:
        raise HTTPException(status_code=400, detail="Invalid email")
    
    # Валидация пароля
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    if body.role not in [UserRole.USER.value, UserRole.ADMIN.value]:
        raise HTTPException(status_code=400, detail="Invalid role")

    if body.plan_name not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan name")
    
    if body.subscription_status not in [
        SubscriptionStatus.FREE.value,
        SubscriptionStatus.TRIAL.value,
        SubscriptionStatus.ACTIVE.value,
        SubscriptionStatus.EXPIRED.value,
        SubscriptionStatus.CANCELLED.value,
    ]:
        raise HTTPException(status_code=400, detail="Invalid subscription status")
    
    # Проверка существующего пользователя
    r = await session.execute(select(User).where(User.email == email_lower))
    existing = r.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists")
    
    # Создание пользователя
    user = User(
        email=email_lower,
        password_hash=_hash_password(body.password),
        role=body.role,
        plan_name=body.plan_name,
        subscription_status=body.subscription_status,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "plan_name": user.plan_name,
        "subscription_status": user.subscription_status,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.patch("/users/{user_id}", response_class=JSONResponse)
async def update_user(
    user_id: int,
    request: Request,
    body: UserUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Обновление пользователя (только для админов)."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    r = await session.execute(select(User).where(User.id == user_id))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.email is not None:
        email_lower = body.email.strip().lower()
        if email_lower and "@" in email_lower:
            r_ex = await session.execute(select(User).where(and_(User.email == email_lower, User.id != user_id)))
            if r_ex.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="User with this email already exists")
            user.email = email_lower

    if body.password is not None and len(body.password) >= 6:
        user.password_hash = _hash_password(body.password)

    if body.role is not None and body.role in [UserRole.USER.value, UserRole.ADMIN.value]:
        user.role = body.role

    if body.plan_name is not None and body.plan_name in PLANS:
        user.plan_name = body.plan_name

    if body.subscription_status is not None and body.subscription_status in [
        SubscriptionStatus.FREE.value,
        SubscriptionStatus.TRIAL.value,
        SubscriptionStatus.ACTIVE.value,
        SubscriptionStatus.EXPIRED.value,
        SubscriptionStatus.CANCELLED.value,
    ]:
        user.subscription_status = body.subscription_status

    if body.subscription_expires_at is not None:
        if body.subscription_expires_at.strip() == "":
            user.subscription_expires_at = None
        else:
            try:
                from datetime import date
                dt = datetime.strptime(body.subscription_expires_at.strip()[:10], "%Y-%m-%d")
                user.subscription_expires_at = dt
            except (ValueError, TypeError):
                pass

    user.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(user)

    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "plan_name": user.plan_name,
        "subscription_status": user.subscription_status,
        "subscription_expires_at": user.subscription_expires_at.isoformat() if user.subscription_expires_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.post("/users/{user_id}/approve", response_class=JSONResponse)
async def approve_user(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Одобрить пользователя (только для админов)."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    r = await session.execute(select(User).where(User.id == user_id))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.approval_status = UserApprovalStatus.APPROVED.value
    user.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(user)

    return {
        "id": user.id,
        "email": user.email,
        "approval_status": user.approval_status,
    }


@router.post("/users/{user_id}/reject", response_class=JSONResponse)
async def reject_user(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Отклонить регистрацию пользователя (только для админов)."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    r = await session.execute(select(User).where(User.id == user_id))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.approval_status = UserApprovalStatus.REJECTED.value
    user.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(user)

    return {
        "id": user.id,
        "email": user.email,
        "approval_status": user.approval_status,
    }


@router.delete("/users/{user_id}", response_class=JSONResponse)
async def delete_user(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Удаление пользователя (только для админов)."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    current_user_id = request.session.get("user_id")
    if current_user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    r = await session.execute(select(User).where(User.id == user_id))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await session.delete(user)
    await session.commit()

    return {"deleted": True, "id": user_id}
