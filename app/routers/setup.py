# app/routers/setup.py
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException

from app.db import get_session
from app.models import KnowledgeBase, LeadMagnet, Offer, SalesAvatar, Segment
from app.schemas import (
    LeadMagnetRead,
    OfferRead,
    SalesAvatarRead,
    SegmentRead,
    SetupSectionSave,
    SetupWizardInput,
)
from agents.registry import run_agent

router = APIRouter(prefix="/setup", tags=["setup"])

SETUP_KEYS = {"authors": "setup_authors", "products": "setup_products", "icp": "setup_icp_raw", "tone": "setup_tone", "goals": "setup_goals"}


async def get_setup_for_scoring(session: AsyncSession) -> dict:
    """Возвращает контекст для агента скоринга: author, products, icp (строки)."""
    key_sets = {
        "authors": ["setup_authors", "authors"],
        "products": ["setup_products", "products"],
        "icp": ["setup_icp_raw"],
    }
    draft = {}
    for section, keys in key_sets.items():
        row = None
        for key in keys:
            r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == key))
            row = r.scalar_one_or_none()
            if row and row.value:
                break
        if row and row.value:
            try:
                parsed = json.loads(row.value)
                draft[section] = parsed if isinstance(parsed, list) else []
            except Exception:
                draft[section] = []
        else:
            draft[section] = []

    authors = draft.get("authors", [])
    products = draft.get("products", [])
    icp_list = draft.get("icp", [])

    author_desc = ""
    if authors:
        a = authors[0]
        author_desc = f"Имя: {a.get('full_name', '')}. Роль: {a.get('role', '')}. История: {a.get('history', '')}"

    products_desc = ""
    if products:
        products_desc = "\n".join(
            f"{p.get('name', '')}" + (f" — {p.get('description', '')}" if p.get("description") else "")
            for p in products
        )

    icp_desc = ""
    if icp_list:
        icp_desc = "\n".join(
            " | ".join(
                f"{k}: {v}" for k, v in icp.items() if v and k in ("name", "roles", "industry", "size", "geo")
            )
            for icp in icp_list
            if isinstance(icp, dict)
        )

    return {"author": author_desc, "products": products_desc, "icp": icp_desc}


@router.get("/avatar", response_model=Optional[SalesAvatarRead])
async def get_avatar(session: AsyncSession = Depends(get_session)):
    """Return latest Sales Avatar (from last «Create skeleton»)."""
    r = await session.execute(select(SalesAvatar).order_by(SalesAvatar.id.desc()).limit(1))
    return r.scalar_one_or_none()


@router.get("/segments", response_model=list[SegmentRead])
async def list_segments(session: AsyncSession = Depends(get_session)):
    """Return all segments."""
    r = await session.execute(select(Segment).order_by(Segment.priority.desc(), Segment.id))
    return list(r.scalars().all())


@router.get("/offers", response_model=list[OfferRead])
async def list_offers(session: AsyncSession = Depends(get_session)):
    """Return all offers."""
    r = await session.execute(select(Offer).order_by(Offer.id))
    return list(r.scalars().all())


@router.get("/lead-magnets", response_model=list[LeadMagnetRead])
async def list_lead_magnets(session: AsyncSession = Depends(get_session)):
    """Return all lead magnets."""
    r = await session.execute(select(LeadMagnet).order_by(LeadMagnet.id))
    return list(r.scalars().all())


@router.get("/draft/debug")
async def get_setup_draft_debug(session: AsyncSession = Depends(get_session)):
    """Проверка: есть ли в БД записи авторов и продуктов (для отладки)."""
    async def _count(key: str) -> int:
        r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == key))
        row = r.scalar_one_or_none()
        if not row or not row.value:
            return 0
        try:
            data = json.loads(row.value)
            return len(data) if isinstance(data, list) else 0
        except Exception:
            return 0

    return {
        "setup_authors_count": await _count("setup_authors"),
        "setup_products_count": await _count("setup_products"),
        "legacy_authors_count": await _count("authors"),
        "legacy_products_count": await _count("products"),
    }


@router.get("/draft")
async def get_setup_draft(session: AsyncSession = Depends(get_session)):
    """Return saved draft for each section (authors, products, icp_raw, tone, goals)."""
    result = {}
    # authors: try setup_authors, then legacy "authors"
    key_sets = {
        "authors": ["setup_authors", "authors"],
        "products": ["setup_products", "products"],
        "icp": ["setup_icp_raw"],
        "tone": ["setup_tone"],
        "goals": ["setup_goals"],
    }
    for section, keys in key_sets.items():
        row = None
        for key in keys:
            r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == key))
            row = r.scalar_one_or_none()
            if row and row.value:
                break
        if row and row.value:
            if section == "authors":
                try:
                    result[section] = json.loads(row.value)
                except Exception:
                    result[section] = []
            elif section == "products":
                try:
                    result[section] = json.loads(row.value)
                except Exception:
                    result[section] = []
            elif section == "icp":
                try:
                    parsed = json.loads(row.value)
                    result[section] = parsed if isinstance(parsed, list) else []
                except Exception:
                    result[section] = []
            elif section in ("tone", "goals"):
                try:
                    parsed = json.loads(row.value)
                    result[section] = parsed if isinstance(parsed, list) else [row.value] if row.value else []
                except Exception:
                    result[section] = [row.value] if row.value else []
            else:
                result[section] = row.value
        else:
            if section == "tone" or section == "goals":
                result[section] = []
            elif section in ("authors", "products", "icp"):
                result[section] = []
            else:
                result[section] = ""
    return result


SUBREDDITS_KEY = "saved_subreddits"


async def _get_subreddits_list(session: AsyncSession) -> list:
    r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == SUBREDDITS_KEY))
    row = r.scalar_one_or_none()
    if not row or not row.value:
        return []
    try:
        data = json.loads(row.value)
        return list(data) if isinstance(data, list) else []
    except Exception:
        return []


async def _save_subreddits_list(session: AsyncSession, names: list) -> None:
    r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == SUBREDDITS_KEY))
    row = r.scalar_one_or_none()
    value = json.dumps(names)
    if row:
        row.value = value
    else:
        session.add(KnowledgeBase(key=SUBREDDITS_KEY, value=value))
    await session.commit()


@router.get("/subreddits")
async def list_setup_subreddits(session: AsyncSession = Depends(get_session)):
    """Список сохранённых сабреддитов (из KnowledgeBase)."""
    names = await _get_subreddits_list(session)
    return sorted(set(names))


@router.post("/subreddits")
async def add_setup_subreddit(body: dict, session: AsyncSession = Depends(get_session)):
    """Добавить сабреддит. Body: {"name": "python"}."""
    raw = (body.get("name") or "").strip().lower().replace("/r/", "").split("/")[0]
    if not raw:
        raise HTTPException(400, "Укажите имя сабреддита")
    names = await _get_subreddits_list(session)
    if raw in names:
        return {"ok": True, "name": raw, "message": "Уже в списке"}
    names.append(raw)
    await _save_subreddits_list(session, sorted(set(names)))
    return {"ok": True, "name": raw}


@router.delete("/subreddits/{name:path}", status_code=204)
async def remove_setup_subreddit(name: str, session: AsyncSession = Depends(get_session)):
    """Удалить сабреддит из списка."""
    sub = (name or "").strip().lower().replace("/r/", "").split("/")[0]
    if not sub:
        raise HTTPException(400, "Укажите имя сабреддита")
    names = await _get_subreddits_list(session)
    if sub not in names:
        raise HTTPException(404, "Сабреддит не найден в списке")
    names = [n for n in names if n != sub]
    await _save_subreddits_list(session, names)


@router.post("/section")
async def save_setup_section(
    body: SetupSectionSave,
    session: AsyncSession = Depends(get_session),
):
    """Save one section (products, icp, tone, goals) to draft."""
    try:
        if body.section not in SETUP_KEYS:
            return {"ok": False, "error": "Unknown section"}
        key = SETUP_KEYS[body.section]
        if body.section == "authors":
            value = json.dumps(body.value) if body.value is not None else "[]"
        elif body.section == "products":
            value = json.dumps(body.value) if body.value is not None else "[]"
        elif body.section == "icp":
            value = json.dumps(body.value) if isinstance(body.value, list) else str(body.value or "")
        elif body.section in ("tone", "goals"):
            value = json.dumps(body.value) if isinstance(body.value, list) else str(body.value or "")
        else:
            value = str(body.value) if body.value is not None else ""
        r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == key))
        row = r.scalar_one_or_none()
        if row:
            row.value = value
        else:
            session.add(KnowledgeBase(key=key, value=value))
        await session.commit()
        return {"ok": True, "section": body.section}
    except Exception as e:
        await session.rollback()
        return {"ok": False, "error": str(e)}


def _ensure_dict(v):
    """Ensure value is a dict or None for JSON columns."""
    if v is None:
        return None
    if isinstance(v, dict):
        return v
    return None


def _ensure_list(v):
    """Ensure value is a list or None for JSON columns."""
    if v is None:
        return None
    if isinstance(v, list):
        return v
    return None


def _ensure_str(v):
    """Ensure value is a string for Text columns (LLM may return list)."""
    if v is None:
        return None
    if isinstance(v, list):
        return "\n".join(str(x) for x in v)
    return str(v)


def _safe_int(v, default: int = 0) -> int:
    """Parse int from LLM output (may be number or text like 'Высокий')."""
    if v is None:
        return default
    if isinstance(v, int):
        return v
    try:
        return int(float(v)) if isinstance(v, (str, float)) else int(v)
    except (ValueError, TypeError):
        return default


@router.post("")
async def setup_wizard(
    body: SetupWizardInput,
    session: AsyncSession = Depends(get_session),
):
    """Onboarding: product, ICP, tone, goals -> SetupAgent -> create SalesAvatar, Segments, Offers, LeadMagnets."""
    try:
        result = await run_agent(
            "setup_agent",
            {
                "product": body.product,
                "icp_raw": body.icp_raw,
                "tone": body.tone,
                "goals": body.goals,
            },
        )
    except Exception as e:
        logging.exception("Setup wizard: agent failed")
        return {"ok": False, "error": f"Агент: {e!s}"}

    data = result.get("data")
    if not data:
        return {"ok": False, "error": result.get("error", "No data"), "raw": result.get("raw")}

    try:
        # Persist — Sales Avatar (single)
        av = data.get("sales_avatar") or {}
        avatar = SalesAvatar(
            name=str(av.get("name") or "Default")[:256],
            positioning=av.get("positioning"),
            tone_guidelines=av.get("tone_guidelines"),
            do_say=_ensure_list(av.get("do_say")),
            dont_say=_ensure_list(av.get("dont_say")),
            examples_good=_ensure_str(av.get("examples_good")),
            examples_bad=_ensure_str(av.get("examples_bad")),
        )
        session.add(avatar)
        await session.flush()

        for seg in data.get("segments") or []:
            s = Segment(
                name=str(seg.get("name") or "Segment")[:256],
                rules=_ensure_dict(seg.get("rules")),
                priority=_safe_int(seg.get("priority"), 0),
                red_flags=_ensure_str(seg.get("red_flags")),
                include_examples=_ensure_str(seg.get("include_examples")),
                exclude_examples=_ensure_str(seg.get("exclude_examples")),
            )
            session.add(s)
        await session.flush()

        for off in data.get("offers") or []:
            o = Offer(
                name=str(off.get("name") or "Offer")[:256],
                promise=_ensure_str(off.get("promise")),
                proof_points=_ensure_str(off.get("proof_points")),
                objections=_ensure_str(off.get("objections")),
                cta_style=(_ensure_str(off.get("cta_style")) or "")[:256] or None,
                notes=_ensure_str(off.get("notes")),
            )
            session.add(o)
        for lm in data.get("lead_magnets") or []:
            l = LeadMagnet(
                title=str(lm.get("title") or "Lead Magnet")[:512],
                format=lm.get("format"),
                description=_ensure_str(lm.get("description")),
                outline=_ensure_str(lm.get("outline")),
                notes=_ensure_str(lm.get("notes")),
            )
            session.add(l)
        await session.commit()
        return {"ok": True, "result": result}
    except Exception as e:
        await session.rollback()
        logging.exception("Setup wizard: persist failed")
        return {"ok": False, "error": f"Сохранение в БД: {e!s}"}
