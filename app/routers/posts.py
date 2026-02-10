# app/routers/posts.py
import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
try:
    import feedparser
except ImportError:
    feedparser = None
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.models import ContactPost, Person
from app.schemas import (
    ContactPostCreate,
    ContactPostRead,
    ContactPostUpdate,
    PostParseFromUrlRequest,
    PostParseFromUrlResponse,
)
from app.config import settings
from app.services.post_parser import parse_post_from_url
from app.services.rapidapi_linkedin import fetch_post_via_rapidapi, fetch_profile_posts, _parse_posted_at


router = APIRouter(prefix="/posts", tags=["posts"])


def _posted_at_to_utc(dt: datetime, tz_name: str) -> datetime:
    """Интерпретирует наивную дату как время в таймзоне tz_name и возвращает наивный UTC."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc).replace(tzinfo=None)

# Шаблоны демо-постов для авто-загрузки (когда нет реального источника)
DEMO_POST_TEMPLATES = [
    {"title": "Ключевые тренды в отрасли в этом квартале", "content": "Краткий обзор изменений и возможностей для команды и партнёров.", "tags": ["тренды", "обзор"]},
    {"title": "Обновление по проекту и следующие шаги", "content": "Поделюсь прогрессом и планами на ближайший период.", "tags": ["проект", "обновление"]},
    {"title": "Итоги конференции и главные инсайты", "content": "Что удалось обсудить и какие выводы можно применить в работе.", "tags": ["конференция", "инсайты"]},
    {"title": "Эффективная стратегия и её реализация", "content": "Стратегия имеет значение, но именно исполнение даёт реальные результаты.", "tags": ["стратегия", "исполнение"]},
    {"title": "Как мы интегрируем новые технологии", "content": "Опыт внедрения и улучшение скорости коммуникаций в команде.", "tags": ["технологии", "интеграция"]},
]


def _post_to_read(post: ContactPost) -> ContactPostRead:
    rv = post.reply_variants if isinstance(post.reply_variants, dict) else None
    return ContactPostRead(
        id=post.id,
        person_id=post.person_id,
        person_name=post.person.full_name if post.person else None,
        title=post.title,
        content=post.content,
        post_url=post.post_url,
        posted_at=post.posted_at,
        likes_count=post.likes_count,
        comments_count=post.comments_count,
        views_count=post.views_count,
        tags=post.tags if isinstance(post.tags, list) else (post.tags or []),
        archived=post.archived,
        reply_variants=rv,
        comment_written=getattr(post, "comment_written", False) or False,
        created_at=post.created_at,
    )


@router.get("", response_model=list[ContactPostRead])
async def list_posts(
    person_id: Optional[int] = None,
    period: Optional[str] = Query(None, description="all|week|month"),
    sort: str = Query("desc", description="desc|asc"),
    archived: Optional[bool] = Query(None, description="false = only visible, true = only archived"),
    max_per_contact: Optional[int] = Query(None, description="макс. постов на контакт (напр. 3 = последние 3 по каждому)"),
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(ContactPost)
        .options(selectinload(ContactPost.person))
        .where(ContactPost.person_id.in_(select(Person.id)))
    )
    if person_id is not None:
        q = q.where(ContactPost.person_id == person_id)
    if period == "week":
        since = datetime.utcnow() - timedelta(days=7)
        q = q.where(ContactPost.posted_at >= since)
    elif period == "month":
        since = datetime.utcnow() - timedelta(days=30)
        q = q.where(ContactPost.posted_at >= since)
    if archived is not None:
        q = q.where(ContactPost.archived == archived)
    order = ContactPost.posted_at.desc() if sort == "desc" else ContactPost.posted_at.asc()
    q = q.order_by(order)
    r = await session.execute(q)
    posts = list(r.scalars().all())
    if max_per_contact is not None and max_per_contact > 0:
        by_person: dict[int, list] = {}
        for p in posts:
            by_person.setdefault(p.person_id, []).append(p)
        posts = []
        for pid in sorted(by_person.keys()):
            posts.extend(by_person[pid][:max_per_contact])
        posts.sort(key=lambda p: p.posted_at, reverse=(sort == "desc"))
    return [_post_to_read(p) for p in posts]


async def _sync_rss(session: AsyncSession) -> int:
    """Подгрузить посты из RSS-лент контактов. Не делает commit."""
    if feedparser is None:
        return 0
    r_people = await session.execute(
        select(Person).where(Person.feed_url.isnot(None)).where(Person.feed_url != "")
    )
    people = list(r_people.scalars().all())
    created = 0
    max_entries_per_feed = 10
    for person in people:
        feed_url = (person.feed_url or "").strip()
        if not feed_url:
            continue
        try:
            feed = await asyncio.to_thread(feedparser.parse, feed_url)
        except Exception:
            continue
        r_ex = await session.execute(
            select(ContactPost.post_url).where(
                ContactPost.person_id == person.id,
                ContactPost.post_url.isnot(None),
            )
        )
        existing_urls = {row[0] for row in r_ex.fetchall()}
        for entry in (feed.entries or [])[:max_entries_per_feed]:
            link = (entry.get("link") or "").strip()
            if not link or link in existing_urls:
                continue
            title = (entry.get("title") or "Без заголовка").strip() or "Без заголовка"
            summary = (entry.get("summary") or "").strip()
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if published:
                try:
                    posted_at = datetime(*published[:6])
                except Exception:
                    posted_at = datetime.utcnow()
            else:
                posted_at = datetime.utcnow()
            post = ContactPost(
                person_id=person.id,
                title=title[:512],
                content=summary[:4096] if summary else None,
                post_url=link,
                posted_at=posted_at,
            )
            session.add(post)
            created += 1
            existing_urls.add(link)
    return created


async def _sync_linkedin_rapidapi(session: AsyncSession, limit_per_profile: int = 5) -> int:
    """
    Для контактов с linkedin_url: Get Profile's Posts (последние limit постов),
    сравниваем post_url с уже сохранёнными. Добавляем новые; архивированные восстанавливаем (archived=False).
    Не делает commit.
    """
    if not settings.rapidapi_key:
        return 0
    r_people = await session.execute(
        select(Person).where(Person.linkedin_url.isnot(None)).where(Person.linkedin_url != "")
    )
    people = list(r_people.scalars().all())
    created = 0
    for person in people:
        profile_url = (person.linkedin_url or "").strip()
        if not profile_url or "linkedin.com" not in profile_url:
            continue
        posts_raw = await fetch_profile_posts(profile_url, limit=limit_per_profile)
        if isinstance(posts_raw, dict) and "error" in posts_raw:
            continue
        if not isinstance(posts_raw, list):
            continue
        r_ex = await session.execute(
            select(ContactPost).where(
                ContactPost.person_id == person.id,
                ContactPost.post_url.isnot(None),
            )
        )
        by_url: dict[str, ContactPost] = {}
        for post in r_ex.scalars().all():
            url = (post.post_url or "").rstrip("/")
            if url:
                by_url[url] = post
        for p in posts_raw:
            post_url = (p.get("post_url") or "").strip()
            url_key = post_url.rstrip("/")
            if not post_url:
                continue
            existing = by_url.get(url_key)
            if existing:
                if existing.archived:
                    existing.archived = False
                    created += 1
                continue
            post = ContactPost(
                person_id=person.id,
                title=p.get("title") or "Пост"[:512],
                content=p.get("content"),
                post_url=post_url,
                posted_at=p.get("posted_at", datetime.utcnow()),
                likes_count=p.get("likes_count"),
                comments_count=p.get("comments_count"),
                views_count=p.get("views_count"),
            )
            session.add(post)
            created += 1
            by_url[url_key] = post
    return created


async def _sync_demo(session: AsyncSession) -> int:
    """Создать демо-пост для контактов без постов. Не делает commit."""
    r_people = await session.execute(select(Person).order_by(Person.id))
    people = list(r_people.scalars().all())
    if not people:
        return 0
    r_has = await session.execute(
        select(ContactPost.person_id).where(ContactPost.person_id.in_([p.id for p in people])).distinct()
    )
    has_post_ids = {row[0] for row in r_has.fetchall()}
    created = 0
    for person in people:
        if person.id in has_post_ids:
            continue
        tpl = random.choice(DEMO_POST_TEMPLATES)
        posted_at = datetime.utcnow() - timedelta(days=random.randint(0, 14))
        post = ContactPost(
            person_id=person.id,
            title=tpl["title"],
            content=tpl["content"],
            post_url=person.linkedin_url,
            posted_at=posted_at,
            likes_count=random.randint(0, 20),
            comments_count=random.randint(0, 5),
            views_count=random.randint(50, 500),
            tags=tpl.get("tags"),
        )
        session.add(post)
        created += 1
        has_post_ids.add(person.id)
    return created


async def run_auto_sync() -> None:
    """Фоновая задача: автоматом подгрузить посты (RSS + демо для контактов без постов)."""
    from app.db import session_scope
    async with session_scope() as session:
        await _sync_rss(session)
        await _sync_demo(session)


@router.post("/sync")
async def sync_posts(
    source: str = Query("demo", description="demo | rss | linkedin"),
    session: AsyncSession = Depends(get_session),
):
    """
    Авто-загрузка постов:
    - demo: демо-посты для контактов без постов
    - rss: из RSS-ленты контактов
    - linkedin: RapidAPI Get Profile's Posts — последние 5 постов профиля, добавляем только новые
    """
    if source == "demo":
        created = await _sync_demo(session)
        await session.commit()
        return {"synced": created, "message": f"Добавлено постов: {created}."}
    if source == "rss":
        if feedparser is None:
            return {"synced": 0, "message": "Установите feedparser: pip install feedparser"}
        created = await _sync_rss(session)
        await session.commit()
        return {"synced": created, "message": f"Из RSS добавлено постов: {created}."}
    if source == "linkedin":
        if not settings.rapidapi_key:
            return {"synced": 0, "message": "Задайте RAPIDAPI_KEY для синка из LinkedIn."}
        created = await _sync_linkedin_rapidapi(session, limit_per_profile=5)
        await session.commit()
        return {"synced": created, "message": f"Из LinkedIn (RapidAPI) добавлено постов: {created}."}
    return {"synced": 0, "message": f"Неизвестный источник: {source}. Используйте source=demo, rss или linkedin."}


@router.post("/parse-from-url", response_model=PostParseFromUrlResponse)
async def parse_post_from_url_route(
    body: PostParseFromUrlRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Парсинг поста по URL. Если задан RAPIDAPI_KEY и URL — LinkedIn, сначала пробует RapidAPI (без Playwright).
    Иначе: Playwright + OpenAI Vision.
    Если передан person_id — создаёт пост и возвращает его.
    """
    url = (body.url or "").strip()
    if not url or not url.startswith("http"):
        return PostParseFromUrlResponse(error="Укажите корректный URL поста (http/https).")

    result = None
    if settings.rapidapi_key and "linkedin.com" in url.lower():
        result = await fetch_post_via_rapidapi(url)
    if result is None or "error" in result:
        result = await parse_post_from_url(url, user_data_dir=settings.playwright_user_data_dir)
    if "error" in result:
        return PostParseFromUrlResponse(error=result["error"])

    # Маппинг полей из распознанного JSON в ContactPost
    def _int(v):
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    title = (result.get("author_name") or result.get("text") or "Пост")[:512]
    if result.get("text") and title == "Пост":
        title = (result["text"][:200].strip() + ("…" if len(result.get("text", "")) > 200 else ""))[:512]
    content = result.get("text") or None
    post_url = result.get("post_url") or url
    reactions = _int(result.get("reactions_count"))
    comments = _int(result.get("comments_count"))
    reposts = _int(result.get("reposts_count"))
    views = _int(result.get("views_count"))

    if body.person_id is None:
        return PostParseFromUrlResponse(
            parsed={
                "author_name": result.get("author_name"),
                "author_profile_url": result.get("author_profile_url"),
                "post_url": post_url,
                "published_at": result.get("published_at"),
                "text": content,
                "media_present": result.get("media_present"),
                "reactions_count": reactions,
                "comments_count": comments,
                "reposts_count": reposts,
                "views_count": views,
                "_title": title,
                "_content": content,
                "_post_url": post_url,
                "_likes_count": reactions,
                "_comments_count": comments,
                "_views_count": views,
            },
            screenshot_base64=result.get("_screenshot_base64"),
        )

    person = await session.get(Person, body.person_id)
    if not person:
        return PostParseFromUrlResponse(error="Контакт не найден.", parsed=result)
    posted_at = _parse_posted_at(result.get("published_at")) if result.get("published_at") else datetime.utcnow()
    post = ContactPost(
        person_id=body.person_id,
        title=title,
        content=content,
        post_url=post_url,
        posted_at=posted_at,
        likes_count=reactions,
        comments_count=comments,
        views_count=views,
    )
    session.add(post)
    await session.flush()
    await session.refresh(post)
    post.person = person
    return PostParseFromUrlResponse(
        parsed=result, post=_post_to_read(post), screenshot_base64=result.get("_screenshot_base64")
    )


@router.post("", response_model=ContactPostRead)
async def create_post(body: ContactPostCreate, session: AsyncSession = Depends(get_session)):
    person = await session.get(Person, body.person_id)
    if not person:
        raise HTTPException(404, "Contact not found")
    tags = body.tags
    posted_at_utc = _posted_at_to_utc(body.posted_at, settings.display_timezone)
    post = ContactPost(
        person_id=body.person_id,
        title=body.title,
        content=body.content,
        post_url=body.post_url,
        posted_at=posted_at_utc,
        likes_count=body.likes_count,
        comments_count=body.comments_count,
        views_count=body.views_count,
        tags=tags,
    )
    session.add(post)
    await session.flush()
    await session.refresh(post)
    post.person = person
    return _post_to_read(post)


@router.get("/{id}", response_model=ContactPostRead)
async def get_post(id: int, session: AsyncSession = Depends(get_session)):
    q = select(ContactPost).options(selectinload(ContactPost.person)).where(ContactPost.id == id)
    r = await session.execute(q)
    post = r.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found")
    return _post_to_read(post)


@router.post("/{id}/refresh-date", response_model=ContactPostRead)
async def refresh_post_date(id: int, session: AsyncSession = Depends(get_session)):
    """
    Обновить дату поста из LinkedIn (RapidAPI). Для постов с post_url на LinkedIn
    запрашивает Get Post Details и подставляет дату публикации.
    """
    q = select(ContactPost).options(selectinload(ContactPost.person)).where(ContactPost.id == id)
    r = await session.execute(q)
    post = r.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found")
    url = (post.post_url or "").strip()
    if not url or "linkedin.com" not in url.lower() or not settings.rapidapi_key:
        raise HTTPException(400, "Пост должен иметь ссылку на LinkedIn и задан RAPIDAPI_KEY.")
    result = await fetch_post_via_rapidapi(url)
    if "error" in result:
        raise HTTPException(400, result["error"])
    published = result.get("published_at")
    if not published:
        raise HTTPException(422, "Дата публикации не получена из LinkedIn.")
    post.posted_at = _parse_posted_at(published)
    await session.commit()
    await session.refresh(post)
    return _post_to_read(post)


@router.patch("/{id}", response_model=ContactPostRead)
async def update_post(id: int, body: ContactPostUpdate, session: AsyncSession = Depends(get_session)):
    q = select(ContactPost).options(selectinload(ContactPost.person)).where(ContactPost.id == id)
    r = await session.execute(q)
    post = r.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found")
    dump = body.model_dump(exclude_unset=True)
    if "posted_at" in dump:
        dump["posted_at"] = _posted_at_to_utc(dump["posted_at"], settings.display_timezone)
    for k, v in dump.items():
        setattr(post, k, v)
    await session.commit()
    await session.refresh(post)
    return _post_to_read(post)


@router.delete("/{id}", status_code=204)
async def delete_post(id: int, session: AsyncSession = Depends(get_session)):
    post = await session.get(ContactPost, id)
    if not post:
        raise HTTPException(404, "Post not found")
    await session.delete(post)
    await session.commit()
