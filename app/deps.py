# app/deps.py — зависимости для FastAPI (текущий пользователь)
from fastapi import Depends, HTTPException, Request


async def get_current_user_id(request: Request) -> int:
    """Возвращает user_id из сессии. Вызывает 401, если пользователь не авторизован."""
    uid = request.session.get("user_id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return int(uid)
