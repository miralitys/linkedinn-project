# app/main.py
import asyncio
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
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
    news,
    plans,
    posts,
    reddit,
    setup,
    touches,
)
from app.routers import onboarding as onboarding_router

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Retry init_db — Render cold start + Supabase могут давать TimeoutError
    for attempt in range(3):
        try:
            await init_db()
            break
        except (TimeoutError, OSError) as e:
            if attempt < 2:
                logging.warning("init_db attempt %s failed (%s), retrying in 10s...", attempt + 1, e)
                await asyncio.sleep(10)
            else:
                raise
    settings.memory_dir.mkdir(parents=True, exist_ok=True)
    settings.prompts_dir.mkdir(parents=True, exist_ok=True)
    if settings.lfas_enable_scheduler:
        # Автоматическая подгрузка постов: по расписанию и один раз после старта
        scheduler.add_job(
            posts.run_auto_sync,
            "interval",
            hours=6,
            id="posts_auto_sync",
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
    else:
        logging.info("Background scheduler is disabled (LFAS_ENABLE_SCHEDULER=false)")
    yield
    if settings.lfas_enable_scheduler and scheduler.running:
        scheduler.shutdown(wait=False)


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
# NormalizePathMiddleware — редирект //path → /path (двойной слэш)
# SessionMiddleware должен быть добавлен ВТОРЫМ (последним в коде), чтобы он выполнился ПЕРВЫМ и инициализировал session.
# AuthMiddleware должен быть добавлен ПЕРВЫМ, чтобы он выполнился ПОСЛЕ SessionMiddleware и мог использовать session.
from app.middleware.auth import AuthMiddleware
from app.middleware.normalize_path import NormalizePathMiddleware
app.add_middleware(AuthMiddleware)
app.add_middleware(NormalizePathMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret or "lfas-change-me-in-production",
    max_age=30 * 24 * 3600,
    same_site="lax",
    https_only=getattr(settings, "session_https_only", False),
)

app.include_router(auth.router)
from app.routers import admin
app.include_router(admin.router)
app.include_router(setup.router)
app.include_router(onboarding_router.router)
app.include_router(companies.router)
app.include_router(people.router)
app.include_router(touches.router)
app.include_router(agents_routes.router)
app.include_router(posts.router)
app.include_router(reddit.router)
app.include_router(plans.router)
app.include_router(news.router)

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


from app.translations import get_tr
@app.get("/pricing", response_class=HTMLResponse)
@app.get("/pricing/", response_class=HTMLResponse)
async def pricing_ru(request: Request):
    """Pricing page — Russian."""
    r = _landing_templates.TemplateResponse(request, "pricing.html", {"locale": "ru", "tr": get_tr("ru")})
    r.set_cookie("locale", "ru", max_age=365 * 24 * 3600, samesite="lax")
    return r


@app.get("/en/pricing", response_class=HTMLResponse)
@app.get("/en/pricing/", response_class=HTMLResponse)
async def pricing_en(request: Request):
    """Pricing page — English."""
    r = _landing_templates.TemplateResponse(request, "pricing.html", {"locale": "en", "tr": get_tr("en")})
    r.set_cookie("locale", "en", max_age=365 * 24 * 3600, samesite="lax")
    return r


@app.get("/pricing2")
@app.get("/pricing2/")
async def pricing2_redirect(request: Request):
    """Redirect to main pricing."""
    return RedirectResponse(url="/pricing", status_code=302)


@app.get("/en/pricing2")
@app.get("/en/pricing2/")
async def pricing2_en_redirect(request: Request):
    """Redirect to main pricing (EN)."""
    return RedirectResponse(url="/en/pricing", status_code=302)


@app.get("/set-locale")
async def set_locale(request: Request, locale: str = "ru", next: str = "/ui/dashboard"):
    """Set locale cookie and redirect to next (for in-app language switch)."""
    loc = "en" if (locale and str(locale).strip().lower() == "en") else "ru"
    safe_next = next if next.startswith("/") and "//" not in next else "/ui/dashboard"
    r = RedirectResponse(url=safe_next, status_code=302)
    r.set_cookie("locale", loc, max_age=365 * 24 * 3600, samesite="lax")
    return r


# Mount UI templates and static if present
try:
    import json
    from datetime import datetime, timedelta

    from fastapi import Depends, HTTPException
    from fastapi.templating import Jinja2Templates
    from sqlalchemy import and_, func, or_, select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db import get_session
    from app.models import (
        ContactPost,
        NewsItem,
        Person,
        RedditPost,
        UserRole,
    )
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

    def _short_text(value, limit: int = 180) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "…"

    def _fmt_dt(value) -> str:
        if not value:
            return "-"
        try:
            return value.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "-"

    @app.get("/ui", response_class=HTMLResponse)
    async def ui_landing(request: Request):
        return RedirectResponse(url="/ui/dashboard", status_code=302)

    @app.get("/ui/setup", response_class=HTMLResponse)
    async def ui_setup(request: Request):
        return templates.TemplateResponse(
            request, "setup.html", {"request": request, **_app_context(request)}
        )

    @app.get("/ui/onboarding", response_class=HTMLResponse)
    async def ui_onboarding(request: Request):
        from app.onboarding_questions import get_all_questions_flat
        ctx = _app_context(request)
        return templates.TemplateResponse(
            request,
            "onboarding.html",
            {
                "request": request,
                **ctx,
                "questions_json": get_all_questions_flat(),
            },
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

    @app.get("/ui/dashboard", response_class=HTMLResponse)
    async def ui_dashboard(
        request: Request,
        session: AsyncSession = Depends(get_session),
    ):
        ctx = _app_context(request)
        user_id = request.session.get("user_id")
        since_24h = datetime.utcnow() - timedelta(days=1)

        news_items = []
        reddit_items = []
        comment_drafts = []
        comment_todo = []
        comment_drafts_total = 0
        comment_todo_total = 0

        # Новости: только за 24 часа, сортировка по максимальному скору (relevance_score) по убыванию.
        r_news = await session.execute(
            select(NewsItem)
            .where(
                or_(
                    NewsItem.published >= since_24h,
                    and_(NewsItem.published.is_(None), NewsItem.created_at >= since_24h),
                )
            )
            .order_by(
                func.coalesce(NewsItem.relevance_score, -1).desc(),
                func.coalesce(NewsItem.published, NewsItem.created_at).desc(),
            )
            .limit(3)
        )
        for item in r_news.scalars().all():
            published_dt = item.published or item.created_at
            news_items.append(
                {
                    "id": item.id,
                    "title": item.title,
                    "summary": _short_text(item.summary or item.content, 200),
                    "source": item.source or "",
                    "url": item.link,
                    "score": item.relevance_score,
                    "published_label": _fmt_dt(published_dt),
                }
            )

        if user_id:
            # Reddit: только за 24 часа, сортировка по max score по убыванию.
            r_reddit = await session.execute(
                select(RedditPost)
                .where(RedditPost.user_id == user_id)
                .where(RedditPost.posted_at >= since_24h)
                .order_by(
                    func.coalesce(RedditPost.score, -1).desc(),
                    RedditPost.posted_at.desc(),
                )
                .limit(3)
            )
            for post in r_reddit.scalars().all():
                reddit_items.append(
                    {
                        "id": post.id,
                        "title": post.title,
                        "content": _short_text(post.content, 200),
                        "subreddit": post.subreddit,
                        "url": post.post_url,
                        "score": post.score,
                        "posted_label": _fmt_dt(post.posted_at),
                    }
                )

            # LinkedIn-комментарии: отделяем "черновики" от "новых к генерации".
            r_posts = await session.execute(
                select(ContactPost, Person.full_name)
                .join(Person, Person.id == ContactPost.person_id)
                .where(Person.user_id == user_id)
                .where(ContactPost.archived.is_(False))
                .where(ContactPost.comment_written.is_(False))
                .order_by(ContactPost.posted_at.desc())
                .limit(250)
            )
            for post, person_name in r_posts.all():
                variants = post.reply_variants if isinstance(post.reply_variants, dict) else {}
                has_variants = any(str(variants.get(k, "")).strip() for k in ("short", "medium", "long"))
                if not has_variants and post.reply_variants and not isinstance(post.reply_variants, dict):
                    has_variants = bool(str(post.reply_variants).strip())
                row = {
                    "id": post.id,
                    "person_name": person_name or "-",
                    "title": _short_text(post.title or post.content, 140),
                    "url": post.post_url,
                    "posted_label": _fmt_dt(post.posted_at),
                }
                if has_variants:
                    comment_drafts_total += 1
                    if len(comment_drafts) < 6:
                        comment_drafts.append(row)
                else:
                    comment_todo_total += 1
                    if len(comment_todo) < 6:
                        comment_todo.append(row)

        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "request": request,
                **ctx,
                "news_items": news_items,
                "reddit_items": reddit_items,
                "comment_drafts": comment_drafts,
                "comment_todo": comment_todo,
                "comment_drafts_total": comment_drafts_total,
                "comment_todo_total": comment_todo_total,
            },
        )

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

    @app.get("/ui/posts-v2", response_class=HTMLResponse)
    async def ui_posts_v2(request: Request):
        if request.session.get("user_role") != UserRole.ADMIN.value:
            raise HTTPException(status_code=403, detail="Admin access required")
        try:
            tz = getattr(settings, "display_timezone", None) or "UTC"
            ctx = _app_context(request)
            return templates.TemplateResponse(
                request,
                "posts.html",
                {
                    "request": request,
                    **ctx,
                    "display_timezone": tz,
                    "comments_prompt_version": "high_engagement_2026",
                    "comments_page_variant_label": "Prompt v2",
                },
            )
        except Exception as e:
            import traceback
            logging.exception("Error rendering /ui/posts-v2: %s", e)
            try:
                ctx = _app_context(request)
                load_err = ctx["tr"].get("load_error", "Ошибка загрузки")
            except Exception:
                load_err = "Ошибка загрузки"
            tb = traceback.format_exc().replace("<", "&lt;").replace(">", "&gt;")
            return HTMLResponse(
                "<html><body style=\"font-family:sans-serif;padding:2rem;max-width:900px;margin:0 auto;\">"
                "<h1>" + load_err + "</h1><p>Не удалось открыть страницу v2. Попробуйте <a href=\"/logout\">выйти</a> и <a href=\"/login\">войти</a> снова, или вернуться на <a href=\"/\">главную</a>.</p>"
                "<p style=\"color:#666;font-size:0.9rem;\">Подробности (уберите после отладки):</p><pre style=\"background:#f1f5f9;padding:1rem;overflow:auto;font-size:12px;white-space:pre-wrap;\">" + tb + "</pre></body></html>",
                status_code=500,
            )

    @app.get("/ui/posts-premium-preview", response_class=HTMLResponse)
    async def ui_posts_premium_preview(request: Request):
        try:
            tz = getattr(settings, "display_timezone", None) or "UTC"
            ctx = _app_context(request)
            return templates.TemplateResponse(
                request,
                "posts_premium_preview.html",
                {"request": request, **ctx, "display_timezone": tz},
            )
        except Exception as e:
            import traceback
            logging.exception("Error rendering /ui/posts-premium-preview: %s", e)
            tb = traceback.format_exc().replace("<", "&lt;").replace(">", "&gt;")
            return HTMLResponse(
                "<html><body style=\"font-family:sans-serif;padding:2rem;max-width:900px;margin:0 auto;\">"
                "<h1>Ошибка загрузки</h1><p>Не удалось открыть preview-страницу.</p>"
                "<pre style=\"background:#f1f5f9;padding:1rem;overflow:auto;font-size:12px;white-space:pre-wrap;\">" + tb + "</pre></body></html>",
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

    @app.get("/ui/pricing", response_class=HTMLResponse)
    async def ui_pricing(request: Request):
        ctx = _app_context(request)
        return templates.TemplateResponse(
            request, "pricing.html", {"request": request, **ctx}
        )

    @app.get("/ui/pricing2", response_class=HTMLResponse)
    async def ui_pricing2(request: Request):
        ctx = _app_context(request)
        return templates.TemplateResponse(
            request, "pricing.html", {"request": request, **ctx}
        )

except Exception as e:
    logging.exception("UI routes failed to load (templates/static): %s", e)
