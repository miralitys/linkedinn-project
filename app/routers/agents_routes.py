# app/routers/agents_routes.py
from __future__ import annotations
import json
import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session, session_scope
from app.deps import get_current_user_id
from app.models import ContactPost, Draft, DraftStatus, DraftType, KnowledgeBase, SalesAvatar
from app.plans import get_plan
from app.services.usage import GENERATION_AGENTS, check_generation_limit, increment_usage
from app.services.comment_jobs import (
    create_comment_job,
    get_comment_job,
    mark_comment_job_done,
    mark_comment_job_error,
)
from app.routers.setup import _kb_key
from app.schemas import AgentRunPayload, AgentRunResponse
from agents.llm_client import get_llm_client
from agents.comment_pipeline.pipeline import prepare_comment_pipeline, finalize_comment_variants
from agents.registry import AGENTS, run_agent

router = APIRouter(prefix="/agents", tags=["agents"])
_LOG = logging.getLogger(__name__)


def _avatar_to_str(avatar) -> str:
    if not avatar:
        return ""
    parts = []
    if avatar.positioning:
        parts.append(f"Positioning: {avatar.positioning}")
    if avatar.tone_guidelines:
        parts.append(f"Tone: {avatar.tone_guidelines}")
    if avatar.do_say:
        parts.append("Do say: " + ", ".join(avatar.do_say))
    if avatar.dont_say:
        parts.append("Don't say: " + ", ".join(avatar.dont_say))
    return "\n".join(parts)


def _merge_reply_variants(existing: object, patch: dict[str, str]) -> dict[str, str]:
    base = existing if isinstance(existing, dict) else {}
    merged = {
        "short": (patch.get("short") if patch.get("short") is not None else base.get("short", "")) or "",
        "medium": (patch.get("medium") if patch.get("medium") is not None else base.get("medium", "")) or "",
        "long": (patch.get("long") if patch.get("long") is not None else base.get("long", "")) or "",
    }
    return merged


async def _complete_comment_fast_job(
    *,
    job_id: str,
    user_id: int,
    post_id: int,
    short_text: str,
    pipeline_ctx: dict,
    llm_provider: str | None = None,
) -> None:
    try:
        llm = get_llm_client(provider=llm_provider) if llm_provider else None
        medium_long = await finalize_comment_variants(
            pipeline_ctx,
            variants=["medium", "long"],
            fallback_variants={"medium", "long"},
            llm=llm,
        )
        async with session_scope() as bg_session:
            q = (
                select(ContactPost)
                .options(selectinload(ContactPost.person))
                .where(ContactPost.id == post_id)
            )
            r = await bg_session.execute(q)
            post = r.scalar_one_or_none()
            if not post:
                await mark_comment_job_error(job_id, error="post_not_found")
                return
            if post.person and post.person.user_id is not None and post.person.user_id != user_id:
                await mark_comment_job_error(job_id, error="post_forbidden")
                return
            merged = _merge_reply_variants(
                post.reply_variants,
                {
                    "short": short_text or "",
                    "medium": medium_long.get("medium", ""),
                    "long": medium_long.get("long", ""),
                },
            )
            post.reply_variants = merged
        ready = [k for k in ("short", "medium", "long") if (merged.get(k) or "").strip()]
        await mark_comment_job_done(job_id, ready_variants=ready, pending_variants=[])
    except Exception as e:
        _LOG.exception("Fast comment background job failed: %s", e)
        await mark_comment_job_error(job_id, error=str(e))


async def _run_comment_agent_fast(
    payload: dict,
    session: AsyncSession,
    user_id: int,
) -> dict:
    post_id_raw = payload.get("post_id")
    try:
        post_id = int(post_id_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="post_id is required for fast_mode")

    q = (
        select(ContactPost)
        .options(selectinload(ContactPost.person))
        .where(ContactPost.id == post_id)
    )
    r = await session.execute(q)
    post = r.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.person and post.person.user_id is not None and post.person.user_id != user_id:
        raise HTTPException(status_code=404, detail="Post not found")

    post_text = (payload.get("post_text") or post.content or "").strip()
    if not post_text:
        return {
            "comments": {"short": "", "medium": "", "long": ""},
            "raw": "",
            "background_pending": False,
            "post_id": post_id,
        }

    goal = payload.get("goal") or "network"
    author = payload.get("author") if isinstance(payload.get("author"), dict) else None
    products = payload.get("products") if isinstance(payload.get("products"), list) else []
    answers_66 = payload.get("author_answers_66") or payload.get("fingerprint") or {}
    prompt_version = (payload.get("prompt_version") or "default").strip() or "default"
    llm_provider = payload.get("llm_provider")
    llm = get_llm_client(provider=llm_provider) if llm_provider else None

    pipeline_ctx = await prepare_comment_pipeline(
        post_text=post_text,
        author_answers_66=answers_66,
        products=products,
        mode=goal,
        author=author,
        prompt_version=prompt_version,
        llm=llm,
    )
    short_result = await finalize_comment_variants(
        pipeline_ctx,
        variants=["short"],
        fallback_variants=set(),
        llm=llm,
    )
    short_text = (short_result.get("short") or "").strip()
    merged_short = _merge_reply_variants(
        post.reply_variants,
        {"short": short_text, "medium": None, "long": None},
    )
    post.reply_variants = merged_short
    await session.commit()

    job = await create_comment_job(
        user_id=user_id,
        post_id=post_id,
        post_title=post.title or "",
        ready_variants=[k for k in ("short",) if (merged_short.get(k) or "").strip()],
        pending_variants=["medium", "long"],
    )
    job_id = job["job_id"]
    asyncio.create_task(
        _complete_comment_fast_job(
            job_id=job_id,
            user_id=user_id,
            post_id=post_id,
            short_text=merged_short.get("short", ""),
            pipeline_ctx=pipeline_ctx,
            llm_provider=llm_provider,
        )
    )

    return {
        "comments": merged_short,
        "raw": str(merged_short),
        "background_pending": True,
        "job_id": job_id,
        "post_id": post_id,
        "post_title": post.title or "",
    }


@router.post("/{agent_name}/run", response_model=AgentRunResponse)
async def run_agent_endpoint(
    agent_name: str,
    body: AgentRunPayload,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    try:
        return await _run_agent_impl(agent_name, body, session, user_id)
    except HTTPException:
        raise
    except Exception as e:
        _LOG.exception("Agent %s failed: %s", agent_name, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/comment_agent/jobs/{job_id}")
async def get_comment_agent_job_status(
    job_id: str,
    user_id: int = Depends(get_current_user_id),
):
    job = await get_comment_job(job_id, user_id=user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _run_agent_impl(
    agent_name: str,
    body: AgentRunPayload,
    session: AsyncSession,
    user_id: int,
) -> AgentRunResponse:
    if agent_name not in AGENTS:
        raise HTTPException(404, f"Unknown agent: {agent_name}")
    payload = body.payload or {}

    # Проверка лимита генераций для content-агентов
    if agent_name in GENERATION_AGENTS:
        ok, current, limit = await check_generation_limit(session, user_id, agent_name)
        if not ok:
            raise HTTPException(
                status_code=403,
                detail=f"Limit reached: {current}/{limit} this month. Upgrade your plan.",
            )

    # Inject shared memory (Sales Avatar) when needed
    if agent_name in ("content_agent", "comment_agent", "news_post_agent", "outreach_sequencer", "qa_guard"):
        try:
            r = await session.execute(select(SalesAvatar).where(SalesAvatar.user_id == user_id).limit(1))
            avatar = r.scalar_one_or_none()
            if avatar and "sales_avatar" not in payload and "context" not in payload:
                payload.setdefault("sales_avatar", _avatar_to_str(avatar))
                payload.setdefault("context", _avatar_to_str(avatar))
        except Exception:
            pass  # Продолжаем без avatar

    # Inject fingerprint + products for comment_agent
    if agent_name == "comment_agent":
        try:
            fp_key = f"fingerprint:{user_id}"
            r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == fp_key))
            row = r.scalar_one_or_none()
            if row and row.value and "author_answers_66" not in payload and "fingerprint" not in payload:
                try:
                    fingerprint = json.loads(row.value)
                    payload.setdefault("author_answers_66", fingerprint)
                    payload.setdefault("fingerprint", fingerprint)
                except Exception:
                    pass
            if not payload.get("products"):
                for base_key in ("setup_products", "products"):
                    key = _kb_key(base_key, user_id)
                    r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == key))
                    row = r.scalar_one_or_none()
                    if row and row.value:
                        try:
                            products = json.loads(row.value)
                            if isinstance(products, list) and products:
                                payload.setdefault("products", products)
                                break
                        except Exception:
                            pass
        except Exception:
            pass

    # Inject setup data (authors, products, ICP) for scoring_agent
    if agent_name == "scoring_agent":
        draft_data = {}
        key_sets = {
            "authors": ["setup_authors", "authors"],
            "products": ["setup_products", "products"],
            "icp": ["setup_icp_raw"],
        }
        for section, keys in key_sets.items():
            row = None
            for base_key in keys:
                key = _kb_key(base_key, user_id)
                r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == key))
                row = r.scalar_one_or_none()
                if row and row.value:
                    break
            if row and row.value:
                import json
                try:
                    parsed = json.loads(row.value)
                    draft_data[section] = parsed if isinstance(parsed, list) else []
                except Exception:
                    draft_data[section] = []
            else:
                draft_data[section] = []
        if draft_data:
            # Формируем контекст для скорринга
            authors = draft_data.get("authors", [])
            products = draft_data.get("products", [])
            icp_list = draft_data.get("icp", [])
            
            # Берем первого автора как бизнес-контекст
            author_desc = ""
            if authors and len(authors) > 0:
                a = authors[0]
                author_desc = f"Имя: {a.get('full_name', '')}. Роль: {a.get('role', '')}. История: {a.get('history', '')}"
            
            # Формируем описание продуктов
            products_desc = ""
            if products and len(products) > 0:
                products_lines = []
                for p in products:
                    name = p.get("name", "") or ""
                    desc = p.get("description", "") or ""
                    products_lines.append(f"{name}" + (f" — {desc}" if desc else ""))
                products_desc = "\n".join(products_lines)
            
            # Формируем описание ICP
            icp_desc = ""
            if icp_list and len(icp_list) > 0:
                icp_lines = []
                for icp in icp_list:
                    parts = []
                    if icp.get("name"):
                        parts.append(f"Название: {icp['name']}")
                    if icp.get("roles"):
                        parts.append(f"Роли: {icp['roles']}")
                    if icp.get("industry"):
                        parts.append(f"Индустрия: {icp['industry']}")
                    if icp.get("size"):
                        parts.append(f"Размер: {icp['size']}")
                    if icp.get("geo"):
                        parts.append(f"Гео: {icp['geo']}")
                    if parts:
                        icp_lines.append(" | ".join(parts))
                icp_desc = "\n".join(icp_lines)
            
            payload.setdefault("author", author_desc)
            payload.setdefault("products", products_desc)
            payload.setdefault("icp", icp_desc)

    try:
        if agent_name == "comment_agent" and bool(payload.get("fast_mode")):
            result = await _run_comment_agent_fast(payload, session, user_id)
        else:
            result = await run_agent(agent_name, payload)
    except ValueError as e:
        msg = str(e)
        if "OPENROUTER_API_KEY" in msg and "not set" in msg.lower():
            raise HTTPException(
                status_code=503,
                detail="OPENROUTER_API_KEY is not set. Add OPENROUTER_API_KEY=sk-or-v1-... to your .env file (get a key at https://openrouter.ai) to enable AI rewrite.",
            )
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        import logging
        logging.exception("Agent %s failed: %s", agent_name, e)
        raise HTTPException(status_code=500, detail=str(e))
    draft_id = None

    # Save as draft when content is produced
    if agent_name == "content_agent" and result.get("content"):
        c = result["content"]
        draft = Draft(
            user_id=user_id,
            type=DraftType.POST.value,
            content=c.get("draft", ""),
            source_agent=agent_name,
            meta={"cta": c.get("cta"), "final_question": c.get("final_question"), "draft_short": c.get("draft_short"), "visual_suggestion": c.get("visual_suggestion")},
            status=DraftStatus.DRAFT.value,
        )
        session.add(draft)
        await session.flush()
        draft_id = draft.id
    elif agent_name == "comment_agent" and result.get("comments"):
        comm = result["comments"]
        text = comm.get("medium") or comm.get("short") or comm.get("long") or ""
        draft = Draft(
            user_id=user_id,
            type=DraftType.COMMENT.value,
            content=text,
            source_agent=agent_name,
            meta={"short": comm.get("short"), "long": comm.get("long")},
            status=DraftStatus.DRAFT.value,
        )
        session.add(draft)
        await session.flush()
        draft_id = draft.id
    elif agent_name == "news_post_agent" and result.get("post"):
        draft = Draft(
            user_id=user_id,
            type=DraftType.POST.value,
            content=result["post"],
            source_agent=agent_name,
            meta={},
            status=DraftStatus.DRAFT.value,
        )
        session.add(draft)
        await session.flush()
        draft_id = draft.id
    elif agent_name == "outreach_sequencer" and result.get("sequencer", {}).get("draft_message"):
        draft = Draft(
            user_id=user_id,
            type=DraftType.DM.value,
            content=result["sequencer"]["draft_message"],
            source_agent=agent_name,
            person_id=payload.get("person_id"),
            meta=result.get("sequencer"),
            status=DraftStatus.DRAFT.value,
        )
        session.add(draft)
        await session.flush()
        draft_id = draft.id

    # Учёт генерации (не блокируем ответ при ошибке)
    if agent_name in GENERATION_AGENTS:
        try:
            await increment_usage(session, user_id, agent_name, 1)
        except Exception:
            _LOG.warning("Failed to increment usage for %s", agent_name, exc_info=True)

    return AgentRunResponse(agent_name=agent_name, result=result, draft_id=draft_id)
