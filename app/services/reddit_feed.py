# app/services/reddit_feed.py
"""Загрузка постов из сабреддита через публичный JSON API Reddit (без OAuth)."""
from datetime import datetime, timezone
from typing import Any, List

import httpx

USER_AGENT = "LFAS/1.0 (MyVOICE's; +https://github.com/myvoice/lfas)"


async def fetch_subreddit_posts(subreddit: str, limit: int = 25, sort: str = "hot") -> List[dict]:
    """
    Загружает посты из r/{subreddit}. Возвращает список dict с полями:
    reddit_id, title, content, post_url, posted_at, author, score, num_comments.
    """
    sub = (subreddit or "").strip().lower().replace("/r/", "").split("/")[0] or "python"
    url = f"https://www.reddit.com/r/{sub}/{sort}.json"
    params = {"limit": min(max(1, limit), 100)}
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
        except httpx.HTTPError as e:
            return []
        data = r.json()
    children = (data.get("data") or {}).get("children") or []
    out: List[dict] = []
    for c in children:
        d = c.get("data") or {}
        reddit_id = d.get("id")
        if not reddit_id:
            continue
        title = (d.get("title") or "").strip() or "(no title)"
        selftext = (d.get("selftext") or "").strip()
        permalink = (d.get("permalink") or "").strip()
        if permalink and not permalink.startswith("http"):
            post_url = "https://www.reddit.com" + (permalink if permalink.startswith("/") else "/" + permalink)
        else:
            post_url = permalink or d.get("url")
        created_utc = d.get("created_utc")
        if created_utc is not None:
            try:
                posted_at = datetime.fromtimestamp(int(created_utc), tz=timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError, OSError):
                posted_at = datetime.utcnow()
        else:
            posted_at = datetime.utcnow()
        out.append({
            "subreddit": sub,
            "reddit_id": reddit_id,
            "title": title[:512],
            "content": selftext[:10000] if selftext else None,
            "post_url": (post_url or "")[:1024],
            "posted_at": posted_at,
            "author": (d.get("author") or "").strip() or None,
            "score": d.get("score") if isinstance(d.get("score"), (int, type(None))) else None,
            "num_comments": d.get("num_comments") if isinstance(d.get("num_comments"), (int, type(None))) else None,
        })
    return out
