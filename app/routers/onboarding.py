# app/routers/onboarding.py — fingerprint онбординг (63 вопроса)
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user_id
from app.models import KnowledgeBase
from app.onboarding_questions import EXTRA_QUESTIONS, ONBOARDING_QUESTIONS, get_all_questions_flat

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

FINGERPRINT_KEY = "fingerprint"


def _kb_key(user_id: int) -> str:
    return f"{FINGERPRINT_KEY}:{user_id}"


def _set_nested(d: dict, path: str, value: Any) -> None:
    """Set nested key: 'background.region_vibe' -> d['background']['region_vibe'] = value."""
    parts = path.split(".")
    cur = d
    for i, part in enumerate(parts[:-1]):
        if part not in cur:
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def _build_fingerprint_from_responses(responses: Dict[str, Any]) -> Dict[str, Any]:
    """Build nested fingerprint from flat {store_to: value} responses."""
    fp = {}
    for store_to, value in responses.items():
        if store_to and value is not None:
            _set_nested(fp, store_to, value)
    return fp


@router.get("/questions")
async def get_onboarding_questions():
    """Возвращает все 63 вопроса + 2 дополнительных (для продукта)."""
    return {
        "questions": ONBOARDING_QUESTIONS,
        "extra": EXTRA_QUESTIONS,
    }


@router.get("/questions/flat")
async def get_onboarding_questions_flat(locale: Optional[str] = None):
    """Плоский список всех вопросов для пошагового UI в модалке.
    locale: ru | en — из query. По умолчанию ru."""
    loc = (locale or "ru").strip().lower()
    loc = "en" if loc == "en" else "ru"
    return {"questions": get_all_questions_flat(loc)}


@router.get("/fingerprint")
async def get_fingerprint(
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """Возвращает сохранённый fingerprint пользователя."""
    key = _kb_key(user_id)
    r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == key))
    row = r.scalar_one_or_none()
    if not row or not row.value:
        return {}
    try:
        return json.loads(row.value)
    except Exception:
        return {}


@router.delete("/fingerprint")
async def delete_fingerprint(
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """Удаляет fingerprint (для тестирования состояния «до интервью»)."""
    key = _kb_key(user_id)
    r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == key))
    row = r.scalar_one_or_none()
    if row:
        await session.delete(row)
        await session.commit()
    return {"ok": True}


@router.post("/fingerprint")
async def save_fingerprint(
    body: Dict[str, Any],
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """
    Сохраняет fingerprint. Body: { "store_to_path": value, ... }.
    Значения мержатся в вложенный dict по ключу.
    """
    key = _kb_key(user_id)
    r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == key))
    row = r.scalar_one_or_none()
    existing = {}
    if row and row.value:
        try:
            existing = json.loads(row.value)
        except Exception:
            pass

    fp = _build_fingerprint_from_responses(body)
    merged = _deep_merge(existing, fp)
    value = json.dumps(merged, ensure_ascii=False)
    if row:
        row.value = value
    else:
        session.add(KnowledgeBase(key=key, value=value))
    await session.commit()
    return {"ok": True, "fingerprint": merged}


def _deep_merge(base: dict, update: dict) -> dict:
    """Deep merge update into base."""
    result = dict(base)
    for k, v in update.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
