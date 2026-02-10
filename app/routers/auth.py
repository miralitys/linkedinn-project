# app/routers/auth.py — вход по email и паролю
import secrets

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings

router = APIRouter(tags=["auth"])
_templates = Jinja2Templates(directory=str(settings.base_dir / "templates"))


def _check_credentials(email: str, password: str) -> bool:
    if not settings.auth_admin_email or not settings.auth_admin_password:
        return False
    return secrets.compare_digest(email.strip(), settings.auth_admin_email.strip()) and secrets.compare_digest(
        password, settings.auth_admin_password
    )


def _auth_required() -> bool:
    return bool(
        settings.auth_enabled
        and settings.auth_admin_email
        and settings.auth_admin_password
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("authenticated"):
        return RedirectResponse(url=request.query_params.get("next", "/ui/posts"), status_code=302)
    return _templates.TemplateResponse(request, "login.html", {"error": None, "auth_configured": _auth_required()})


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(..., alias="email"),
    password: str = Form(..., alias="password"),
):
    if not _auth_required():
        return RedirectResponse(url="/ui/posts", status_code=302)
    if _check_credentials(email, password):
        request.session["authenticated"] = True
        request.session["user"] = email.strip()
        next_url = request.query_params.get("next", "/ui/posts")
        if not next_url.startswith("/"):
            next_url = "/ui/posts"
        return RedirectResponse(url=next_url, status_code=302)
    return _templates.TemplateResponse(
        request, "login.html", {"error": "Неверный email или пароль", "auth_configured": True}, status_code=401
    )


@router.get("/logout")
@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)
