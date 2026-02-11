# app/deps.py — зависимости для FastAPI (текущий пользователь)
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from app.db import async_session_maker
from app.models import User


async def get_current_user_id(request: Request) -> int:
    """Возвращает user_id из сессии. Вызывает 401, если пользователь не авторизован."""
    uid = request.session.get("user_id")
    if uid is not None:
        return int(uid)
    # Fallback: если authenticated, но user_id нет (legacy-сессия) — ищем по email
    if request.session.get("authenticated") and request.session.get("user"):
        email = str(request.session.get("user", "")).strip().lower()
        if email:
            async with async_session_maker() as db:
                r = await db.execute(select(User).where(User.email == email))
                user = r.scalar_one_or_none()
                if user:
                    request.session["user_id"] = user.id
                    return user.id
    raise HTTPException(status_code=401, detail="Authentication required")
