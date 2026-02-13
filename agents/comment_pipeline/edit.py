# agents/comment_pipeline/edit.py — Edit(draft, patch_plan, constraints)

from pathlib import Path
from typing import Any, List

from app.config import settings
from agents.llm_client import get_llm_client


async def edit_draft(
    draft: str,
    patch_plan: List[dict],
    constraints: dict,
    llm=None,
) -> str:
    """Вносит правки по patch_plan. Не переписывает >35%."""
    if not patch_plan:
        return draft
    path = settings.prompts_dir / "comment_pipeline_edit.txt"
    prompt_tpl = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not prompt_tpl:
        return draft

    import json
    user = prompt_tpl.format(
        patch_plan=json.dumps(patch_plan, ensure_ascii=False),
        draft=draft,
        constraints=json.dumps(constraints, ensure_ascii=False),
    )

    client = llm or get_llm_client()
    response = await client.chat(
        [{"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=1024,
    )
    result = (response or "").strip()
    return result if result else draft
