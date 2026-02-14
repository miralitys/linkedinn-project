# app/routers/linkedin_oauth.py
"""
LinkedIn OAuth 2.0 + Community Management API (memberCreatorPostAnalytics).
Токены хранятся в БД, по таймеру обновляются и дергается GET memberCreatorPostAnalytics,
результаты пишутся в linkedin_daily_metrics.
"""
import logging
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import LinkedInDailyMetric, LinkedInOAuth, LinkedInPostDailyMetric
from app.services.crypto import decrypt_token, encrypt_token

router = APIRouter(prefix="/linkedin", tags=["linkedin"])

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_API_BASE = "https://api.linkedin.com/rest"
# Для продукта "Sign In with LinkedIn using OpenID Connect" часто нужны openid + profile
SCOPE = "openid profile"  # только вход (минимальный набор для OIDC)
SCOPE_FULL = "openid profile r_member_postAnalytics"  # вход + метрики постов (нужен Share on LinkedIn)
METRIC_TYPES = ("IMPRESSION", "MEMBERS_REACHED", "RESHARE", "REACTION", "COMMENT")


def _linkedin_version() -> str:
    return datetime.utcnow().strftime("%Y%m")


async def _get_valid_token(session: AsyncSession) -> Optional[str]:
    """Возвращает актуальный access_token (обновляет по refresh_token при необходимости)."""
    r = await session.execute(select(LinkedInOAuth).limit(1))
    row = r.scalar_one_or_none()
    if not row:
        return None
    now = datetime.utcnow()
    if row.expires_at and (row.expires_at - now).total_seconds() < 300:
        if not row.refresh_token or not settings.linkedin_client_id or not settings.linkedin_client_secret:
            return None
        refresh_plain = decrypt_token(row.refresh_token, settings.token_encryption_key)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                LINKEDIN_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_plain,
                    "client_id": settings.linkedin_client_id,
                    "client_secret": settings.linkedin_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code != 200:
            logging.warning("LinkedIn token refresh failed: %s %s", resp.status_code, resp.text)
            return None
        data = resp.json()
        row.access_token = encrypt_token(data["access_token"], settings.token_encryption_key)
        row.expires_at = now + timedelta(seconds=data.get("expires_in", 5184000))
        if "refresh_token" in data:
            row.refresh_token = encrypt_token(data["refresh_token"], settings.token_encryption_key)
        if "refresh_token_expires_in" in data:
            row.refresh_token_expires_at = now + timedelta(seconds=data["refresh_token_expires_in"])
    return decrypt_token(row.access_token, settings.token_encryption_key)


def _normalize_redirect_uri(uri: Optional[str]) -> Optional[str]:
    """Без слэша в конце — LinkedIn сравнивает строго."""
    if not uri:
        return None
    return uri.rstrip("/")


def _extract_entity_from_post_ref(post_ref: str) -> tuple[str, str]:
    """
    Преобразует URL/URN поста в entity для q=entity:
    - (share:urn:li:share:...)
    - (ugc:urn:li:ugcPost:...)
    """
    ref = (post_ref or "").strip()
    if not ref:
        raise ValueError("post_ref is empty")

    m_share = re.search(r"urn:li:share:(\d+)", ref, re.I)
    if m_share:
        return "share", f"urn:li:share:{m_share.group(1)}"

    m_ugc = re.search(r"urn:li:ugcPost:(\d+)", ref, re.I)
    if m_ugc:
        return "ugc", f"urn:li:ugcPost:{m_ugc.group(1)}"

    # Часто в UI/URL встречается activity-URN; для memberCreatorPostAnalytics используем share URN.
    m_activity = re.search(r"urn:li:activity:(\d+)", ref, re.I)
    if m_activity:
        return "share", f"urn:li:share:{m_activity.group(1)}"

    m_posts_activity = re.search(r"activity-(\d+)", ref, re.I)
    if m_posts_activity:
        return "share", f"urn:li:share:{m_posts_activity.group(1)}"

    raise ValueError("Unsupported LinkedIn post URL/URN format")


async def get_my_post_refs_from_linkedin_api(
    session: AsyncSession,
    count: int = 12,
) -> list[str]:
    """
    Возвращает ссылки/URN последних постов текущего пользователя напрямую из LinkedIn API.
    Требует доступный OAuth токен.
    """
    token = await _get_valid_token(session)
    if not token:
        raise RuntimeError("LinkedIn not connected")

    version = _linkedin_version()
    headers = {
        "Authorization": f"Bearer {token}",
        "Linkedin-Version": version,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }

    # OIDC userinfo -> sub => urn:li:person:{sub}
    async with httpx.AsyncClient() as client:
        me_resp = await client.get("https://api.linkedin.com/v2/userinfo", headers=headers)
    if me_resp.status_code != 200:
        raise RuntimeError(f"LinkedIn userinfo failed: {me_resp.status_code}")
    me = me_resp.json()
    sub = (me.get("sub") or "").strip()
    if not sub:
        raise RuntimeError("LinkedIn userinfo missing sub")
    author_urn = f"urn:li:person:{sub}"

    encoded_author = quote(author_urn, safe="")
    safe_count = max(1, min(int(count or 12), 50))
    url = f"{LINKEDIN_API_BASE}/posts?q=author&author={encoded_author}&count={safe_count}"

    async with httpx.AsyncClient() as client:
        posts_resp = await client.get(url, headers=headers)
    if posts_resp.status_code != 200:
        raise RuntimeError(f"LinkedIn posts API failed: {posts_resp.status_code} {posts_resp.text[:160]}")

    data = posts_resp.json()
    elements = data.get("elements") or []
    refs: list[str] = []
    for el in elements:
        # В Posts API id обычно urn:li:share:* или urn:li:ugcPost:*
        post_id = (el.get("id") or "").strip()
        if post_id and (post_id.startswith("urn:li:share:") or post_id.startswith("urn:li:ugcPost:")):
            refs.append(post_id)
    # Удаляем дубли, сохраняя порядок.
    uniq: list[str] = []
    seen = set()
    for r in refs:
        if r in seen:
            continue
        seen.add(r)
        uniq.append(r)
    return uniq


@router.get("/oauth/setup")
async def linkedin_oauth_setup():
    """Точный redirect_uri и client_id для настройки в LinkedIn Developer Portal."""
    redirect_uri = _normalize_redirect_uri(settings.linkedin_redirect_uri)
    return {
        "client_id": settings.linkedin_client_id or None,
        "redirect_uri": redirect_uri,
        "hint": "В приложении LinkedIn: Auth → Authorized redirect URLs — добавьте redirect_uri выше (без слэша в конце). Нужен продукт Sign In with LinkedIn.",
    }


def _build_authorize_url(redirect_uri: str, state: str, scope: str = SCOPE) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.linkedin_client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
    }
    return f"{LINKEDIN_AUTH_URL}?{urlencode(params)}"


@router.get("/oauth/debug-url")
async def linkedin_oauth_debug_url():
    """Точный URL авторизации для проверки (скопируйте и откройте в браузере)."""
    if not settings.linkedin_client_id or not settings.linkedin_redirect_uri:
        return {"error": "LINKEDIN_CLIENT_ID или LINKEDIN_REDIRECT_URI не заданы"}
    redirect_uri = _normalize_redirect_uri(settings.linkedin_redirect_uri)
    state = "debug"
    return {
        "authorization_url": _build_authorize_url(redirect_uri, state, SCOPE),
        "authorization_url_with_metrics": _build_authorize_url(redirect_uri, state, SCOPE_FULL),
        "redirect_uri_sent": redirect_uri,
        "client_id": settings.linkedin_client_id,
        "scope_default": SCOPE,
        "scope_full": SCOPE_FULL,
    }


@router.get("/oauth/authorize")
async def linkedin_authorize(
    request: Request,
    metrics: Optional[str] = None,
):
    """Редирект на LinkedIn. По умолчанию scope=openid (только вход). ?metrics=1 — openid + r_member_postAnalytics."""
    if not settings.linkedin_client_id or not settings.linkedin_redirect_uri:
        return RedirectResponse(url="/ui/setup?linkedin=config", status_code=302)
    redirect_uri = _normalize_redirect_uri(settings.linkedin_redirect_uri)
    state = secrets.token_urlsafe(16)
    request.session["linkedin_oauth_state"] = state
    scope = SCOPE_FULL if metrics == "1" else SCOPE
    url = _build_authorize_url(redirect_uri, state, scope)
    return RedirectResponse(url=url, status_code=302)


@router.get("/oauth/callback")
async def linkedin_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """Обмен code на токены и сохранение в linkedin_oauth."""
    if error:
        desc = quote(error_description or "", safe="")
        return RedirectResponse(url=f"/ui/setup?linkedin=denied&error={quote(error, safe='')}&error_description={desc}", status_code=302)
    saved_state = request.session.get("linkedin_oauth_state")
    if not state or state != saved_state or not code:
        return RedirectResponse(url="/ui/setup?linkedin=error", status_code=302)
    if not settings.linkedin_client_id or not settings.linkedin_client_secret or not settings.linkedin_redirect_uri:
        return RedirectResponse(url="/ui/setup?linkedin=config", status_code=302)
    redirect_uri = _normalize_redirect_uri(settings.linkedin_redirect_uri)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": settings.linkedin_client_id,
                "client_secret": settings.linkedin_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code != 200:
        logging.warning("LinkedIn token exchange failed: %s %s", resp.status_code, resp.text)
        return RedirectResponse(url="/ui/setup?linkedin=token_failed", status_code=302)
    data = resp.json()
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=data.get("expires_in", 5184000))
    refresh_expires = None
    if "refresh_token_expires_in" in data:
        refresh_expires = now + timedelta(seconds=data["refresh_token_expires_in"])
    r = await session.execute(select(LinkedInOAuth).limit(1))
    existing = r.scalar_one_or_none()
    if existing:
        existing.access_token = encrypt_token(data["access_token"], settings.token_encryption_key)
        if data.get("refresh_token"):
            existing.refresh_token = encrypt_token(data["refresh_token"], settings.token_encryption_key)
        existing.expires_at = expires_at
        existing.refresh_token_expires_at = refresh_expires or existing.refresh_token_expires_at
        existing.scope = data.get("scope", "")
    else:
        session.add(
            LinkedInOAuth(
                access_token=encrypt_token(data["access_token"], settings.token_encryption_key),
                refresh_token=encrypt_token(data["refresh_token"], settings.token_encryption_key) if data.get("refresh_token") else None,
                expires_at=expires_at,
                refresh_token_expires_at=refresh_expires,
                scope=data.get("scope", ""),
            )
        )
    return RedirectResponse(url="/ui/setup?linkedin=connected", status_code=302)


@router.get("/status")
async def linkedin_status(session: AsyncSession = Depends(get_session)):
    """Проверка: подключён ли LinkedIn (есть ли токен)."""
    r = await session.execute(select(LinkedInOAuth).limit(1))
    row = r.scalar_one_or_none()
    return {"connected": row is not None}


@router.post("/disconnect")
async def linkedin_disconnect(session: AsyncSession = Depends(get_session)):
    """Отключить LinkedIn: удалить токен из БД."""
    r = await session.execute(select(LinkedInOAuth))
    rows = list(r.scalars().all())
    for row in rows:
        await session.delete(row)
    await session.commit()
    return {"connected": False}


@router.get("/metrics")
async def linkedin_metrics(
    days: int = 30,
    session: AsyncSession = Depends(get_session),
):
    """Список метрик из linkedin_daily_metrics за последние days дней."""
    since = datetime.utcnow() - timedelta(days=days)
    q = (
        select(LinkedInDailyMetric)
        .where(LinkedInDailyMetric.metric_date >= since)
        .order_by(LinkedInDailyMetric.metric_date.desc(), LinkedInDailyMetric.metric_type)
    )
    r = await session.execute(q)
    rows = r.scalars().all()
    return [
        {"metric_date": m.metric_date.isoformat()[:10], "metric_type": m.metric_type, "count": m.count}
        for m in rows
    ]


@router.get("/post-metrics")
async def linkedin_post_metrics(
    post_url: str,
    days: int = 30,
    save_history: bool = True,
    session: AsyncSession = Depends(get_session),
):
    """
    Метрики конкретного поста LinkedIn (lifetime TOTAL) через memberCreatorPostAnalytics q=entity.
    post_url может быть LinkedIn URL или URN.
    """
    try:
        return await sync_post_metrics_for_ref(session, post_url=post_url, days=days, save_history=save_history)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def sync_post_metrics_for_ref(
    session: AsyncSession,
    post_url: str,
    days: int = 30,
    save_history: bool = True,
) -> dict:
    """Синк и чтение метрик для конкретного поста (служебная функция для API/страниц)."""
    token = await _get_valid_token(session)
    if not token:
        raise RuntimeError("LinkedIn not connected")

    entity_type, entity_urn = _extract_entity_from_post_ref(post_url)
    version = _linkedin_version()
    headers = {
        "Authorization": f"Bearer {token}",
        "Linkedin-Version": version,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }
    encoded_urn = quote(entity_urn, safe="")
    entity_param = f"({entity_type}:{encoded_urn})"

    async def _fetch_metric(metric_type: str, aggregation: str, date_range: Optional[str] = None) -> tuple[int, list, Optional[str]]:
        url = (
            f"{LINKEDIN_API_BASE}/memberCreatorPostAnalytics"
            f"?q=entity&entity={entity_param}&queryType={metric_type}&aggregation={aggregation}"
        )
        if date_range:
            url += f"&dateRange={date_range}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return 0, [], f"{resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            elements = data.get("elements") or []
            total_count = 0
            for el in elements:
                total_count += int(el.get("count", 0) or 0)
            return total_count, elements, None
        except Exception as e:
            return 0, [], str(e)

    results: dict[str, int] = {}
    errors: dict[str, str] = {}
    for metric_type in METRIC_TYPES:
        total_count, _, err = await _fetch_metric(metric_type, "TOTAL")
        if err:
            errors[metric_type] = err
            continue
        results[metric_type] = total_count

    saved_rows = 0
    if save_history:
        safe_days = max(1, min(days, 90))
        end = datetime.utcnow()
        start = end - timedelta(days=safe_days)
        date_range = (
            f"(start:(year:{start.year},month:{start.month},day:{start.day}),"
            f"end:(year:{end.year},month:{end.month},day:{end.day}))"
        )
        for metric_type in METRIC_TYPES:
            _, elements, err = await _fetch_metric(metric_type, "DAILY", date_range=date_range)
            if err:
                errors.setdefault(metric_type, err)
                continue
            for el in elements:
                dr = el.get("dateRange") or {}
                start_d = dr.get("start") or {}
                y = start_d.get("year")
                m = start_d.get("month")
                d = start_d.get("day")
                if not (y and m and d):
                    continue
                metric_date = datetime(y, m, d)
                count = int(el.get("count", 0) or 0)
                existing = await session.execute(
                    select(LinkedInPostDailyMetric).where(
                        LinkedInPostDailyMetric.post_urn == entity_urn,
                        LinkedInPostDailyMetric.metric_date == metric_date,
                        LinkedInPostDailyMetric.metric_type == metric_type,
                    )
                )
                row = existing.scalar_one_or_none()
                if row is None:
                    session.add(
                        LinkedInPostDailyMetric(
                            post_urn=entity_urn,
                            entity_type=entity_type,
                            source_post_url=post_url,
                            metric_date=metric_date,
                            metric_type=metric_type,
                            count=count,
                        )
                    )
                    saved_rows += 1
                else:
                    row.count = count
                    row.source_post_url = post_url
                    row.entity_type = entity_type
        await session.commit()

    if not results:
        raise RuntimeError("LinkedIn metrics fetch failed")

    safe_days = max(1, min(days, 365))
    since = datetime.utcnow() - timedelta(days=safe_days)
    hist_q = (
        select(LinkedInPostDailyMetric)
        .where(
            LinkedInPostDailyMetric.post_urn == entity_urn,
            LinkedInPostDailyMetric.metric_date >= since,
        )
        .order_by(LinkedInPostDailyMetric.metric_date.asc(), LinkedInPostDailyMetric.metric_type.asc())
    )
    hist_r = await session.execute(hist_q)
    history_rows = hist_r.scalars().all()
    history_daily = [
        {
            "metric_date": h.metric_date.isoformat()[:10],
            "metric_type": h.metric_type,
            "count": h.count,
        }
        for h in history_rows
    ]

    return {
        "entity_type": entity_type,
        "entity_urn": entity_urn,
        "metrics": results,
        "history_daily": history_daily,
        "saved_rows": saved_rows,
        "errors": errors,
    }


async def run_linkedin_analytics_sync() -> None:
    """Задача по расписанию: обновить токен, вызвать memberCreatorPostAnalytics (q=me), записать в linkedin_daily_metrics."""
    from app.db import session_scope

    async with session_scope() as session:
        token = await _get_valid_token(session)
        if not token:
            logging.debug("LinkedIn: no valid token, skip analytics sync")
            return
        end = datetime.utcnow()
        start = end - timedelta(days=7)
        version = _linkedin_version()
        headers = {
            "Authorization": f"Bearer {token}",
            "Linkedin-Version": version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }
        for metric_type in METRIC_TYPES:
            try:
                date_range = (
                    f"(start:(year:{start.year},month:{start.month},day:{start.day}),"
                    f"end:(year:{end.year},month:{end.month},day:{end.day}))"
                )
                url = (
                    f"{LINKEDIN_API_BASE}/memberCreatorPostAnalytics"
                    f"?q=me&queryType={metric_type}&aggregation=DAILY&dateRange={date_range}"
                )
                async with httpx.AsyncClient() as client:
                    r = await client.get(url, headers=headers)
                if r.status_code != 200:
                    logging.warning("LinkedIn analytics %s: %s %s", metric_type, r.status_code, r.text[:200])
                    continue
                data = r.json()
                elements = data.get("elements") or []
                for el in elements:
                    count = el.get("count", 0)
                    dr = el.get("dateRange") or {}
                    start_d = dr.get("start") or {}
                    y = start_d.get("year")
                    m = start_d.get("month")
                    d = start_d.get("day")
                    if y and m and d:
                        metric_date = datetime(y, m, d)
                        existing = await session.execute(
                            select(LinkedInDailyMetric).where(
                                LinkedInDailyMetric.metric_date == metric_date,
                                LinkedInDailyMetric.metric_type == metric_type,
                            )
                        )
                        if existing.scalar_one_or_none() is None:
                            session.add(
                                LinkedInDailyMetric(metric_date=metric_date, metric_type=metric_type, count=count)
                            )
            except Exception as e:
                logging.exception("LinkedIn analytics %s: %s", metric_type, e)
        await session.commit()
