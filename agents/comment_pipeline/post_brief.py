# agents/comment_pipeline/post_brief.py — BuildPostBrief(post_text)

import json
from pathlib import Path
from typing import Any

from app.config import settings
from agents.llm_client import get_llm_client
from agents.utils import extract_json


async def build_post_brief(post_text: str, llm=None) -> dict:
    """Возвращает PostBrief JSON."""
    if not post_text or not post_text.strip():
        return {
            "main_claim": "",
            "anchors": [],
            "tone": "neutral",
            "tags": [],
        }
    path = settings.prompts_dir / "comment_pipeline_post_brief.txt"
    prompt = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not prompt:
        # Fallback minimal
        return {
            "main_claim": post_text[:200] if len(post_text) > 200 else post_text,
            "anchors": [],
            "tone": "neutral",
            "tags": [],
        }
    user = prompt.format(post_text=post_text.strip())
    client = llm or get_llm_client()
    response = await client.chat(
        [{"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=512,
    )
    try:
        data = extract_json(response)
        if isinstance(data, dict):
            return {
                "main_claim": data.get("main_claim", "") or "",
                "anchors": data.get("anchors") or [],
                "tone": data.get("tone", "neutral") or "neutral",
                "tags": data.get("tags") or [],
            }
    except Exception:
        pass
    return {
        "main_claim": post_text[:200] if len(post_text) > 200 else post_text,
        "anchors": [],
        "tone": "neutral",
        "tags": [],
    }
