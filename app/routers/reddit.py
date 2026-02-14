# app/routers/reddit.py
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session, session_scope
from app.deps import get_current_user_id
from app.models import KnowledgeBase, Person, RedditPost, SavedSubreddit, User
from app.plans import get_plan
from app.plans import get_plan
from app.services.limits import get_reddit_sources_count, get_sources_count
from app.routers.setup import _kb_key, get_setup_for_scoring
from app.schemas import RedditPostCreate, RedditPostRead, RedditPostUpdate, SavedSubredditAdd
from app.services.reddit_feed import fetch_subreddit_posts
from agents.registry import run_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reddit", tags=["reddit"])


def _reply_variants_post(rv: any) -> str:
    """Извлечь текст сгенерированного поста из reply_variants (dict или JSON-строка)."""
    try:
        if rv is None:
            return ""
        if isinstance(rv, dict):
            return (rv.get("post") or "").strip()
        if isinstance(rv, str):
            try:
                data = json.loads(rv)
                return (data.get("post") or "").strip() if isinstance(data, dict) else ""
            except (json.JSONDecodeError, TypeError):
                return ""
        return ""
    except Exception:
        return ""


def _has_generated_post(rv: any) -> bool:
    """Есть ли в reply_variants непустой сгенерированный текст (ключ post или любой непустой текст)."""
    try:
        if rv is None:
            return False
        text = _reply_variants_post(rv)
        if text:
            return True
        if isinstance(rv, dict):
            for v in rv.values():
                if isinstance(v, str) and v.strip():
                    return True
        if isinstance(rv, str):
            try:
                data = json.loads(rv)
                if isinstance(data, dict):
                    for v in data.values():
                        if isinstance(v, str) and v.strip():
                            return True
            except (json.JSONDecodeError, TypeError):
                pass
        return False
    except Exception:
        return False


def _reddit_post_to_read(p: RedditPost) -> RedditPostRead:
    try:
        rv_raw = getattr(p, "reply_variants", None)
        rv = rv_raw if isinstance(rv_raw, dict) else (json.loads(rv_raw) if isinstance(rv_raw, str) else None)
        if rv is not None and not isinstance(rv, dict):
            rv = None
        status_val = getattr(p, "status", None) or "new"
        if status_val not in ("new", "in_progress", "done", "hidden"):
            status_val = "new"
        if status_val == "new" and _has_generated_post(rv_raw):
            status_val = "in_progress"
        person_name = None
        posted_at = getattr(p, "posted_at", None)
        created_at = getattr(p, "created_at", None)
        if posted_at is None and created_at is not None:
            posted_at = created_at
        elif posted_at is None:
            posted_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if created_at is None:
            created_at = posted_at
        return RedditPostRead(
            id=p.id,
            subreddit=p.subreddit or "",
            reddit_id=p.reddit_id or "",
            title=p.title or "",
            content=getattr(p, "content", None),
            post_url=getattr(p, "post_url", None),
            posted_at=posted_at,
            author=getattr(p, "author", None),
            score=getattr(p, "score", None),
            num_comments=getattr(p, "num_comments", None),
            person_id=getattr(p, "person_id", None),
            person_name=person_name,
            reply_variants=rv,
            comment_written=getattr(p, "comment_written", False) or False,
            relevance_score=getattr(p, "relevance_score", None),
            relevance_flag=getattr(p, "relevance_flag", None),
            relevance_reason=getattr(p, "relevance_reason", None),
            status=status_val,
            created_at=created_at,
        )
    except Exception as e:
        logger.exception("_reddit_post_to_read failed for post id=%s: %s", getattr(p, "id", None), e)
        raise


@router.get("/posts", response_model=list[RedditPostRead])
async def list_reddit_posts(
    subreddit: Optional[List[str]] = Query(None, alias="subreddit", description="Фильтр по сабреддитам (можно несколько)"),
    period: Optional[str] = Query(None, description="all|week|month"),
    sort: str = Query("desc", description="desc|asc"),
    status_filter: Optional[str] = Query(None, alias="status", description="new|in_progress|done|hidden"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    try:
        q = select(RedditPost).where(RedditPost.user_id == user_id)
        if subreddit:
            subs = [s.strip().lower() for s in subreddit if s and s.strip()]
            if subs:
                q = q.where(RedditPost.subreddit.in_(subs))
        if status_filter and status_filter in ("new", "in_progress", "done", "hidden"):
            q = q.where(RedditPost.status == status_filter)
        # Фильтр по периоду + лимит истории плана
        user = await session.get(User, user_id)
        plan = get_plan(user.plan_name if user else None)
        history_days = plan.get("history_days", 7)
        if period == "week":
            days = min(7, history_days)
        elif period == "month":
            days = min(30, history_days)
        else:
            days = history_days
        since = datetime.utcnow() - timedelta(days=days)
        q = q.where(RedditPost.posted_at >= since)
        order = RedditPost.posted_at.desc() if sort == "desc" else RedditPost.posted_at.asc()
        q = q.order_by(order).limit(limit).offset(offset)
        r = await session.execute(q)
        posts = list(r.scalars().all())
        return [_reddit_post_to_read(p) for p in posts]
    except Exception as e:
        import logging
        logging.exception("Error loading reddit posts: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to load posts: {str(e)}")


async def _sync_one_subreddit(
    session: AsyncSession,
    subreddit: str,
    user_id: int,
    limit: int = 25,
    sort: str = "hot",
) -> tuple[int, list[int]]:
    """Загрузить посты из r/{subreddit} и добавить новые в БД."""
    items = await fetch_subreddit_posts(subreddit, limit=limit, sort=sort)
    if not items:
        return 0, []
    sub = items[0]["subreddit"]
    r = await session.execute(
        select(RedditPost.reddit_id).where(RedditPost.subreddit == sub, RedditPost.user_id == user_id)
    )
    existing = {row[0] for row in r.fetchall()}
    added_rows: list[RedditPost] = []
    for it in items:
        if it["reddit_id"] in existing:
            continue
        post = RedditPost(
            user_id=user_id,
            subreddit=it["subreddit"],
            reddit_id=it["reddit_id"],
            title=it["title"],
            content=it.get("content"),
            post_url=it.get("post_url"),
            posted_at=it["posted_at"],
            author=it.get("author"),
            score=it.get("score"),
            num_comments=it.get("num_comments"),
        )
        session.add(post)
        added_rows.append(post)
        existing.add(it["reddit_id"])
    # Сохраняем сабреддит в список (игнорируем дубликаты)
    try:
        r = await session.execute(
            select(SavedSubreddit.id).where(SavedSubreddit.name == sub, SavedSubreddit.user_id == user_id).limit(1)
        )
        if r.scalar_one_or_none() is None:
            session.add(SavedSubreddit(user_id=user_id, name=sub))
    except Exception:
        pass
    if added_rows:
        await session.flush()
    added_ids = [p.id for p in added_rows if p.id is not None]
    return len(added_rows), added_ids


@router.post("/sync")
async def sync_subreddit(
    subreddit: str = Query(..., description="Имя сабреддита, напр. python"),
    limit: int = Query(25, ge=1, le=100),
    sort: str = Query("hot", description="hot|new|top|rising"),
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """Загрузить посты из r/{subreddit} и добавить новые в БД."""
    added, _added_ids = await _sync_one_subreddit(session, subreddit, user_id, limit=limit, sort=sort)
    await session.commit()
    return {"synced": added, "subreddit": subreddit.strip().lower()}


async def _run_scoring_for_pending_reddit(post_ids: Optional[list[int]] = None) -> None:
    """Фоновая задача: проставить score постам Reddit, у которых relevance_score ещё не задан."""
    async with session_scope() as session:
        try:
            q = select(RedditPost).where(RedditPost.relevance_score.is_(None))
            if post_ids:
                q = q.where(RedditPost.id.in_(post_ids))
            q = q.order_by(RedditPost.id.asc())
            r = await session.execute(q)
            pending = list(r.scalars().all())
            if not pending:
                return
            logger.info("Scoring %d pending reddit posts", len(pending))
            setup_cache: dict[int, dict] = {}
            for post in pending:
                uid = post.user_id or 1
                setup = setup_cache.get(uid)
                if setup is None:
                    setup = await get_setup_for_scoring(session, uid)
                    setup_cache[uid] = setup
                try:
                    payload = {
                        "title": post.title or "",
                        "body": post.content or "",
                        "subreddit": post.subreddit or "",
                        **setup,
                    }
                    result = await run_agent("scoring_agent", payload)
                    if result and result.get("score") is not None:
                        post.relevance_score = result["score"]
                        post.relevance_flag = (result.get("flag") or "")[:8]
                        post.relevance_reason = (result.get("reason") or "")[:256]
                except Exception as e:
                    logger.warning("Scoring failed for reddit post id=%s: %s", post.id, e)
                await session.flush()
        except Exception as e:
            logger.exception("Pending reddit scoring failed: %s", e)


@router.post("/refresh")
async def refresh_reddit(
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """Обновить посты по всем сохранённым сабреддитам: подгрузить новые в БД. По новым запускается скоринг."""
    subreddits = await _get_saved_subreddit_names(session, user_id)
    total_added = 0
    added_ids: list[int] = []
    for sub in subreddits or []:
        try:
            added, ids = await _sync_one_subreddit(session, sub, user_id, limit=50, sort="new")
            total_added += added
            added_ids.extend(ids)
        except Exception:
            pass
    await session.commit()
    if added_ids:
        asyncio.create_task(_run_scoring_for_pending_reddit(post_ids=added_ids))
    return {"refreshed": True, "added": total_added, "subreddits": len(subreddits or [])}


async def run_reddit_sync_all() -> None:
    """Фоновая задача: синхрон по всем сохранённым сабреддитам (раз в час). По новым постам запускается скоринг."""
    from app.models import User
    added_ids: list[int] = []
    async with session_scope() as session:
        try:
            r = await session.execute(select(User.id))
            user_ids = [row[0] for row in r.fetchall()]
            for uid in user_ids:
                subreddits = await _get_saved_subreddit_names(session, uid)
                for sub in subreddits or []:
                    try:
                        _added, ids = await _sync_one_subreddit(session, sub, uid, limit=50, sort="new")
                        added_ids.extend(ids)
                    except Exception:
                        pass
        except Exception as e:
            logger.exception("Scheduled reddit sync failed: %s", e)
    if added_ids:
        asyncio.create_task(_run_scoring_for_pending_reddit(post_ids=added_ids))


async def _get_saved_subreddit_names(session: AsyncSession, user_id: int) -> list:
    """Список имён сабреддитов: из KnowledgeBase (Settings) или из таблицы SavedSubreddit."""
    key = _kb_key("saved_subreddits", user_id)
    r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == key))
    row = r.scalar_one_or_none()
    if row and row.value:
        try:
            data = json.loads(row.value)
            if isinstance(data, list) and data:
                return sorted(set(data))
        except Exception:
            pass
    r = await session.execute(
        select(SavedSubreddit.name).where(SavedSubreddit.user_id == user_id).order_by(SavedSubreddit.name)
    )
    return [row[0] for row in r.fetchall()]


@router.get("/subreddits")
async def list_saved_subreddits(
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """Список сабреддитов: из KnowledgeBase (Settings) или из таблицы SavedSubreddit."""
    return await _get_saved_subreddit_names(session, user_id)


@router.post("/subreddits/add")
async def add_saved_subreddit(
    body: SavedSubredditAdd,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """Добавить сабреддит в список (из раздела Settings)."""
    sub = (body.name or "").strip().lower().replace("/r/", "").split("/")[0]
    if not sub:
        raise HTTPException(400, "Укажите имя сабреддита")
    r = await session.execute(
        select(SavedSubreddit.id).where(SavedSubreddit.name == sub, SavedSubreddit.user_id == user_id).limit(1)
    )
    if r.scalar_one_or_none() is not None:
        return {"ok": True, "name": sub, "message": "Уже в списке"}
    # Лимит Reddit-источников (Starter: reddit_sources, Pro/Enterprise: sources)
    user = await session.get(User, user_id)
    plan = get_plan(user.plan_name if user else None)
    if plan.get("reddit_sources") is not None:
        reddit_count = await get_reddit_sources_count(session, user_id)
        if reddit_count >= plan.get("reddit_sources", 3):
            raise HTTPException(
                status_code=403,
                detail=f"Limit reached: {reddit_count}/{plan.get('reddit_sources')} Reddit sources. Upgrade your plan.",
            )
    else:
        sources_count = await get_sources_count(session, user_id)
        if sources_count >= plan.get("sources", 10):
            raise HTTPException(
                status_code=403,
                detail=f"Limit reached: {sources_count}/{plan.get('sources')} sources. Upgrade your plan.",
            )
    session.add(SavedSubreddit(user_id=user_id, name=sub))
    await session.commit()
    return {"ok": True, "name": sub}


@router.delete("/subreddits/{name:path}", status_code=204)
async def remove_saved_subreddit(
    name: str,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """Удалить сабреддит из списка (посты из БД не удаляются)."""
    sub = (name or "").strip().lower().replace("/r/", "").split("/")[0]
    if not sub:
        raise HTTPException(400, "Укажите имя сабреддита")
    r = await session.execute(
        select(SavedSubreddit).where(SavedSubreddit.name == sub, SavedSubreddit.user_id == user_id)
    )
    row = r.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Сабреддит не найден в списке")
    await session.delete(row)
    await session.commit()


@router.post("/posts/{post_id}/score")
async def save_reddit_post_score(
    post_id: int,
    body: dict,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    """Сохранить оценку релевантности для Reddit поста."""
    try:
        r = await session.execute(select(RedditPost).where(RedditPost.id == post_id))
        post = r.scalar_one_or_none()
        if not post:
            raise HTTPException(404, "Пост не найден")
        if post.user_id is not None and post.user_id != user_id:
            raise HTTPException(404, "Пост не найден")

        score = body.get("score")
        flag = body.get("flag")
        reason = body.get("reason")

        if score is not None:
            post.relevance_score = int(score)
        if flag is not None:
            post.relevance_flag = str(flag)[:8]
        if reason is not None:
            post.relevance_reason = str(reason)[:256]

        await session.commit()
        return {"ok": True, "score": post.relevance_score, "flag": post.relevance_flag}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Save reddit score failed: %s", e)
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/posts/{id}", response_model=RedditPostRead)
async def get_reddit_post(
    id: int,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    q = select(RedditPost).options(selectinload(RedditPost.person)).where(RedditPost.id == id)
    r = await session.execute(q)
    post = r.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Пост не найден")
    if post.user_id is not None and post.user_id != user_id:
        raise HTTPException(404, "Post not found")
    return _reddit_post_to_read(post)


@router.patch("/posts/{id}", response_model=RedditPostRead)
async def update_reddit_post(
    id: int,
    body: RedditPostUpdate,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    q = select(RedditPost).options(selectinload(RedditPost.person)).where(RedditPost.id == id)
    r = await session.execute(q)
    post = r.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Пост не найден")
    if post.user_id is not None and post.user_id != user_id:
        raise HTTPException(404, "Пост не найден")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(post, k, v)
    await session.commit()
    await session.refresh(post)
    return _reddit_post_to_read(post)


@router.delete("/posts/{id}", status_code=204)
async def delete_reddit_post(
    id: int,
    session: AsyncSession = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
):
    post = await session.get(RedditPost, id)
    if not post:
        raise HTTPException(404, "Пост не найден")
    if post.user_id is not None and post.user_id != user_id:
        raise HTTPException(404, "Пост не найден")
    await session.delete(post)
    await session.commit()
