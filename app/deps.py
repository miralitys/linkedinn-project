# app/deps.py — зависимости для FastAPI (текущий пользователь)
import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from app.db import async_session_maker
from app.models import User, UserApprovalStatus, UserRole
from app.plans import DEFAULT_PLAN


async def get_current_user_id(request: Request) -> int:
    """Возвращает user_id из сессии. Вызывает 401, если пользователь не авторизован."""
    uid = request.session.get("user_id")
    if uid is not None:
        return int(uid)
    # Fallback: если authenticated, но user_id нет (legacy-сессия) — ищем или привязываем
    if request.session.get("authenticated") and request.session.get("user"):
        email = str(request.session.get("user", "")).strip().lower()
        if email:
            async with async_session_maker() as db:
                r = await db.execute(select(User).where(User.email == email))
                user = r.scalar_one_or_none()
                if not user:
                    # Создаём нового пользователя — у каждого свой user_id
                    pw_hash = bcrypt.hashpw(b"legacy-session-fix", bcrypt.gensalt()).decode("utf-8")
                    user = User(
                        email=email,
                        password_hash=pw_hash,
                        role=UserRole.ADMIN.value,
                        approval_status=UserApprovalStatus.APPROVED.value,
                        plan_name=DEFAULT_PLAN,
                    )
                    db.add(user)
                    await db.commit()
                    await db.refresh(user)
                request.session["user_id"] = user.id
                return user.id
    raise HTTPException(status_code=401, detail="Authentication required")
