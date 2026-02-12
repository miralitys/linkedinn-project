# app/routers/drafts.py
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user_id
from app.models import Draft, DraftStatus, SalesAvatar
from app.schemas import DraftApproveRequest, DraftQARequest, DraftRead
from agents.registry import run_agent

router = APIRouter(prefix="/drafts", tags=["drafts"])


def _avatar_str(avatar) -> str:
    if not avatar:
        return ""
    return f"{avatar.positioning or ''}\n{avatar.tone_guidelines or ''}"


@router.get("", response_model=list)
async def list_drafts(
    status: Optional[str] = None,
    type: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    q = select(Draft).where((Draft.user_id == user_id) | (Draft.user_id.is_(None))).order_by(Draft.created_at.desc())
    if status:
        q = q.where(Draft.status == status)
    if type:
        q = q.where(Draft.type == type)
    r = await session.execute(q)
    return list(r.scalars().all())


@router.get("/{id}", response_model=DraftRead)
async def get_draft(id: int, session: AsyncSession = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    d = await session.get(Draft, id)
    if not d:
        raise HTTPException(404, "Draft not found")
    if d.user_id is not None and d.user_id != user_id:
        raise HTTPException(404, "Draft not found")
    return d


@router.post("/{id}/qa")
async def run_qa_on_draft(
    id: int,
  body: DraftQARequest,
  session: AsyncSession = Depends(get_session),
  user_id: int = Depends(get_current_user_id),
):
    """Run QA/Risk Guard on draft; store result in draft.qa_result."""
    d = await session.get(Draft, id)
    if not d:
        raise HTTPException(404, "Draft not found")
    if d.user_id is not None and d.user_id != user_id:
        raise HTTPException(404, "Draft not found")
    if not body.run_qa:
        return {"draft_id": id, "qa_run": False}
    r = await session.execute(select(SalesAvatar).where((SalesAvatar.user_id == user_id) | (SalesAvatar.user_id.is_(None))).limit(1))
    avatar = r.scalar_one_or_none()
    context = _avatar_str(avatar)
    result = await run_agent(
        "qa_guard",
        {"context": context, "content_type": d.type, "text": d.content},
    )
    d.qa_result = {
        "ok": result.get("ok", False),
        "risks": result.get("risks", {}),
        "fixes": result.get("fixes", []),
        "rewritten_text": result.get("rewritten_text"),
    }
    d.status = DraftStatus.QA_PENDING.value
    await session.commit()
    await session.refresh(d)
    return {"draft_id": id, "qa_result": d.qa_result, "draft": DraftRead.model_validate(d)}


@router.post("/{id}/approve")
async def approve_draft(
    id: int,
    body: DraftApproveRequest,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """Mark draft as approved or rejected."""
    d = await session.get(Draft, id)
    if not d:
        raise HTTPException(404, "Draft not found")
    if d.user_id is not None and d.user_id != user_id:
        raise HTTPException(404, "Draft not found")
    d.status = DraftStatus.APPROVED.value if body.approved else DraftStatus.REJECTED.value
    if body.note and d.meta is None:
        d.meta = {}
    if isinstance(d.meta, dict) and body.note:
        d.meta["approve_note"] = body.note
    await session.commit()
    await session.refresh(d)
    return {"draft_id": id, "status": d.status, "draft": DraftRead.model_validate(d)}
