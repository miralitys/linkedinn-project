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
    auth,
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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Ловим любую необработанную ошибку и показываем traceback для отладки."""
    import traceback
    logging.exception("Unhandled error for %s: %s", request.url.path, exc)
    tb = traceback.format_exc().replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(
        '<html><body style="font-family:sans-serif;padding:2rem;max-width:900px;margin:0 auto;">'
        "<h1>Ошибка сервера</h1>"
        "<p>Что-то пошло не так. Попробуйте <a href=\"/logout\">выйти</a> и войти снова, или вернуться на <a href=\"/\">главную</a>.</p>"
        "<p style=\"color:#666;font-size:0.9rem;\">Traceback:</p><pre style=\"background:#f1f5f9;padding:1rem;overflow:auto;font-size:12px;white-space:pre-wrap;\">"
        + tb
        + "</pre></body></html>",
        status_code=500,
    )


# Порядок важен: последний add_middleware = первый по цепочке запроса.
# SessionMiddleware должен быть добавлен ВТОРЫМ (последним в коде), чтобы он выполнился ПЕРВЫМ и инициализировал session.
# AuthMiddleware должен быть добавлен ПЕРВЫМ, чтобы он выполнился ПОСЛЕ SessionMiddleware и мог использовать session.
from app.middleware.auth import AuthMiddleware
app.add_middleware(AuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret or "lfas-change-me-in-production",
    max_age=30 * 24 * 3600,
)

app.include_router(auth.router)
from app.routers import admin
app.include_router(admin.router)
app.include_router(setup.router)
app.include_router(companies.router)
app.include_router(people.router)
app.include_router(touches.router)
app.include_router(agents_routes.router)
app.include_router(posts.router)
app.include_router(reddit.router)
app.include_router(news.router)
app.include_router(linkedin_oauth.router)

# Главная страница (лендинг) — всегда регистрируем, без зависимости от try ниже
from fastapi.templating import Jinja2Templates as _Jinja2Templates
_landing_templates = _Jinja2Templates(directory=str(settings.base_dir / "templates"))

def _landing_response(request: Request, template: str, locale: str):
    r = _landing_templates.TemplateResponse(request, template, {"locale": locale})
    r.set_cookie("locale", locale, max_age=365 * 24 * 3600, samesite="lax")
    return r


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Главная страница — лендинг (русский)."""
    return _landing_response(request, "index.html", "ru")


@app.get("/en", response_class=HTMLResponse)
@app.get("/en/", response_class=HTMLResponse)
async def root_en(request: Request):
    """Landing page — English."""
    return _landing_response(request, "index_en.html", "en")


@app.get("/set-locale")
async def set_locale(request: Request, locale: str = "ru", next: str = "/ui/posts"):
    """Set locale cookie and redirect to next (for in-app language switch)."""
    loc = "en" if (locale and str(locale).strip().lower() == "en") else "ru"
    safe_next = next if next.startswith("/") and "//" not in next else "/ui/posts"
    r = RedirectResponse(url=safe_next, status_code=302)
    r.set_cookie("locale", loc, max_age=365 * 24 * 3600, samesite="lax")
    return r


# Mount UI templates and static if present
try:
    import json
    from fastapi.templating import Jinja2Templates

    from app.translations import RU, get_locale_from_cookie, get_tr

    templates = Jinja2Templates(directory=str(settings.base_dir / "templates"))
    templates.env.filters["tojson"] = lambda x: json.dumps(x, ensure_ascii=False)
    static_dir = settings.base_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def _app_context(request: Request):
        try:
            locale = get_locale_from_cookie(getattr(request, "cookies", None))
            return {"locale": locale, "tr": get_tr(locale)}
        except Exception:
            return {"locale": "ru", "tr": RU}

    @app.get("/ui", response_class=HTMLResponse)
    async def ui_landing(request: Request):
        ctx = {"request": request, **_app_context(request)}
        template = "index_en.html" if ctx.get("locale") == "en" else "index.html"
        return templates.TemplateResponse(request, template, ctx)

    @app.get("/ui/setup", response_class=HTMLResponse)
    async def ui_setup(request: Request):
        return templates.TemplateResponse(
            request, "setup.html", {"request": request, **_app_context(request)}
        )

    @app.get("/ui/companies", response_class=HTMLResponse)
    async def ui_companies(request: Request):
        return templates.TemplateResponse(
            request, "companies.html", {"request": request, **_app_context(request)}
        )

    @app.get("/ui/people", response_class=HTMLResponse)
    async def ui_people(request: Request):
        return templates.TemplateResponse(
            request, "people.html", {"request": request, **_app_context(request)}
        )

    @app.get("/ui/kol")
    async def ui_kol_redirect():
        return RedirectResponse(url="/ui/people", status_code=302)

    @app.get("/ui/posts", response_class=HTMLResponse)
    async def ui_posts(request: Request):
        try:
            tz = getattr(settings, "display_timezone", None) or "UTC"
            ctx = _app_context(request)
            return templates.TemplateResponse(
                request,
                "posts.html",
                {"request": request, **ctx, "display_timezone": tz},
            )
        except Exception as e:
            import traceback
            logging.exception("Error rendering /ui/posts: %s", e)
            try:
                ctx = _app_context(request)
                load_err = ctx["tr"].get("load_error", "Ошибка загрузки")
            except Exception:
                load_err = "Ошибка загрузки"
            tb = traceback.format_exc().replace("<", "&lt;").replace(">", "&gt;")
            return HTMLResponse(
                "<html><body style=\"font-family:sans-serif;padding:2rem;max-width:900px;margin:0 auto;\">"
                "<h1>" + load_err + "</h1><p>Не удалось открыть страницу. Попробуйте <a href=\"/logout\">выйти</a> и <a href=\"/login\">войти</a> снова, или вернуться на <a href=\"/\">главную</a>.</p>"
                "<p style=\"color:#666;font-size:0.9rem;\">Подробности (уберите после отладки):</p><pre style=\"background:#f1f5f9;padding:1rem;overflow:auto;font-size:12px;white-space:pre-wrap;\">" + tb + "</pre></body></html>",
                status_code=500,
            )

    @app.get("/ui/reddit", response_class=HTMLResponse)
    async def ui_reddit(request: Request):
        return templates.TemplateResponse(
            request,
            "reddit.html",
            {"request": request, **_app_context(request), "display_timezone": settings.display_timezone},
        )

    @app.get("/ui/news", response_class=HTMLResponse)
    async def ui_news(request: Request):
        return templates.TemplateResponse(
            request, "news.html", {"request": request, **_app_context(request)}
        )
except Exception as e:
    logging.exception("UI routes failed to load (templates/static): %s", e)
