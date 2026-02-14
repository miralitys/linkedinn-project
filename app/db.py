# app/db.py
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.models import Base

# SQLite: need check_same_thread=False for aiosqlite.
# Postgres (Supabase): отключаем prepared statement cache — Supabase/pgbouncer не поддерживает его в transaction mode.
PERFORMANCE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_companies_user_id ON companies (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_people_user_id ON people (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_people_user_status ON people (user_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_people_user_is_kol ON people (user_id, is_kol)",
    "CREATE INDEX IF NOT EXISTS idx_people_company_id ON people (company_id)",
    "CREATE INDEX IF NOT EXISTS idx_people_segment_id ON people (segment_id)",
    "CREATE INDEX IF NOT EXISTS idx_touches_person_created_at ON touches (person_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_contact_posts_person_posted_at ON contact_posts (person_id, posted_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_contact_posts_person_archived_posted_at ON contact_posts (person_id, archived, posted_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_contact_posts_person_post_url ON contact_posts (person_id, post_url)",
    "CREATE INDEX IF NOT EXISTS idx_reddit_posts_user_posted_at ON reddit_posts (user_id, posted_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reddit_posts_user_subreddit ON reddit_posts (user_id, subreddit)",
    "CREATE INDEX IF NOT EXISTS idx_reddit_posts_relevance_score_id ON reddit_posts (relevance_score, id)",
    "CREATE INDEX IF NOT EXISTS idx_saved_subreddits_user_id ON saved_subreddits (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_news_items_published_id ON news_items (published, id)",
    "CREATE INDEX IF NOT EXISTS idx_news_items_source_published ON news_items (source, published)",
    "CREATE INDEX IF NOT EXISTS idx_drafts_user_created_at ON drafts (user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_drafts_user_status ON drafts (user_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_usage_user_month_agent ON usage (user_id, year_month, agent_name)",
)
_connect_args = {}
_poolclass = None
_engine_kw = {"echo": False}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
    if ":memory:" in settings.database_url:
        _poolclass = StaticPool
else:
    # Supabase/pgbouncer: prepared statements вызывают ошибки в transaction pooling
    # timeout=120 — Render cold start + Supabase могут быть медленными
    _connect_args = {"statement_cache_size": 0, "timeout": 120}
    _engine_kw["pool_pre_ping"] = True
    _engine_kw["pool_recycle"] = 300

engine = create_async_engine(
    settings.database_url,
    connect_args=_connect_args if _connect_args else {},
    poolclass=_poolclass,
    **_engine_kw,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


def _is_postgres() -> bool:
    url = (settings.database_url or "").lower()
    return "postgresql" in url or "postgres" in url


async def init_db() -> None:
    """Create all tables and add new columns for existing DBs (SQLite and Postgres)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.database_url.startswith("sqlite"):
            try:
                await conn.execute(text("ALTER TABLE people ADD COLUMN is_kol BOOLEAN DEFAULT 0"))
            except Exception:
                pass
            try:
                await conn.execute(text("ALTER TABLE people ADD COLUMN feed_url VARCHAR(1024)"))
            except Exception:
                pass
            try:
                await conn.execute(text("ALTER TABLE contact_posts ADD COLUMN reply_variants TEXT"))
            except Exception:
                pass
            try:
                await conn.execute(text("ALTER TABLE contact_posts ADD COLUMN comment_written BOOLEAN DEFAULT 0"))
            except Exception:
                pass
            try:
                await conn.execute(text("ALTER TABLE reddit_posts ADD COLUMN relevance_score INTEGER"))
            except Exception:
                pass
            try:
                await conn.execute(text("ALTER TABLE reddit_posts ADD COLUMN relevance_flag VARCHAR(8)"))
            except Exception:
                pass
            try:
                await conn.execute(text("ALTER TABLE reddit_posts ADD COLUMN relevance_reason VARCHAR(256)"))
            except Exception:
                pass
            try:
                await conn.execute(text("ALTER TABLE reddit_posts ADD COLUMN status VARCHAR(32) DEFAULT 'new'"))
            except Exception:
                pass
            # Создаём таблицу users, если её нет
            try:
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email VARCHAR(256) NOT NULL UNIQUE,
                        password_hash VARCHAR(256) NOT NULL,
                        role VARCHAR(16) NOT NULL DEFAULT 'user',
                        subscription_status VARCHAR(32) NOT NULL DEFAULT 'free',
                        subscription_expires_at DATETIME,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        last_login_at DATETIME,
                        approval_status VARCHAR(16) NOT NULL DEFAULT 'approved'
                    )
                """))
            except Exception:
                pass
            try:
                await conn.execute(text("ALTER TABLE users ADD COLUMN approval_status VARCHAR(16) DEFAULT 'approved'"))
            except Exception:
                pass
            try:
                await conn.execute(text("ALTER TABLE users ADD COLUMN plan_name VARCHAR(32)"))
            except Exception:
                pass
            # Multi-tenant: user_id для companies, people, segments, reddit_posts, saved_subreddits, sales_avatar, offers, lead_magnets, drafts
            for table in ("companies", "people", "segments", "reddit_posts", "saved_subreddits", "sales_avatar", "offers", "lead_magnets", "drafts"):
                try:
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER"))
                except Exception:
                    pass
            # Миграция: назначить user_id=1 существующим записям
            for table in ("companies", "people", "segments", "reddit_posts", "saved_subreddits", "sales_avatar", "offers", "lead_magnets", "drafts"):
                try:
                    await conn.execute(text(f"UPDATE {table} SET user_id = 1 WHERE user_id IS NULL"))
                except Exception:
                    pass
            # KnowledgeBase: ключи legacy -> key:1 для user_id=1
            try:
                await conn.execute(text("""
                    UPDATE knowledge_base SET key = key || ':1'
                    WHERE key NOT LIKE '%:%' AND key IN (
                        'setup_authors','authors','setup_products','products',
                        'setup_icp_raw','setup_tone','setup_goals','saved_subreddits'
                    )
                """))
            except Exception:
                pass
        elif _is_postgres():
            # Добавляем колонки в reddit_posts на проде (Supabase), если их ещё нет
            for sql in (
                "ALTER TABLE reddit_posts ADD COLUMN IF NOT EXISTS relevance_score INTEGER",
                "ALTER TABLE reddit_posts ADD COLUMN IF NOT EXISTS relevance_flag VARCHAR(8)",
                "ALTER TABLE reddit_posts ADD COLUMN IF NOT EXISTS relevance_reason VARCHAR(256)",
                "ALTER TABLE reddit_posts ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'new'",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS approval_status VARCHAR(16) DEFAULT 'approved'",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_name VARCHAR(32)",
                "ALTER TABLE companies ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)",
                "ALTER TABLE people ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)",
                "ALTER TABLE segments ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)",
                "ALTER TABLE reddit_posts ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)",
                "ALTER TABLE saved_subreddits ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)",
                "ALTER TABLE sales_avatar ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)",
                "ALTER TABLE offers ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)",
                "ALTER TABLE lead_magnets ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)",
                "ALTER TABLE drafts ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)",
            ):
                try:
                    await conn.execute(text(sql))
                except Exception:
                    pass
            # Миграция: назначить user_id=1 существующим записям
            for table in ("companies", "people", "segments", "reddit_posts", "saved_subreddits", "sales_avatar", "offers", "lead_magnets", "drafts"):
                try:
                    await conn.execute(text(f"UPDATE {table} SET user_id = 1 WHERE user_id IS NULL"))
                except Exception:
                    pass
            # RedditPost: сменить unique constraint на (subreddit, reddit_id, user_id)
            try:
                await conn.execute(text("ALTER TABLE reddit_posts DROP CONSTRAINT IF EXISTS uq_reddit_posts_subreddit_reddit_id"))
                await conn.execute(text("ALTER TABLE reddit_posts ADD CONSTRAINT uq_reddit_posts_subreddit_reddit_id_user UNIQUE (subreddit, reddit_id, user_id)"))
            except Exception:
                pass
            # SavedSubreddit: сменить unique на (name, user_id)
            try:
                await conn.execute(text("ALTER TABLE saved_subreddits DROP CONSTRAINT IF EXISTS saved_subreddits_name_key"))
                await conn.execute(text("ALTER TABLE saved_subreddits DROP CONSTRAINT IF EXISTS uq_saved_subreddits_name_user"))
                await conn.execute(text("ALTER TABLE saved_subreddits ADD CONSTRAINT uq_saved_subreddits_name_user UNIQUE (name, user_id)"))
            except Exception:
                pass
            # KnowledgeBase: ключи legacy -> key:1 для user_id=1
            try:
                await conn.execute(text("""
                    UPDATE knowledge_base SET key = key || ':1'
                    WHERE key NOT LIKE '%:%' AND key IN (
                        'setup_authors','authors','setup_products','products',
                        'setup_icp_raw','setup_tone','setup_goals','saved_subreddits'
                    )
                """))
            except Exception:
                pass
            # Создаём таблицу users, если её нет (Postgres)
            # Используем Base.metadata.create_all для Postgres (уже вызывается выше)
            # Дополнительно проверяем существование через try/except
            pass
        for sql in PERFORMANCE_INDEXES:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


if __name__ == "__main__":
    import asyncio
    asyncio.run(init_db())
    print("DB initialized.")
