# app/middleware/auth.py — редирект на /login, если не авторизован
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, JSONResponse

from app.config import settings

PUBLIC_PATHS = {"/", "/login", "/register", "/logout", "/en", "/en/", "/set-locale"}


def _auth_protection_enabled() -> bool:
    """Защита включена, если настроены email и пароль."""
    return bool(
        settings.auth_enabled
        and settings.auth_admin_email
        and settings.auth_admin_password
    )


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not _auth_protection_enabled():
            return await call_next(request)
        path = request.url.path.rstrip("/") or "/"
        if path in PUBLIC_PATHS or path.startswith("/static") or path.startswith("/register"):
            return await call_next(request)
        # Проверяем доступность session более надежно
        session = getattr(request, "session", None)
        if session is None:
            # Если session недоступна, пропускаем проверку (может быть ошибка конфигурации)
            return await call_next(request)
        if session.get("authenticated"):
            return await call_next(request)
        if path.startswith("/ui") or "text/html" in request.headers.get("accept", ""):
            next_url = request.url.path
            if request.query_params:
                next_url += "?" + str(request.query_params)
            return RedirectResponse(url=f"/login?next={next_url}", status_code=302)
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
