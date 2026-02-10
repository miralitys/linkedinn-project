# app/db.py
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.models import Base

# SQLite: need check_same_thread=False for aiosqlite. Postgres (Supabase): no special args.
_connect_args = {}
_poolclass = None
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
    if ":memory:" in settings.database_url:
        _poolclass = StaticPool

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args=_connect_args if _connect_args else {},
    poolclass=_poolclass,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def init_db() -> None:
    """Create all tables and add new columns for existing SQLite DBs."""
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
