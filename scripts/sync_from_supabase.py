#!/usr/bin/env python3
"""
Синхронизация данных с сервера (Supabase) в локальную SQLite.
Локальная БД будет перезаписана данными с сервера — вы будете работать с одинаковыми данными.

Запуск:
  REMOTE_DATABASE_URL="postgresql://postgres.xxx:password@aws-0-xxx.pooler.supabase.com:6543/postgres?sslmode=require" python -m scripts.sync_from_supabase

Или в .env задать REMOTE_DATABASE_URL (Supabase) и запустить.
Локальная БД по умолчанию: ./lfas.db
"""
import asyncio
import os
import ssl
import sys
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def _normalize_url(url: str) -> str:
    """postgresql:// → postgresql+asyncpg:// и убираем ?sslmode=require."""
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "?sslmode=" in url or "&sslmode=" in url:
        from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
        p = urlparse(url)
        q = parse_qs(p.query)
        q.pop("sslmode", None)
        new_query = urlencode(q, doseq=True)
        url = urlunparse((p.scheme, p.netloc, p.path, p.params, new_query or "", p.fragment))
    return url


async def main():
    from sqlalchemy import select, insert, text, delete
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from app.models import (
        Base,
        User,
        Company,
        Segment,
        Person,
        KOL,
        Touch,
        ContactPost,
        RedditPost,
        SavedSubreddit,
        NewsItem,
        SalesAvatar,
        Offer,
        LeadMagnet,
        KnowledgeBase,
        Draft,
        LinkedInOAuth,
        LinkedInDailyMetric,
    )

    local_db = os.environ.get("LOCAL_DATABASE_URL", "sqlite+aiosqlite:///./lfas.db")
    if not local_db.startswith("sqlite"):
        local_db = "sqlite+aiosqlite:///" + str(ROOT / "lfas.db")

    # REMOTE = сервер (Supabase), LOCAL = lfas.db
    remote_url = os.environ.get("REMOTE_DATABASE_URL", "").strip().strip('"').strip("'")
    if not remote_url:
        db_url = os.environ.get("DATABASE_URL", "").strip().strip('"').strip("'")
        if db_url and "postgresql" in db_url.lower():
            remote_url = db_url

    if not remote_url or "sqlite" in remote_url.lower():
        host = os.environ.get("SUPABASE_DB_HOST")
        user = os.environ.get("SUPABASE_DB_USER", "postgres")
        password = os.environ.get("SUPABASE_DB_PASSWORD")
        port = os.environ.get("SUPABASE_DB_PORT", "6543")
        dbname = os.environ.get("SUPABASE_DB_NAME", "postgres")
        if host and password:
            user_enc = quote_plus(user)
            pass_enc = quote_plus(password)
            remote_url = f"postgresql://{user_enc}:{pass_enc}@{host.strip()}:{port}/{dbname}"
        else:
            print("Задайте REMOTE_DATABASE_URL или DATABASE_URL (строка подключения к Supabase).")
            print("Пример: REMOTE_DATABASE_URL=postgresql://postgres.xxx:pass@aws-0-xxx.pooler.supabase.com:6543/postgres?sslmode=require")
            sys.exit(1)

    remote_url = _normalize_url(remote_url)

    engine_local = create_async_engine(
        local_db,
        connect_args={"check_same_thread": False} if "sqlite" in local_db else {},
        echo=False,
    )
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    engine_remote = create_async_engine(
        remote_url,
        connect_args={"ssl": ssl_ctx} if "asyncpg" in remote_url else {},
        echo=False,
    )

    async_session_local = async_sessionmaker(engine_local, class_=AsyncSession, expire_on_commit=False)
    async_session_remote = async_sessionmaker(engine_remote, class_=AsyncSession, expire_on_commit=False)

    # Порядок: сначала таблицы без FK, потом зависимые
    tables_order = [
        (User, "users"),
        (Company, "companies"),
        (Segment, "segments"),
        (Person, "people"),
        (KOL, "kol"),
        (Touch, "touches"),
        (ContactPost, "contact_posts"),
        (RedditPost, "reddit_posts"),
        (SavedSubreddit, "saved_subreddits"),
        (NewsItem, "news_items"),
        (SalesAvatar, "sales_avatar"),
        (Offer, "offers"),
        (LeadMagnet, "lead_magnets"),
        (KnowledgeBase, "knowledge_base"),
        (Draft, "drafts"),
        (LinkedInOAuth, "linkedin_oauth"),
        (LinkedInDailyMetric, "linkedin_daily_metrics"),
    ]

    print("Синхронизация: Supabase → локальная SQLite")
    print("=" * 50)

    async with async_session_local() as s_local, async_session_remote() as s_remote:
        for model, table_name in tables_order:
            try:
                r = await s_remote.execute(select(model))
                rows = list(r.scalars().all())
            except Exception as e:
                print(f"  {table_name}: таблица отсутствует на сервере или ошибка — {e}")
                continue

            if not rows:
                await s_local.execute(delete(model))
                await s_local.flush()
                print(f"  {table_name}: 0 записей (локально очищено)")
                continue

            await s_local.execute(delete(model))
            await s_local.flush()

            for row in rows:
                d = {c.key: getattr(row, c.key) for c in model.__table__.columns}
                try:
                    await s_local.execute(insert(model.__table__).values(**d))
                except Exception as e:
                    print(f"  {table_name}: ошибка вставки {d.get('id', '?')} — {e}")
                    raise

            await s_local.flush()
            print(f"  {table_name}: синхронизировано {len(rows)} записей")

        await s_local.commit()

    await engine_local.dispose()
    await engine_remote.dispose()
    print("=" * 50)
    print("Готово. Локальная БД синхронизирована с сервером.")
    print("Запустите приложение с LOCAL_DATABASE_URL или без DATABASE_URL (по умолчанию lfas.db).")


if __name__ == "__main__":
    asyncio.run(main())
