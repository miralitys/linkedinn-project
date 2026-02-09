# app/routers/reddit.py
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session, session_scope
from app.models import KnowledgeBase, Person, RedditPost, SavedSubreddit
from app.routers.setup import get_setup_for_scoring
from app.schemas import RedditPostCreate, RedditPostRead, RedditPostUpdate, SavedSubredditAdd
from app.services.reddit_feed import fetch_subreddit_posts
from agents.registry import run_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reddit", tags=["reddit"])


def _reddit_post_to_read(p: RedditPost) -> RedditPostRead:
    rv = p.reply_variants if isinstance(p.reply_variants, dict) else None
    return RedditPostRead(
        id=p.id,
        subreddit=p.subreddit,
        reddit_id=p.reddit_id,
        title=p.title,
        content=p.content,
        post_url=p.post_url,
        posted_at=p.posted_at,
        author=p.author,
        score=p.score,
        num_comments=p.num_comments,
        person_id=p.person_id,
        person_name=p.person.full_name if p.person else None,
        reply_variants=rv,
        comment_written=getattr(p, "comment_written", False) or False,
        relevance_score=getattr(p, "relevance_score", None),
        relevance_flag=getattr(p, "relevance_flag", None),
        relevance_reason=getattr(p, "relevance_reason", None),
        created_at=p.created_at,
    )


@router.get("/posts", response_model=list[RedditPostRead])
async def list_reddit_posts(
    subreddit: Optional[str] = Query(None, description="Фильтр по сабреддиту"),
    period: Optional[str] = Query(None, description="all|week|month"),
    sort: str = Query("desc", description="desc|asc"),
    session: AsyncSession = Depends(get_session),
):
    try:
        q = select(RedditPost).options(selectinload(RedditPost.person))
        if subreddit:
            q = q.where(RedditPost.subreddit == subreddit.strip().lower())
        if period == "week":
            since = datetime.utcnow() - timedelta(days=7)
            q = q.where(RedditPost.posted_at >= since)
        elif period == "month":
            since = datetime.utcnow() - timedelta(days=30)
            q = q.where(RedditPost.posted_at >= since)
        order = RedditPost.posted_at.desc() if sort == "desc" else RedditPost.posted_at.asc()
        q = q.order_by(order)
        r = await session.execute(q)
        posts = list(r.scalars().all())
        return [_reddit_post_to_read(p) for p in posts]
    except Exception as e:
        import logging
        logging.exception("Error loading reddit posts: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to load posts: {str(e)}")


async def _sync_one_subreddit(session: AsyncSession, subreddit: str, limit: int = 25, sort: str = "hot") -> int:
    """Загрузить посты из r/{subreddit} и добавить новые в БД. Возвращает количество добавленных."""
    items = await fetch_subreddit_posts(subreddit, limit=limit, sort=sort)
    if not items:
        return 0
    sub = items[0]["subreddit"]
    r = await session.execute(select(RedditPost.reddit_id).where(RedditPost.subreddit == sub))
    existing = {row[0] for row in r.fetchall()}
    added = 0
    for it in items:
        if it["reddit_id"] in existing:
            continue
        post = RedditPost(
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
        existing.add(it["reddit_id"])
        added += 1
    # Сохраняем сабреддит в список (игнорируем дубликаты)
    try:
        r = await session.execute(select(SavedSubreddit.id).where(SavedSubreddit.name == sub).limit(1))
        if r.scalar_one_or_none() is None:
            session.add(SavedSubreddit(name=sub))
    except Exception:
        pass
    return added


@router.post("/sync")
async def sync_subreddit(
    subreddit: str = Query(..., description="Имя сабреддита, напр. python"),
    limit: int = Query(25, ge=1, le=100),
    sort: str = Query("hot", description="hot|new|top|rising"),
    session: AsyncSession = Depends(get_session),
):
    """Загрузить посты из r/{subreddit} и добавить новые в БД."""
    added = await _sync_one_subreddit(session, subreddit, limit=limit, sort=sort)
    await session.commit()
    return {"synced": added, "subreddit": subreddit.strip().lower()}


async def _run_scoring_for_pending_reddit() -> None:
    """Фоновая задача: проставить score всем постам Reddit, у которых relevance_score ещё не задан."""
    async with session_scope() as session:
        try:
            setup = await get_setup_for_scoring(session)
            r = await session.execute(
                select(RedditPost).where(RedditPost.relevance_score.is_(None)).order_by(RedditPost.id.asc())
            )
            pending = list(r.scalars().all())
            if not pending:
                return
            logger.info("Scoring %d pending reddit posts", len(pending))
            for post in pending:
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
async def refresh_reddit(session: AsyncSession = Depends(get_session)):
    """Обновить посты по всем сохранённым сабреддитам: подгрузить новые в БД. По новым запускается скоринг."""
    subreddits = await _get_saved_subreddit_names(session)
    total_added = 0
    for sub in subreddits or []:
        try:
            total_added += await _sync_one_subreddit(session, sub, limit=50, sort="new")
        except Exception:
            pass
    await session.commit()
    asyncio.create_task(_run_scoring_for_pending_reddit())
    return {"refreshed": True, "added": total_added, "subreddits": len(subreddits or [])}


async def run_reddit_sync_all() -> None:
    """Фоновая задача: синхрон по всем сохранённым сабреддитам (раз в час). По новым постам запускается скоринг."""
    async with session_scope() as session:
        try:
            subreddits = await _get_saved_subreddit_names(session)
            for sub in subreddits or []:
                try:
                    await _sync_one_subreddit(session, sub, limit=50, sort="new")
                except Exception:
                    pass
        except Exception as e:
            logger.exception("Scheduled reddit sync failed: %s", e)
    asyncio.create_task(_run_scoring_for_pending_reddit())


async def _get_saved_subreddit_names(session: AsyncSession) -> list:
    """Список имён сабреддитов: из KnowledgeBase (Settings) или из таблицы SavedSubreddit."""
    r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == "saved_subreddits"))
    row = r.scalar_one_or_none()
    if row and row.value:
        try:
            data = json.loads(row.value)
            if isinstance(data, list) and data:
                return sorted(set(data))
        except Exception:
            pass
    r = await session.execute(select(SavedSubreddit.name).order_by(SavedSubreddit.name))
    return [row[0] for row in r.fetchall()]


@router.get("/subreddits")
async def list_saved_subreddits(session: AsyncSession = Depends(get_session)):
    """Список сабреддитов: из KnowledgeBase (Settings) или из таблицы SavedSubreddit."""
    return await _get_saved_subreddit_names(session)


@router.post("/subreddits/add")
async def add_saved_subreddit(body: SavedSubredditAdd, session: AsyncSession = Depends(get_session)):
    """Добавить сабреддит в список (из раздела Settings)."""
    sub = (body.name or "").strip().lower().replace("/r/", "").split("/")[0]
    if not sub:
        raise HTTPException(400, "Укажите имя сабреддита")
    r = await session.execute(select(SavedSubreddit.id).where(SavedSubreddit.name == sub).limit(1))
    if r.scalar_one_or_none() is not None:
        return {"ok": True, "name": sub, "message": "Уже в списке"}
    session.add(SavedSubreddit(name=sub))
    await session.commit()
    return {"ok": True, "name": sub}


@router.delete("/subreddits/{name:path}", status_code=204)
async def remove_saved_subreddit(name: str, session: AsyncSession = Depends(get_session)):
    """Удалить сабреддит из списка (посты из БД не удаляются)."""
    sub = (name or "").strip().lower().replace("/r/", "").split("/")[0]
    if not sub:
        raise HTTPException(400, "Укажите имя сабреддита")
    r = await session.execute(select(SavedSubreddit).where(SavedSubreddit.name == sub))
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
):
    """Сохранить оценку релевантности для Reddit поста."""
    try:
        r = await session.execute(select(RedditPost).where(RedditPost.id == post_id))
        post = r.scalar_one_or_none()
        if not post:
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
async def get_reddit_post(id: int, session: AsyncSession = Depends(get_session)):
    q = select(RedditPost).options(selectinload(RedditPost.person)).where(RedditPost.id == id)
    r = await session.execute(q)
    post = r.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found")
    return _reddit_post_to_read(post)


@router.patch("/posts/{id}", response_model=RedditPostRead)
async def update_reddit_post(id: int, body: RedditPostUpdate, session: AsyncSession = Depends(get_session)):
    q = select(RedditPost).options(selectinload(RedditPost.person)).where(RedditPost.id == id)
    r = await session.execute(q)
    post = r.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(post, k, v)
    await session.commit()
    await session.refresh(post)
    return _reddit_post_to_read(post)


@router.delete("/posts/{id}", status_code=204)
async def delete_reddit_post(id: int, session: AsyncSession = Depends(get_session)):
    post = await session.get(RedditPost, id)
    if not post:
        raise HTTPException(404, "Post not found")
    await session.delete(post)
    await session.commit()
