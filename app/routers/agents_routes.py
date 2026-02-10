# app/routers/agents_routes.py
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Draft, DraftStatus, DraftType, KnowledgeBase, SalesAvatar
from app.schemas import AgentRunPayload, AgentRunResponse
from agents.registry import AGENTS, run_agent

router = APIRouter(prefix="/agents", tags=["agents"])


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


@router.post("/{agent_name}/run", response_model=AgentRunResponse)
async def run_agent_endpoint(
    agent_name: str,
    body: AgentRunPayload,
    session: AsyncSession = Depends(get_session),
):
    if agent_name not in AGENTS:
        raise HTTPException(404, f"Unknown agent: {agent_name}")
    payload = body.payload or {}

    # Inject shared memory (Sales Avatar) when needed
    if agent_name in ("content_agent", "comment_agent", "news_post_agent", "outreach_sequencer", "qa_guard"):
        r = await session.execute(select(SalesAvatar).limit(1))
        avatar = r.scalar_one_or_none()
        if avatar and "sales_avatar" not in payload and "context" not in payload:
            payload.setdefault("sales_avatar", _avatar_to_str(avatar))
            payload.setdefault("context", _avatar_to_str(avatar))
    
    # Inject setup data (authors, products, ICP) for scoring_agent
    if agent_name == "scoring_agent":
        # Получаем данные из setup напрямую
        from app.models import KnowledgeBase
        draft_data = {}
        key_sets = {
            "authors": ["setup_authors", "authors"],
            "products": ["setup_products", "products"],
            "icp": ["setup_icp_raw"],
        }
        for section, keys in key_sets.items():
            row = None
            for key in keys:
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
        result = await run_agent(agent_name, payload)
    except Exception as e:
        import logging
        logging.exception("Agent %s failed: %s", agent_name, e)
        raise HTTPException(status_code=500, detail=str(e))
    draft_id = None

    # Save as draft when content is produced
    if agent_name == "content_agent" and result.get("content"):
        c = result["content"]
        draft = Draft(
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

    return AgentRunResponse(agent_name=agent_name, result=result, draft_id=draft_id)
