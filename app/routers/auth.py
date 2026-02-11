# app/routers/auth.py — вход по email и паролю, регистрация
import bcrypt
import hmac
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import User, UserRole, UserApprovalStatus
from app.translations import get_locale_from_cookie, get_tr

router = APIRouter(tags=["auth"])
_templates = Jinja2Templates(directory=str(settings.base_dir / "templates"))


def _hash_password(password: str) -> str:
    """Хеширует пароль с помощью bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _check_password(password: str, password_hash: str) -> bool:
    """Проверяет пароль против хеша."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


async def _check_credentials_db(email: str, password: str, session: AsyncSession) -> tuple[Optional[User], Optional[str]]:
    """Проверяет учетные данные в БД. Возвращает (user, error). error: None | 'pending' | 'rejected' | 'bad_password' | 'not_found'."""
    r = await session.execute(select(User).where(User.email == email.strip().lower()))
    user = r.scalar_one_or_none()
    if not user:
        return None, "not_found"
    if not _check_password(password, user.password_hash):
        return None, "bad_password"
    status = getattr(user, "approval_status", UserApprovalStatus.APPROVED.value)
    if status == UserApprovalStatus.PENDING.value:
        return None, "pending"
    if status == UserApprovalStatus.REJECTED.value:
        return None, "rejected"
    return user, None


def _check_credentials_env(email: str, password: str) -> bool:
    """Проверяет учетные данные из .env (для обратной совместимости)."""
    if not settings.auth_admin_email or not settings.auth_admin_password:
        return False
    # Используем hmac.compare_digest с байтами для поддержки не-ASCII символов
    email_match = hmac.compare_digest(
        email.strip().encode("utf-8"),
        settings.auth_admin_email.strip().encode("utf-8")
    )
    password_match = hmac.compare_digest(
        password.encode("utf-8"),
        settings.auth_admin_password.encode("utf-8")
    )
    return email_match and password_match


def _auth_required() -> bool:
    return bool(settings.auth_enabled)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    try:
        if request.session.get("authenticated"):
            return RedirectResponse(url=request.query_params.get("next", "/ui/posts"), status_code=302)
    except Exception:
        pass
    try:
        locale = get_locale_from_cookie(getattr(request, "cookies", None))
        tr = get_tr(locale)
    except Exception:
        from app.translations import RU
        locale = "ru"
        tr = RU
    return _templates.TemplateResponse(
        request, "login.html", {"error": None, "auth_configured": _auth_required(), "locale": locale, "tr": tr}
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(..., alias="email"),
    password: str = Form(..., alias="password"),
    session: AsyncSession = Depends(get_session),
):
    if not _auth_required():
        return RedirectResponse(url="/ui/posts", status_code=302)
    
    # Сначала пробуем БД
    user, cred_error = await _check_credentials_db(email, password, session)
    if cred_error == "pending":
        try:
            locale = get_locale_from_cookie(getattr(request, "cookies", None))
            tr = get_tr(locale)
        except Exception:
            from app.translations import RU
            locale = "ru"
            tr = RU
        return _templates.TemplateResponse(
            request,
            "login.html",
            {"error": tr.get("login_error_pending", "Аккаунт ожидает подтверждения администратора."), "auth_configured": True, "locale": locale, "tr": tr},
            status_code=403,
        )
    if cred_error == "rejected":
        try:
            locale = get_locale_from_cookie(getattr(request, "cookies", None))
            tr = get_tr(locale)
        except Exception:
            from app.translations import RU
            locale = "ru"
            tr = RU
        return _templates.TemplateResponse(
            request,
            "login.html",
            {"error": tr.get("login_error_rejected", "Регистрация отклонена."), "auth_configured": True, "locale": locale, "tr": tr},
            status_code=403,
        )
    if user:
        user.last_login_at = datetime.utcnow()
        await session.commit()
        request.session["authenticated"] = True
        request.session["user_id"] = user.id
        request.session["user"] = user.email
        # Email из .env всегда админ, даже если в БД роль user
        admin_email = (settings.auth_admin_email or "").strip().lower()
        if admin_email and user.email.lower() == admin_email:
            request.session["user_role"] = UserRole.ADMIN.value
        else:
            request.session["user_role"] = user.role
        next_url = request.query_params.get("next", "/ui/posts")
        if not next_url.startswith("/"):
            next_url = "/ui/posts"
        return RedirectResponse(url=next_url, status_code=302)
    
    # Fallback на .env для обратной совместимости
    if _check_credentials_env(email, password):
        request.session["authenticated"] = True
        request.session["user"] = email.strip()
        request.session["user_role"] = UserRole.ADMIN.value  # .env админ
        # Найти или создать пользователя, чтобы user_id был в сессии (для API)
        r = await session.execute(select(User).where(User.email == email.strip().lower()))
        env_user = r.scalar_one_or_none()
        if env_user:
            request.session["user_id"] = env_user.id
        else:
            env_user = User(
                email=email.strip().lower(),
                password_hash=_hash_password(password),
                role=UserRole.ADMIN.value,
                approval_status=UserApprovalStatus.APPROVED.value,
            )
            session.add(env_user)
            await session.commit()
            await session.refresh(env_user)
            request.session["user_id"] = env_user.id
        next_url = request.query_params.get("next", "/ui/posts")
        if not next_url.startswith("/"):
            next_url = "/ui/posts"
        return RedirectResponse(url=next_url, status_code=302)
    
    try:
        locale = get_locale_from_cookie(getattr(request, "cookies", None))
        tr = get_tr(locale)
    except Exception:
        from app.translations import RU
        locale = "ru"
        tr = RU
    return _templates.TemplateResponse(
        request,
        "login.html",
        {"error": tr.get("login_error_bad_credentials", "Invalid email or password"), "auth_configured": True, "locale": locale, "tr": tr},
        status_code=401,
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    try:
        if request.session.get("authenticated"):
            return RedirectResponse(url="/ui/posts", status_code=302)
    except Exception:
        pass
    try:
        locale = get_locale_from_cookie(getattr(request, "cookies", None))
        tr = get_tr(locale)
    except Exception:
        from app.translations import RU
        locale = "ru"
        tr = RU
    return _templates.TemplateResponse(
        request, "register.html", {"error": None, "auth_configured": _auth_required(), "locale": locale, "tr": tr}
    )


@router.get("/register/pending", response_class=HTMLResponse)
async def register_pending(request: Request):
    """Страница после успешной регистрации: «Вы зарегистрированы, ждите подтверждения»."""
    try:
        locale = get_locale_from_cookie(getattr(request, "cookies", None))
        tr = get_tr(locale)
    except Exception:
        from app.translations import RU
        locale = "ru"
        tr = RU
    return _templates.TemplateResponse(
        request, "register_pending.html", {"locale": locale, "tr": tr}
    )


@router.post("/register")
async def register_submit(
    request: Request,
    email: str = Form(..., alias="email"),
    password: str = Form(..., alias="password"),
    password_confirm: str = Form(..., alias="password_confirm"),
    session: AsyncSession = Depends(get_session),
):
    if not _auth_required():
        return RedirectResponse(url="/ui/posts", status_code=302)
    
    try:
        locale = get_locale_from_cookie(getattr(request, "cookies", None))
        tr = get_tr(locale)
    except Exception:
        from app.translations import RU
        locale = "ru"
        tr = RU
    
    # Валидация
    email = email.strip().lower()
    if not email or "@" not in email:
        return _templates.TemplateResponse(
            request,
            "register.html",
            {"error": tr.get("register_error_invalid_email", "Invalid email"), "auth_configured": True, "locale": locale, "tr": tr},
            status_code=400,
        )
    
    if len(password) < 6:
        return _templates.TemplateResponse(
            request,
            "register.html",
            {"error": tr.get("register_error_short_password", "Password must be at least 6 characters"), "auth_configured": True, "locale": locale, "tr": tr},
            status_code=400,
        )
    
    if password != password_confirm:
        return _templates.TemplateResponse(
            request,
            "register.html",
            {"error": tr.get("register_error_password_mismatch", "Passwords do not match"), "auth_configured": True, "locale": locale, "tr": tr},
            status_code=400,
        )
    
    # Проверка существующего пользователя
    r = await session.execute(select(User).where(User.email == email))
    existing = r.scalar_one_or_none()
    if existing:
        return _templates.TemplateResponse(
            request,
            "register.html",
            {"error": tr.get("register_error_email_exists", "Email already registered"), "auth_configured": True, "locale": locale, "tr": tr},
            status_code=400,
        )
    
    # Создание пользователя (статус «ожидает подтверждения»)
    user = User(
        email=email,
        password_hash=_hash_password(password),
        role=UserRole.USER.value,
        approval_status=UserApprovalStatus.PENDING.value,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    
    # Перенаправление на страницу «ждём подтверждения» (без входа)
    return RedirectResponse(url="/register/pending", status_code=302)


@router.get("/logout")
@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    locale = get_locale_from_cookie(request.cookies)
    return RedirectResponse(url="/en" if locale == "en" else "/", status_code=302)
