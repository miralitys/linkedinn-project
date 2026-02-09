# app/main.py
import asyncio
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.db import init_db
from app.routers import (
    agents_routes,
    companies,
    people,
    linkedin_oauth,
    news,
    posts,
    reddit,
    setup,
    touches,
)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    settings.memory_dir.mkdir(parents=True, exist_ok=True)
    settings.prompts_dir.mkdir(parents=True, exist_ok=True)
    # Автоматическая подгрузка постов: по расписанию и один раз после старта
    scheduler.add_job(
        posts.run_auto_sync,
        "interval",
        hours=6,
        id="posts_auto_sync",
        replace_existing=True,
    )
    scheduler.add_job(
        linkedin_oauth.run_linkedin_analytics_sync,
        "interval",
        hours=24,
        id="linkedin_analytics_sync",
        replace_existing=True,
    )
    # Новости и Reddit: раз в час подгружаем новые в БД
    scheduler.add_job(
        news.run_news_refresh,
        "interval",
        hours=1,
        id="news_refresh",
        replace_existing=True,
    )
    scheduler.add_job(
        reddit.run_reddit_sync_all,
        "interval",
        hours=1,
        id="reddit_sync_all",
        replace_existing=True,
    )
    scheduler.start()

    async def sync_once_after_start():
        await asyncio.sleep(15)
        try:
            await posts.run_auto_sync()
        except Exception as e:
            logging.exception("Posts auto-sync at startup: %s", e)
        try:
            await news.run_news_refresh()
        except Exception as e:
            logging.exception("News refresh at startup: %s", e)
        try:
            await reddit.run_reddit_sync_all()
        except Exception as e:
            logging.exception("Reddit sync at startup: %s", e)

    asyncio.create_task(sync_once_after_start())
    yield
    scheduler.shutdown()


app = FastAPI(title="MyVOICE's", description="LinkedIn Funnel Agent System", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret or "lfas-change-me-in-production")

app.include_router(setup.router)
app.include_router(companies.router)
app.include_router(people.router)
app.include_router(touches.router)
app.include_router(agents_routes.router)
app.include_router(posts.router)
app.include_router(reddit.router)
app.include_router(news.router)
app.include_router(linkedin_oauth.router)


@app.get("/")
async def root():
    return {"app": "MyVOICE's", "docs": "/docs", "ui": "/ui"}


# Mount UI templates and static if present
try:
    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=str(settings.base_dir / "templates"))
    static_dir = settings.base_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/ui")
    async def ui_redirect():
        return RedirectResponse(url="/ui/posts", status_code=302)

    @app.get("/ui/setup", response_class=HTMLResponse)
    async def ui_setup(request: Request):
        return templates.TemplateResponse(request, "setup.html")

    @app.get("/ui/companies", response_class=HTMLResponse)
    async def ui_companies(request: Request):
        return templates.TemplateResponse(request, "companies.html")

    @app.get("/ui/people", response_class=HTMLResponse)
    async def ui_people(request: Request):
        return templates.TemplateResponse(request, "people.html")

    @app.get("/ui/kol")
    async def ui_kol_redirect():
        """Раздел KOL убран — лидеры мнений отмечаются в контактах. Редирект на контакты."""
        return RedirectResponse(url="/ui/people", status_code=302)

    @app.get("/ui/posts", response_class=HTMLResponse)
    async def ui_posts(request: Request):
        return templates.TemplateResponse(request, "posts.html", {"display_timezone": settings.display_timezone})

    @app.get("/ui/reddit", response_class=HTMLResponse)
    async def ui_reddit(request: Request):
        return templates.TemplateResponse(request, "reddit.html", {"display_timezone": settings.display_timezone})

    @app.get("/ui/news", response_class=HTMLResponse)
    async def ui_news(request: Request):
        return templates.TemplateResponse(request, "news.html")
except Exception as e:
    logging.exception("UI routes failed to load (templates/static): %s", e)
