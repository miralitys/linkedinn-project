#!/usr/bin/env python3
"""
Перенос данных из локального SQLite (lfas.db) в Supabase (Postgres).
Запуск: из корня проекта, с установленным DATABASE_URL на Supabase.

  export DATABASE_URL="postgresql://postgres.xxx:password@aws-1-xxx.pooler.supabase.com:5432/postgres?sslmode=require"
  python -m scripts.migrate_local_to_supabase

Или в .env задать DATABASE_URL на Supabase и запустить так же.
Локальная БД по умолчанию: ./lfas.db (относительно текущей рабочей директории).
"""
import asyncio
import os
import ssl
import sys
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Загрузка .env из корня проекта (если установлен python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def _normalize_url(url: str) -> str:
    """postgresql:// → postgresql+asyncpg:// и убираем ?sslmode=require (asyncpg его не принимает)."""
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
    from sqlalchemy import select, insert, text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from app.models import (
        Base,
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
    remote_url = os.environ.get("DATABASE_URL", "").strip().strip('"').strip("'")
    if not remote_url or "sqlite" in remote_url.lower():
        # Попробовать собрать URL из отдельных переменных (удобно, если в пароле спецсимволы)
        host = os.environ.get("SUPABASE_DB_HOST")
        user = os.environ.get("SUPABASE_DB_USER", "postgres")
        password = os.environ.get("SUPABASE_DB_PASSWORD")
        port = os.environ.get("SUPABASE_DB_PORT", "6543")
        dbname = os.environ.get("SUPABASE_DB_NAME", "postgres")
        if host and password:
            user_enc = quote_plus(user)
            pass_enc = quote_plus(password)
            remote_url = f"postgresql://{user_enc}:{pass_enc}@{host.strip()}:{port}/{dbname}"
        elif not remote_url:
            print("Задайте DATABASE_URL (строка подключения к Supabase).")
            sys.exit(1)
        else:
            print("DATABASE_URL должен указывать на Supabase (postgresql://...), а не на SQLite.")
            print("Задайте в .env строку из Supabase (Settings → Database → Connection string), с ?sslmode=require в конце.")
            sys.exit(1)

    remote_url = _normalize_url(remote_url)

    engine_local = create_async_engine(
        local_db,
        connect_args={"check_same_thread": False} if "sqlite" in local_db else {},
        echo=False,
    )
    # asyncpg: SSL без строгой проверки сертификата (для миграции; соединение всё равно шифруется)
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    try:
        engine_remote = create_async_engine(
            remote_url,
            connect_args={"ssl": ssl_ctx} if "asyncpg" in remote_url else {},
            echo=False,
        )
    except Exception as e:
        host = os.environ.get("SUPABASE_DB_HOST")
        password = os.environ.get("SUPABASE_DB_PASSWORD")
        if host and password:
            user = os.environ.get("SUPABASE_DB_USER", "postgres")
            port = os.environ.get("SUPABASE_DB_PORT", "6543")
            dbname = os.environ.get("SUPABASE_DB_NAME", "postgres")
            remote_url = f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host.strip()}:{port}/{dbname}"
            remote_url = _normalize_url(remote_url)
            try:
                engine_remote = create_async_engine(
                    remote_url,
                    connect_args={"ssl": ssl_ctx} if "asyncpg" in remote_url else {},
                    echo=False,
                )
            except Exception as e2:
                print("Ошибка подключения к Supabase:", e2)
                sys.exit(1)
        else:
            print("Ошибка разбора DATABASE_URL:", e)
            has_host = "да" if os.environ.get("SUPABASE_DB_HOST") else "нет"
            has_pass = "да" if os.environ.get("SUPABASE_DB_PASSWORD") else "нет"
            print(f"  SUPABASE_DB_HOST задан: {has_host}, SUPABASE_DB_PASSWORD задан: {has_pass}")
            print("Вариант 1 — в .env задать отдельные переменные (пароль — любой). Тогда закомментируйте DATABASE_URL:")
            print("  # DATABASE_URL=...")
            print("  SUPABASE_DB_HOST=aws-0-xxx.pooler.supabase.com")
            print("  SUPABASE_DB_USER=postgres.ТВОЙ_PROJECT_REF")
            print("  SUPABASE_DB_PASSWORD=твой_пароль")
            print("  SUPABASE_DB_PORT=6543")
            print("  SUPABASE_DB_NAME=postgres")
            print("Вариант 2 — одна строка DATABASE_URL в одну строку, пароль с @#? закодировать (@→%40, #→%23, ?→%3F).")
            sys.exit(1)

    async_session_local = async_sessionmaker(engine_local, class_=AsyncSession, expire_on_commit=False)
    async_session_remote = async_sessionmaker(engine_remote, class_=AsyncSession, expire_on_commit=False)

    tables_order = [
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

    async with async_session_local() as s_local, async_session_remote() as s_remote:
        for model, table_name in tables_order:
            r = await s_local.execute(select(model))
            rows = list(r.scalars().all())
            if not rows:
                print(f"  {table_name}: пусто, пропуск")
                continue
            for row in rows:
                d = {c.key: getattr(row, c.key) for c in model.__table__.columns}
                await s_remote.execute(insert(model.__table__).values(**d))
            await s_remote.flush()
            print(f"  {table_name}: перенесено {len(rows)} записей")
        await s_remote.commit()

    # Сброс последовательностей ID в Postgres (таблицы из нашего кода — подстановка безопасна)
    async with engine_remote.connect() as conn:
        for _, table_name in tables_order:
            try:
                await conn.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), COALESCE((SELECT MAX(id) FROM {table_name}), 1))"
                    )
                )
            except Exception as e:
                print(f"  Предупреждение: sequence для {table_name}: {e}")
        await conn.commit()
    await engine_local.dispose()
    await engine_remote.dispose()
    print("Готово. Данные перенесены в Supabase.")


if __name__ == "__main__":
    asyncio.run(main())
