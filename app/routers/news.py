# app/routers/news.py
"""Новости из внешних RSS (Land Line Media и др.). Хранение в БД, автообновление раз в час, авто-скорринг новых."""
import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, List, Optional, Union
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, session_scope
from app.models import NewsItem, UserRole
from app.routers.setup import get_setup_for_scoring
from agents.registry import run_agent

try:
    import feedparser
except ImportError:
    feedparser = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    from readability import Document as ReadabilityDocument
except ImportError:
    ReadabilityDocument = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/news", tags=["news"])

NEWS_CACHE_TTL = 3600  # 1 час (для совместимости; основное хранение — БД)

LANDLINE_FEED_URL = "https://landline.media/feed/"
TT_NEWS_FEED_URL = "https://www.ttnews.com/rss.xml"
CDLLIFE_FEED_URLS = ("https://cdllife.com/feed/", "https://www.cdllife.com/feed/")
DAYS_BACK = 3
FEED_TIMEOUT = 20.0
FULL_ARTICLE_TIMEOUT = 20.0
MAX_ITEMS_FALLBACK = 25
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
USER_AGENT_BOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
FULL_ARTICLE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

ALLOWED_FULL_ARTICLE_DOMAINS = (
    "landline.media",
    "www.ttnews.com",
    "ttnews.com",
    "cdllife.com",
    "www.cdllife.com",
)


def _require_admin(request: Request) -> None:
    role = request.session.get("user_role")
    if role != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Admin access required")


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", text).replace("&nbsp;", " ").strip()


def _strip_scripts(html: str) -> str:
    """Удаляет script/style теги для безопасного отображения в iframe/в приложении."""
    if not html:
        return ""
    html = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<style\b[^>]*>[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
    return html


def _strip_links_from_html(html: str) -> str:
    """Убирает ссылки из HTML: теги <a> заменяются на их текстовое содержимое."""
    if not html or BeautifulSoup is None:
        return html
    try:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a"):
            a.replace_with(a.get_text() or "")
        return str(soup)
    except Exception:
        return html


def _extract_ttnews_article(html: str) -> Optional[str]:
    """Специальная вытяжка для ttnews.com (Drupal). Ищем field--name-body, node__content и т.п."""
    if not html or BeautifulSoup is None:
        return None
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["script", "style"]):
            tag.decompose()
        candidates = []
        # Drupal 8/9/10: field--name-body — основное тело статьи
        for tag in soup.find_all(class_=re.compile(r"field--name-body|field-name-body", re.I)):
            text = (tag.get_text() or "").strip()
            if len(text) >= 200:
                candidates.append((tag, len(text)))
        # node__content — контент ноды
        for tag in soup.find_all(class_=re.compile(r"node__content", re.I)):
            text = (tag.get_text() or "").strip()
            if len(text) >= 200 and tag not in [c[0] for c in candidates]:
                candidates.append((tag, len(text)))
        # layout-content, region-content, block-ttnews (Drupal layout / TT News)
        for tag in soup.find_all(class_=re.compile(r"layout-content|region-content|block-system-main-block|block-ttnews", re.I)):
            paras = tag.find_all("p")
            text = (tag.get_text() or "").strip()
            if len(paras) >= 3 and len(text) >= 400:
                candidates.append((tag, len(text)))
        # article с много параграфов
        for tag in soup.find_all("article"):
            paras = tag.find_all("p")
            text = (tag.get_text() or "").strip()
            if len(paras) >= 2 and len(text) >= 300:
                candidates.append((tag, len(text)))
        if candidates:
            best = max(candidates, key=lambda x: x[1])
            content = str(best[0])
        else:
            # Fallback: div с максимум <p> и текста
            best_div = None
            best_score = 0
            for tag in soup.find_all(["div", "section"]):
                paras = tag.find_all("p")
                text_len = len((tag.get_text() or "").strip())
                if len(paras) >= 2 and text_len >= 250:
                    score = len(paras) * 100 + text_len
                    if score > best_score:
                        best_score = score
                        best_div = tag
            if best_div:
                content = str(best_div)
            else:
                return None
        content = _strip_scripts(content)
        return content[:150000].strip() if len(content.strip()) >= 100 else None
    except Exception as e:
        logger.debug("TT News extraction failed: %s", e)
        return None


def _extract_article_html(html: str) -> Optional[str]:
    """Извлекает основной текст статьи из HTML (article/entry-content/body)."""
    if not html or BeautifulSoup is None:
        return None
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["script", "style"]):
            tag.decompose()
        # Селекторы по приоритету: типичные контейнеры статей (WordPress, Drupal/TT News, кастом)
        candidates = []
        main = (
            soup.find(id="main-content")
            or soup.find("article")
            or soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find(class_=re.compile(r"entry-content|article-body|post-content|article-content|content-area|story-body|node-content|field--name-body|node__content|field-name-body", re.I))
            or soup.find(class_=re.compile(r"content\b|article|post-body|block-content", re.I))
            or soup.find(id=re.compile(r"content|main|article-body", re.I))
        )
        if main:
            candidates.append(main)
        # Drupal: поле body статьи (часто внутри node)
        for tag in soup.find_all(class_=re.compile(r"field--name-body|field-name-body|node__content", re.I)):
            if tag not in candidates and len((tag.get_text() or "").strip()) > 200:
                candidates.append(tag)
        # Дополнительно: контейнер с несколькими параграфами (часто основной текст)
        for tag in soup.find_all(["article", "main", "div"]):
            if tag in (candidates or [None]):
                continue
            classes = " ".join(tag.get("class") or [])
            if not re.search(r"content|article|body|post|entry|story|node", classes, re.I):
                continue
            paragraphs = tag.find_all("p")
            if len(paragraphs) >= 2 and len((tag.get_text() or "").strip()) > 300:
                candidates.append(tag)
        # Берём самый объёмный блок (≥150 символов) — так находим статью на любых сайтах
        eligible = [c for c in candidates if c and len((c.get_text() or "").strip()) >= 150]
        best = max(eligible, key=lambda x: len((x.get_text() or "").strip())) if eligible else None
        if best is not None:
            content = str(best)
        else:
            # Универсальный запасной вариант: блок с максимум параграфов и достаточным текстом (ttnews и др.)
            all_divs = soup.find_all(["div", "section"])
            best_fallback = None
            best_para_count = 0
            best_text_len = 0
            for tag in all_divs:
                paras = tag.find_all("p")
                text_len = len((tag.get_text() or "").strip())
                if len(paras) >= 3 and text_len >= 400:
                    if len(paras) > best_para_count or (len(paras) == best_para_count and text_len > best_text_len):
                        best_para_count = len(paras)
                        best_text_len = text_len
                        best_fallback = tag
            if best_fallback is not None:
                content = str(best_fallback)
            else:
                body = soup.find("body")
                content = str(body) if body else str(soup)
        content = _strip_scripts(content)
        if len(content.strip()) < 100:
            return None
        return content[:150000].strip()
    except Exception as e:
        logger.warning("Article extraction failed: %s", e)
        return None


def _local_tag(tag: Optional[str]) -> str:
    if not tag:
        return ""
    return tag.split("}")[-1] if "}" in tag else tag


def _find_child(parent, local_name: str):
    for c in parent:
        if _local_tag(c.tag) == local_name:
            return c
    return None


def _elem_text(el) -> str:
    if el is None:
        return ""
    if el.text:
        return (el.text or "").strip()
    return " ".join((e.text or "").strip() for e in el.iter() if e.text).strip()


def _link_from_entry(entry_el) -> str:
    """Из Atom <entry> достаёт ссылку из <link href="..."/>."""
    for c in entry_el:
        if _local_tag(c.tag) != "link":
            continue
        href = c.get("href") if hasattr(c, "get") else None
        if href:
            return href.strip()
    return _elem_text(_find_child(entry_el, "link"))


def _parse_rss_with_etree(raw_content: Union[str, bytes], source: Optional[str] = None, source_url: Optional[str] = None) -> List[dict]:
    """Парсинг RSS 2.0 и Atom (item/entry). Работает с namespace."""
    if isinstance(raw_content, bytes):
        raw_content = raw_content.decode("utf-8", errors="replace")
    root = ET.fromstring(raw_content)
    items = []
    for el in root.iter():
        local = _local_tag(el.tag)
        if local not in ("item", "entry"):
            continue
        item = el
        title_el = _find_child(item, "title")
        title = _elem_text(title_el)
        if local == "entry":
            link = _link_from_entry(item)
            desc_el = _find_child(item, "content") or _find_child(item, "summary")
            pub_el = _find_child(item, "published") or _find_child(item, "updated")
        else:
            link_el = _find_child(item, "link")
            link = _elem_text(link_el)
            desc_el = _find_child(item, "description") or _find_child(item, "encoded")
            pub_el = _find_child(item, "pubDate")
        summary = _elem_text(desc_el) if desc_el is not None else ""
        published_iso = None
        if pub_el is not None and (getattr(pub_el, "text", None) or list(pub_el.iter())):
            raw_date = (pub_el.text or "").strip() or _elem_text(pub_el)
            if raw_date:
                dt = None
                try:
                    dt = parsedate_to_datetime(raw_date)
                except (ValueError, TypeError):
                    try:
                        dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    except Exception:
                        pass
                if dt:
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    published_iso = dt.isoformat()
        summary_plain = _strip_html(summary)
        summary_short = summary_plain[:497] + "..." if len(summary_plain) > 500 else summary_plain
        full_content = _strip_scripts(summary[:65535] if summary else "")
        row = {
            "title": (title or "Без заголовка")[:512],
            "link": link,
            "summary": summary_short,
            "published": published_iso,
            "content": full_content,
        }
        if source is not None:
            row["source"] = source
        if source_url is not None:
            row["sourceUrl"] = source_url
        items.append(row)
    return items


def _parse_published(entry: Any) -> Optional[datetime]:
    """Для feedparser: datetime из published_parsed."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


@router.get("/landline")
async def get_landline_news():
    """
    Загрузить новости Land Line Media за последние 3 суток из RSS.
    Работает с feedparser или без него (парсинг через xml.etree).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    try:
        async with httpx.AsyncClient(timeout=FEED_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(
                LANDLINE_FEED_URL,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                },
            )
            response.raise_for_status()
            raw_content = response.content
            try:
                raw_content = raw_content.decode("utf-8")
            except UnicodeDecodeError:
                raw_content = raw_content.decode("utf-8", errors="replace")
    except httpx.TimeoutException as e:
        logger.warning("Landline feed timeout: %s", e)
        raise HTTPException(status_code=502, detail="Таймаут при загрузке ленты. Попробуйте позже.")
    except httpx.HTTPError as e:
        logger.warning("Landline feed HTTP error: %s", e)
        raise HTTPException(status_code=502, detail=f"Не удалось загрузить ленту: {e!s}")

    items: List[dict] = []

    if feedparser is not None:
        feed = feedparser.parse(raw_content)
        if getattr(feed, "bozo_exception", None):
            logger.warning("Feed parse warning: %s", feed.bozo_exception)
        entries = feed.entries or []
        for entry in entries:
            published = _parse_published(entry)
            if published and published < cutoff:
                continue
            link = (entry.get("link") or "").strip()
            title = (entry.get("title") or "").strip() or "Без заголовка"
            summary = entry.get("summary") or entry.get("description") or ""
            summary_plain = _strip_html(summary)
            summary_short = summary_plain[:497] + "..." if len(summary_plain) > 500 else summary_plain
            full_content = _strip_scripts((summary or "")[:65535])
            published_iso = published.isoformat() if published else None
            items.append({"title": title[:512], "link": link, "summary": summary_short, "published": published_iso, "content": full_content, "source": "Land Line Media", "sourceUrl": "https://landline.media/news/"})
        if not items and entries:
            for entry in entries[:MAX_ITEMS_FALLBACK]:
                published = _parse_published(entry)
                link = (entry.get("link") or "").strip()
                title = (entry.get("title") or "").strip() or "Без заголовка"
                summary = entry.get("summary") or entry.get("description") or ""
                summary_plain = _strip_html(summary)
                summary_short = summary_plain[:497] + "..." if len(summary_plain) > 500 else summary_plain
                full_content = _strip_scripts((summary or "")[:65535])
                published_iso = published.isoformat() if published else None
                items.append({"title": title[:512], "link": link, "summary": summary_short, "published": published_iso, "content": full_content, "source": "Land Line Media", "sourceUrl": "https://landline.media/news/"})
    else:
        try:
            content = raw_content.lstrip("\ufeff")
            if "<!DOCTYPE" in content[:200] or "<html" in content[:200].lower():
                raise HTTPException(
                    status_code=502,
                    detail="Сервер вернул HTML вместо ленты. Проверьте подключение к интернету.",
                )
            all_items = _parse_rss_with_etree(content, source="Land Line Media", source_url="https://landline.media/news/")
            for it in all_items:
                pub = it.get("published")
                if pub:
                    try:
                        dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt < cutoff:
                            continue
                    except (ValueError, TypeError):
                        pass
                items.append(it)
            if not items and all_items:
                items = all_items[:MAX_ITEMS_FALLBACK]
        except HTTPException:
            raise
        except ET.ParseError as e:
            logger.warning("RSS XML parse error: %s", e)
            raise HTTPException(status_code=502, detail="Ошибка разбора ленты RSS.")
        except Exception as e:
            logger.exception("News landline parse: %s", e)
            raise HTTPException(status_code=502, detail=f"Ошибка загрузки новостей: {e!s}")

    items.sort(key=lambda x: x["published"] or "", reverse=True)
    return {"source": "Land Line Media", "items": items}


async def _fetch_ttnews(cutoff: datetime) -> List[dict]:
    """Загрузить новости Transport Topics (ttnews.com) за последние DAYS_BACK суток."""
    items: List[dict] = []
    try:
        async with httpx.AsyncClient(timeout=FEED_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(
                TT_NEWS_FEED_URL,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                },
            )
            response.raise_for_status()
            raw_content = response.content
            try:
                raw_content = raw_content.decode("utf-8")
            except UnicodeDecodeError:
                raw_content = raw_content.decode("utf-8", errors="replace")
    except (httpx.TimeoutException, httpx.HTTPError) as e:
        logger.warning("TT News feed error: %s", e)
        return items
    raw_content = raw_content.lstrip("\ufeff")
    if "<!DOCTYPE" in (raw_content[:200] or "") or "<html" in (raw_content[:200] or "").lower():
        return items
    try:
        all_items = _parse_rss_with_etree(
            raw_content,
            source="Transport Topics",
            source_url="https://www.ttnews.com/",
        )
        for it in all_items:
            pub = it.get("published")
            if pub:
                try:
                    dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
            items.append(it)
        if not items and all_items:
            items = all_items[:MAX_ITEMS_FALLBACK]
    except ET.ParseError as e:
        logger.warning("TT News RSS parse error: %s", e)
    except Exception as e:
        logger.exception("TT News parse: %s", e)
    return items


@router.get("/full")
async def get_full_article(url: str = Query(..., description="URL статьи для загрузки полного текста")):
    """
    Загружает страницу по URL и возвращает извлечённый основной контент статьи (HTML).
    Разрешены только домены наших источников новостей.
    """
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise HTTPException(status_code=400, detail="Некорректный URL.")
        domain = parsed.netloc.lower().lstrip("www.")
        if domain not in (d.lstrip("www.") for d in ALLOWED_FULL_ARTICLE_DOMAINS):
            allowed = ", ".join(ALLOWED_FULL_ARTICLE_DOMAINS)
            raise HTTPException(status_code=400, detail=f"Разрешены только URL с: {allowed}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail="Некорректный URL.")
    if BeautifulSoup is None:
        raise HTTPException(status_code=503, detail="Для извлечения полного текста установите beautifulsoup4.")
    try:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}/"
        netloc_lower = parsed.netloc.lower()
        headers = dict(FULL_ARTICLE_HEADERS)
        headers["Referer"] = origin
        async with httpx.AsyncClient(timeout=FULL_ARTICLE_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            raw = response.content
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                raw = raw.decode("utf-8", errors="replace")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Таймаут при загрузке статьи.")
    except httpx.HTTPError as e:
        logger.warning("Full article fetch failed: %s", e)
        raise HTTPException(status_code=502, detail="Не удалось загрузить страницу.")

    content: Optional[str] = None
    is_ttnews = "ttnews.com" in netloc_lower

    # Для ttnews.com: сначала пробуем Drupal-специфичную вытяжку (часто лучше readability)
    if is_ttnews:
        content = _extract_ttnews_article(raw)
        if content and len(content.strip()) >= 200:
            pass  # используем результат
        else:
            content = None

    # readability-lxml — универсальный вариант
    if (not content or len(content.strip()) < 100) and ReadabilityDocument is not None:
        try:
            doc = ReadabilityDocument(raw)
            extracted = doc.summary()
            if extracted and len(extracted.strip()) > 200:
                if not content or len(extracted.strip()) > len(content.strip()):
                    content = extracted
        except Exception as e:
            logger.debug("Readability extraction failed: %s", e)

    if not content or len(content.strip()) < 100:
        fallback = _extract_article_html(raw)
        if fallback and (not content or len(fallback.strip()) > len(content.strip())):
            content = fallback

    if not content or len(content.strip()) < 100:
        return {"content": None, "error": "Не удалось извлечь текст статьи."}
    content = _strip_links_from_html(content)
    return {"content": content}


async def _fetch_news_from_feeds() -> List[dict]:
    """Загружает новости из RSS-лент. Используется для кэша и ручного обновления."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    landline_items: List[dict] = []
    tt_items: List[dict] = []
    cdllife_items: List[dict] = []
    try:
        async with httpx.AsyncClient(timeout=FEED_TIMEOUT, follow_redirects=True) as client:
            # Land Line
            try:
                r_ll = await client.get(
                    LANDLINE_FEED_URL,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
                )
                r_ll.raise_for_status()
                raw_ll = r_ll.content
                try:
                    raw_ll = raw_ll.decode("utf-8")
                except UnicodeDecodeError:
                    raw_ll = raw_ll.decode("utf-8", errors="replace")
                raw_ll = raw_ll.lstrip("\ufeff")
                if not ("<!DOCTYPE" in raw_ll[:200] or "<html" in raw_ll[:200].lower()):
                    all_ll = _parse_rss_with_etree(raw_ll, source="Land Line Media", source_url="https://landline.media/news/")
                    for it in all_ll:
                        pub = it.get("published")
                        if pub:
                            try:
                                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                                if dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=timezone.utc)
                                if dt < cutoff:
                                    continue
                            except (ValueError, TypeError):
                                pass
                        landline_items.append(it)
                    if not landline_items and all_ll:
                        landline_items = all_ll[:MAX_ITEMS_FALLBACK]
            except Exception as e:
                logger.warning("Landline in merged feed: %s", e)
            # TT News
            try:
                r_tt = await client.get(
                    TT_NEWS_FEED_URL,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
                )
                r_tt.raise_for_status()
                raw_tt = r_tt.content
                try:
                    raw_tt = raw_tt.decode("utf-8")
                except UnicodeDecodeError:
                    raw_tt = raw_tt.decode("utf-8", errors="replace")
                raw_tt = raw_tt.lstrip("\ufeff")
                if not ("<!DOCTYPE" in raw_tt[:200] or "<html" in raw_tt[:200].lower()):
                    all_tt = _parse_rss_with_etree(raw_tt, source="Transport Topics", source_url="https://www.ttnews.com/")
                    for it in all_tt:
                        pub = it.get("published")
                        if pub:
                            try:
                                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                                if dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=timezone.utc)
                                if dt < cutoff:
                                    continue
                            except (ValueError, TypeError):
                                pass
                        tt_items.append(it)
                    if not tt_items and all_tt:
                        tt_items = all_tt[:MAX_ITEMS_FALLBACK]
            except Exception as e:
                logger.warning("TT News in merged feed: %s", e)
            # CDLLife — пробуем основной feed и с www
            for cdl_url in CDLLIFE_FEED_URLS:
                if cdllife_items:
                    break
                try:
                    r_cdl = await client.get(
                        cdl_url,
                        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
                    )
                    if r_cdl.status_code != 200:
                        continue
                    raw_cdl = r_cdl.content
                    try:
                        raw_cdl = raw_cdl.decode("utf-8")
                    except UnicodeDecodeError:
                        raw_cdl = raw_cdl.decode("utf-8", errors="replace")
                    raw_cdl = raw_cdl.lstrip("\ufeff")
                    if "<!DOCTYPE" in raw_cdl[:200] or "<html" in raw_cdl[:200].lower():
                        continue
                    all_cdl = _parse_rss_with_etree(raw_cdl, source="CDLLife", source_url="https://cdllife.com/news/")
                    for it in all_cdl:
                        pub = it.get("published")
                        if pub:
                            try:
                                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                                if dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=timezone.utc)
                                if dt < cutoff:
                                    continue
                            except (ValueError, TypeError):
                                pass
                        cdllife_items.append(it)
                    if not cdllife_items and all_cdl:
                        cdllife_items = all_cdl[:MAX_ITEMS_FALLBACK]
                except Exception as e:
                    logger.warning("CDLLife feed %s: %s", cdl_url, e)
    except httpx.TimeoutException:
        raise HTTPException(status_code=502, detail="Таймаут при загрузке лент. Попробуйте позже.")
    merged = landline_items + tt_items + cdllife_items
    merged.sort(key=lambda x: x.get("published") or "", reverse=True)
    return merged


def _news_item_to_dict(n: NewsItem) -> dict:
    """Формат элемента для фронта (как раньше: title, link, summary, published, source, sourceUrl, score)."""
    return {
        "id": n.id,
        "title": n.title or "",
        "link": n.link or "",
        "summary": n.summary or "",
        "content": n.content or "",
        "published": n.published_iso or (n.published.isoformat() if n.published else ""),
        "source": n.source or "",
        "sourceUrl": n.source_url or "",
        "score": getattr(n, "relevance_score", None),
        "score_flag": getattr(n, "relevance_flag", None),
        "score_reason": getattr(n, "relevance_reason", None),
    }


async def _save_fetched_news_to_db(session: AsyncSession, items: List[dict]) -> tuple[int, list[int]]:
    """Добавляет в БД только новые новости (по link). Возвращает (количество, ids)."""
    if not items:
        return 0, []
    links = [it.get("link") or "" for it in items if it.get("link")]
    if not links:
        return 0, []
    r = await session.execute(select(NewsItem.link).where(NewsItem.link.in_(links)))
    existing = {row[0] for row in r.fetchall()}
    added_rows: list[NewsItem] = []
    for it in items:
        link = (it.get("link") or "").strip()
        if not link or link in existing:
            continue
        existing.add(link)
        published = it.get("published")
        pub_dt = None
        if published is not None:
            try:
                if isinstance(published, datetime):
                    pub_dt = published
                else:
                    pub_dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
                # Postgres TIMESTAMP WITHOUT TIME ZONE + asyncpg требуют naive datetime
                if pub_dt.tzinfo is not None:
                    pub_dt = pub_dt.astimezone(timezone.utc).replace(tzinfo=None)
            except (ValueError, TypeError):
                pass
        published_iso_str = published.isoformat() if isinstance(published, datetime) else (published or "")
        row = NewsItem(
            link=link[:2048],
            title=(it.get("title") or "")[:1024],
            summary=it.get("summary"),
            content=it.get("content"),
            published=pub_dt,
            published_iso=published_iso_str or None,
            source=it.get("source"),
            source_url=it.get("source_url"),
        )
        session.add(row)
        added_rows.append(row)
    if added_rows:
        await session.flush()
    added_ids = [n.id for n in added_rows if n.id is not None]
    return len(added_rows), added_ids


@router.get("")
@router.get("/")
async def get_news_merged(
    session: AsyncSession = Depends(get_session),
    source_filter: Optional[str] = Query(None, alias="source", description="Фильтр по источнику"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Лента новостей из БД. Данные хранятся в БД; новые подгружаются при POST /news/refresh или по расписанию раз в час.
    """
    q = select(NewsItem).order_by(NewsItem.published.desc().nullslast(), NewsItem.id.desc())
    if source_filter:
        q = q.where(NewsItem.source == source_filter)
    q = q.limit(limit).offset(offset)
    r = await session.execute(q)
    rows = list(r.scalars().all())
    items = [_news_item_to_dict(n) for n in rows]
    return {"items": items}


async def _run_scoring_for_pending_news(item_ids: Optional[list[int]] = None) -> None:
    """Фоновая задача: проставить score новостям, у которых relevance_score ещё не задан."""
    from app.models import User
    async with session_scope() as session:
        try:
            r = await session.execute(select(User.id).limit(1))
            row = r.first()
            user_id = row[0] if row else 1
            setup = await get_setup_for_scoring(session, user_id)
            q = select(NewsItem).where(NewsItem.relevance_score.is_(None))
            if item_ids:
                q = q.where(NewsItem.id.in_(item_ids))
            q = q.order_by(NewsItem.id.asc())
            r = await session.execute(q)
            pending = list(r.scalars().all())
            if not pending:
                return
            logger.info("Scoring %d pending news items", len(pending))
            for item in pending:
                try:
                    payload = {
                        "title": item.title or "",
                        "body": item.summary or item.content or "",
                        **setup,
                    }
                    result = await run_agent("scoring_agent", payload)
                    if result and result.get("score") is not None:
                        item.relevance_score = result["score"]
                        item.relevance_flag = (result.get("flag") or "")[:8]
                        item.relevance_reason = (result.get("reason") or "")[:256]
                except Exception as e:
                    logger.warning("Scoring failed for news id=%s: %s", item.id, e)
                await session.flush()
        except Exception as e:
            logger.exception("Pending news scoring failed: %s", e)


@router.post("/refresh")
async def refresh_news(
    request: Request,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Загрузить новости из RSS, добавить новые в БД и вернуть актуальный список из БД. По новым запускается скоринг."""
    _require_admin(request)
    try:
        items = await _fetch_news_from_feeds()
        added, added_ids = await _save_fetched_news_to_db(session, items)
        await session.commit()
        if added_ids:
            asyncio.create_task(_run_scoring_for_pending_news(item_ids=added_ids))
        # Возвращаем список из БД
        r = await session.execute(
            select(NewsItem)
            .order_by(NewsItem.published.desc().nullslast(), NewsItem.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list(r.scalars().all())
        out = [_news_item_to_dict(n) for n in rows]
        return {"items": out, "refreshed": True, "added": added}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("News refresh failed: %s", e)
        await session.rollback()
        raise HTTPException(status_code=502, detail=f"Ошибка обновления: {e}")


async def run_news_refresh() -> None:
    """Фоновая задача: загрузить новости из RSS и добавить новые в БД (раз в час). По новым запускается скоринг."""
    async with session_scope() as session:
        try:
            items = await _fetch_news_from_feeds()
            _added, added_ids = await _save_fetched_news_to_db(session, items)
        except Exception as e:
            logger.exception("Scheduled news refresh failed: %s", e)
            return
    if added_ids:
        asyncio.create_task(_run_scoring_for_pending_news(item_ids=added_ids))


@router.patch("/items/{item_id}/score")
async def save_news_score(
    item_id: int,
    body: dict,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Сохранить оценку релевантности для новости (после скорринга)."""
    _require_admin(request)
    r = await session.execute(select(NewsItem).where(NewsItem.id == item_id))
    row = r.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Новость не найдена")
    score = body.get("score")
    if score is not None:
        row.relevance_score = int(score)
    if body.get("flag"):
        row.relevance_flag = str(body["flag"])[:8]
    if body.get("reason"):
        row.relevance_reason = str(body["reason"])[:256]
    await session.commit()
    return {"ok": True, "score": row.relevance_score}
