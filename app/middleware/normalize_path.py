# app/middleware/normalize_path.py — редирект при двойном слэше в URL
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse


class NormalizePathMiddleware(BaseHTTPMiddleware):
    """Редирект с //path на /path при двойном слэше в начале."""
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("//") and not path.startswith("///"):
            new_path = "/" + path.lstrip("/")
            return RedirectResponse(url=new_path, status_code=302)
        return await call_next(request)
