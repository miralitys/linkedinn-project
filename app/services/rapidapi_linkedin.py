"""
Сервис RapidAPI — Fresh LinkedIn Profile Data.
Получение данных поста по URL без Playwright, если задан RAPIDAPI_KEY.

1. Сначала пробуем Get Post Details (urn/post_url) — работает для feed/update и posts/.
2. Если нет — Get Profile Posts (только для posts/username_activity-XXX).
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Any, List, Optional, Union

import httpx

from app.config import settings


def _extract_urn(post_url: str) -> Optional[str]:
    """Извлекает activity URN (числовой ID) из URL поста."""
    if not post_url or "linkedin.com" not in post_url:
        return None
    m = re.search(r"urn:li:activity:(\d+)", post_url, re.I)
    if m:
        return m.group(1)
    m = re.search(r"_activity-(\d+)-", post_url, re.I)
    if m:
        return m.group(1)
    return None


def _extract_profile_url_from_post(post_url: str) -> Optional[str]:
    """
    Извлекает URL профиля автора из URL поста LinkedIn.
    Работает только для формата: https://www.linkedin.com/posts/username_activity-123456789-xxx
    Возвращает https://www.linkedin.com/in/username
    Для feed/update/urn:li:activity:XXX профиль извлечь нельзя → None
    """
    if not post_url or "linkedin.com" not in post_url:
        return None
    # posts/username_activity-123456789-xxx или posts/username-activity-123456789-xxx
    m = re.search(r"linkedin\.com/posts/([^/_]+)_?activity-\d+", post_url, re.I)
    if m:
        username = m.group(1)
        return f"https://www.linkedin.com/in/{username}"
    return None


# Месяцы для парсинга "7 фев 2026", "7 февраля 2026"
_RU_MONTHS = {
    "янв": 1, "января": 1, "фев": 2, "февраля": 2, "февр": 2,
    "мар": 3, "марта": 3, "апр": 4, "апреля": 4,
    "май": 5, "мая": 5, "июн": 6, "июня": 6, "июл": 7, "июля": 7,
    "авг": 8, "августа": 8, "сен": 9, "сентября": 9, "окт": 10, "октября": 10,
    "ноя": 11, "ноября": 11, "дек": 12, "декабря": 12,
}
_EN_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_posted_at(raw: Any) -> datetime:
    """
    Парсит дату создания поста в LinkedIn (не дату загрузки в систему).
    - datetime: как есть
    - int/float: timestamp (ms или s)
    - "2023-11-23 09:39:26": ISO
    - "7 фев 2026", "7 февраля 2026": русская дата
    - "1d", "5 дн.": относительная
    """
    now = datetime.utcnow()
    if raw is None:
        return now
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, (int, float)):
        try:
            ts = raw / 1000 if raw > 1e12 else raw
            return datetime.utcfromtimestamp(ts)
        except (ValueError, OSError):
            return now
    if isinstance(raw, str):
        s = raw.strip()
        if not s or s.lower() == "unknown":
            return now
        import re
        # ISO: "2023-11-23 09:39:26" или "2023-11-23T09:39:26"
        try:
            s19 = s[:19].replace("T", " ").replace("Z", "")
            return datetime.strptime(s19, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
        # DD.MM.YYYY или DD.MM.YY
        m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})$", s)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000
            try:
                return datetime(y, mo, d)
            except ValueError:
                pass
        # "7 фев 2026", "7 фев. 2026", "7 февраля 2026"
        m_ru = re.match(r"^(\d{1,2})\s+([а-яё]+)\.?\s*(\d{4})$", s, re.I)
        if m_ru:
            day = int(m_ru.group(1))
            mon_str = m_ru.group(2).lower()
            year = int(m_ru.group(3))
            for k, v in _RU_MONTHS.items():
                if mon_str.startswith(k) or k.startswith(mon_str[:3]):
                    try:
                        return datetime(year, v, day)
                    except ValueError:
                        break
        # "7 Feb 2026", "Feb 7, 2026"
        m_en = re.match(r"^(\d{1,2})\s+([a-z]+)\s+(\d{4})$", s, re.I)
        if m_en:
            day, mon_str, year = int(m_en.group(1)), m_en.group(2).lower()[:3], int(m_en.group(3))
            if mon_str in _EN_MONTHS:
                try:
                    return datetime(year, _EN_MONTHS[mon_str], day)
                except ValueError:
                    pass
        # Относительная: 1d, 2w, 5 дн., 1 нед.
        s_lower = s.lower()
        m = re.match(r"^(\d+)\s*(d|w|mo|h|m)$", s_lower)
        if m:
            n, u = int(m.group(1)), m.group(2)
            delta = {"h": timedelta(hours=n), "d": timedelta(days=n), "w": timedelta(weeks=n),
                     "mo": timedelta(days=n * 30), "m": timedelta(minutes=n)}.get(u)
            if delta:
                return now - delta
        m_ru = re.match(r"^(\d+)\s*(дн\.?|нед\.?|мес\.?|ч\.?|мин\.?|час\.?)$", s_lower)
        if m_ru:
            n, u = int(m_ru.group(1)), m_ru.group(2).rstrip(".")
            u_map = {"ч": "h", "час": "h", "дн": "d", "нед": "w", "мес": "mo", "мин": "m"}
            u_en = u_map.get(u, "d")
            delta = {"h": timedelta(hours=n), "d": timedelta(days=n), "w": timedelta(weeks=n),
                     "mo": timedelta(days=n * 30), "m": timedelta(minutes=n)}.get(u_en, timedelta(days=n))
            return now - delta
        # "5 days ago", "2 weeks", "1 month ago"
        m_ago = re.match(r"^(\d+)\s*(day|days|week|weeks|month|months|hour|hours)\s*(ago)?$", s_lower)
        if m_ago:
            n = int(m_ago.group(1))
            unit = m_ago.group(2)
            if unit in ("day", "days"):
                return now - timedelta(days=n)
            if unit in ("week", "weeks"):
                return now - timedelta(weeks=n)
            if unit in ("month", "months"):
                return now - timedelta(days=n * 30)
            if unit in ("hour", "hours"):
                return now - timedelta(hours=n)
    return now


def _int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


async def _fetch_via_get_post_details(post_url: str, urn: str, host: str, key: str) -> Optional[dict[str, Any]]:
    """
    Пробует Get Post Details. Возвращает результат или None при 404/ошибке.
    """
    api_url = f"https://{host}/get-post-details"
    params = {"urn": urn}
    headers = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": host}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(api_url, params=params, headers=headers)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        logging.warning("RapidAPI Get Post Details HTTP error: %s %s", e.response.status_code, e.response.text[:200])
        return {"error": f"RapidAPI: HTTP {e.response.status_code}."}
    except Exception as e:
        logging.debug("RapidAPI Get Post Details failed: %s", e)
        return None

    data = body.get("data")
    if not data or not isinstance(data, dict):
        msg = body.get("message") or "Пустой ответ."
        return {"error": msg}

    # Маппинг ответа Get Post Details (Fresh LinkedIn: poster, text, num_*)
    text = data.get("text") or data.get("content") or ""
    poster = data.get("poster") or data.get("author") or {}
    if isinstance(poster, dict):
        first = poster.get("first") or ""
        last = poster.get("last") or ""
        author_name = f"{first} {last}".strip() or "Unknown"
        author_profile_url = poster.get("linkedin_url") or poster.get("url")
    else:
        author_name = str(poster) if poster else "Unknown"
        author_profile_url = None

    num_likes = _int(data.get("num_likes") or data.get("num_reactions") or data.get("num_appreciations"))

    media_present = bool(
        data.get("images")
        or data.get("video")
        or data.get("document")
        or (isinstance(data.get("document"), dict) and data.get("document"))
    )

    return {
        "author_name": (author_name or "Unknown").strip(),
        "author_profile_url": author_profile_url,
        "post_url": data.get("post_url") or data.get("url") or post_url,
        "published_at": data.get("posted") or data.get("posted_at") or data.get("created_at") or data.get("time") or data.get("published_at"),
        "text": str(text).strip() if text else "",
        "media_present": media_present,
        "reactions_count": num_likes,
        "comments_count": _int(data.get("num_comments")),
        "reposts_count": _int(data.get("num_reposts")),
        "views_count": _int(data.get("views_count") or data.get("num_views")),
    }


async def fetch_post_via_rapidapi(post_url: str) -> dict[str, Any]:
    """
    Получает данные поста LinkedIn через RapidAPI (Fresh LinkedIn Profile Data).
    1. Сначала пробует Get Post Details (urn) — для любых URL.
    2. Если нет — Get Profile Posts (только для posts/username_activity-XXX).

    Возвращает словарь в формате post_parser.
    При ошибке: {"error": "..."}.
    """
    key = settings.rapidapi_key
    host = settings.rapidapi_host or "fresh-linkedin-profile-data.p.rapidapi.com"
    if not key:
        return {"error": "RAPIDAPI_KEY не задан."}

    target_urn = _extract_urn(post_url)

    # 1. Пробуем Get Post Details (если есть urn)
    if target_urn:
        result = await _fetch_via_get_post_details(post_url, target_urn, host, key)
        if result is not None and "error" not in result:
            return result
        if result and "error" in result:
            return result  # явная ошибка API

    # 2. Fallback: Get Profile Posts (только для posts/username_activity-XXX)
    profile_url = _extract_profile_url_from_post(post_url)
    if not profile_url:
        return {"error": "Fresh LinkedIn: Get Post Details недоступен, а для feed/update/urn:li:activity:XXX профиль неизвестен. Используйте Playwright."}
    api_url = f"https://{host}/get-profile-posts"
    params = {"linkedin_url": profile_url, "type": "posts"}
    headers = {
        "X-RapidAPI-Key": key,
        "X-RapidAPI-Host": host,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(api_url, params=params, headers=headers)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPStatusError as e:
        logging.warning("RapidAPI Fresh LinkedIn get-profile-posts HTTP error: %s %s", e.response.status_code, e.response.text[:200])
        return {"error": f"RapidAPI: HTTP {e.response.status_code}."}
    except Exception as e:
        logging.exception("RapidAPI Fresh LinkedIn get-profile-posts failed: %s", e)
        return {"error": str(e)}

    if body.get("message", "").lower() not in ("ok", "ok."):
        msg = body.get("message") or "Ошибка RapidAPI."
        return {"error": msg}

    data_list = body.get("data")
    if not data_list or not isinstance(data_list, list):
        return {"error": "RapidAPI вернул пустой data."}

    # Ищем пост по post_url или urn
    post = None
    for item in data_list:
        item_url = (item.get("post_url") or "").strip()
        item_urn = str(item.get("urn", "")).strip()
        if target_urn and (target_urn in item_url or target_urn == item_urn):
            post = item
            break
        if item_url and post_url.rstrip("/") in item_url:
            post = item
            break
        if item_url == post_url or item_url.rstrip("/") == post_url.rstrip("/"):
            post = item
            break

    if not post:
        return {"error": "Пост не найден в ленте профиля (возможно, он удалён или скрыт)."}

    text = post.get("text") or ""
    # Fresh LinkedIn разбивает реакции: num_likes, num_appreciations, num_empathy и т.д.
    total_reactions = _int(post.get("num_likes"))
    if total_reactions is None:
        s = (
            (_int(post.get("num_likes")) or 0)
            + (_int(post.get("num_appreciations")) or 0)
            + (_int(post.get("num_empathy")) or 0)
            + (_int(post.get("num_praises")) or 0)
            + (_int(post.get("num_interests")) or 0)
        )
        total_reactions = s if s > 0 else None

    media_present = bool(
        post.get("images")
        or post.get("video")
        or post.get("document")
    )

    return {
        "author_name": post.get("poster_name") or post.get("author_name") or "Unknown",
        "author_profile_url": post.get("poster_linkedin_url") or post.get("author_profile_url") or profile_url,
        "post_url": post.get("post_url") or post_url,
        "published_at": post.get("time") or post.get("posted") or "unknown",
        "text": str(text).strip() if text else "",
        "media_present": media_present,
        "reactions_count": total_reactions,
        "comments_count": _int(post.get("num_comments")),
        "reposts_count": _int(post.get("num_reposts")),
        "views_count": _int(post.get("num_views") or post.get("views_count")),
    }


async def fetch_profile_posts(profile_url: str, limit: int = 5) -> Union[List[dict], dict]:
    """
    Получает последние посты профиля через Get Profile's Posts.
    profile_url — URL профиля LinkedIn (https://www.linkedin.com/in/username).
    Возвращает список dict с полями: title, content, post_url, posted_at, likes_count, comments_count, views_count.
    При ошибке: {"error": "..."}.
    """
    key = settings.rapidapi_key
    host = settings.rapidapi_host or "fresh-linkedin-profile-data.p.rapidapi.com"
    if not key:
        return {"error": "RAPIDAPI_KEY не задан."}

    api_url = f"https://{host}/get-profile-posts"
    params = {"linkedin_url": profile_url.strip(), "type": "posts"}
    headers = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": host}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(api_url, params=params, headers=headers)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPStatusError as e:
        logging.warning("RapidAPI get-profile-posts HTTP error: %s %s", e.response.status_code, e.response.text[:200])
        return {"error": f"RapidAPI: HTTP {e.response.status_code}."}
    except Exception as e:
        logging.exception("RapidAPI get-profile-posts failed: %s", e)
        return {"error": str(e)}

    if body.get("message", "").lower() not in ("ok", "ok."):
        return {"error": body.get("message") or "Ошибка RapidAPI."}

    data_list = body.get("data")
    if not data_list or not isinstance(data_list, list):
        return []

    result = []
    for item in data_list[:limit]:
        text = (item.get("text") or "").strip()
        title = (text[:200] + ("…" if len(text) > 200 else "")) if text else "Пост"
        post_url = (item.get("post_url") or "").strip()
        if not post_url:
            continue

        total_reactions = _int(item.get("num_likes"))
        if total_reactions is None:
            s = (
                (_int(item.get("num_likes")) or 0)
                + (_int(item.get("num_appreciations")) or 0)
                + (_int(item.get("num_empathy")) or 0)
                + (_int(item.get("num_praises")) or 0)
                + (_int(item.get("num_interests")) or 0)
            )
            total_reactions = s if s > 0 else None

        posted_at = _parse_posted_at(item.get("time") or item.get("posted"))

        result.append({
            "title": title[:512],
            "content": text[:4096] if text else None,
            "post_url": post_url,
            "posted_at": posted_at,
            "likes_count": total_reactions,
            "comments_count": _int(item.get("num_comments")),
            "views_count": _int(item.get("num_views") or item.get("views_count")),
        })
    return result
