# agents/comment_pipeline/generate.py — GenerateDrafts

import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import settings
from agents.llm_client import get_llm_client
from agents.utils import extract_json
from agents.comment_pipeline.config import MODE_HARD_AD, MODE_NATIVE_AD, MODE_NETWORK


def _mode_rules(mode: str, product_plan: Optional[dict]) -> str:
    if mode == MODE_NETWORK:
        return "NETWORK: Никаких продуктов, CTA, ссылок."
    if mode == MODE_NATIVE_AD:
        if not product_plan:
            return "NATIVE (без продукта): вести себя как NETWORK."
        return "NATIVE: 1 короткая вставка про продукт (как пример/инструмент), без CTA, без ссылок, без продажного тона."
    if mode == MODE_HARD_AD and product_plan:
        return (
            "HARD_AD: Продукт обязателен. CTA обязателен (1 строка) по шаблону. "
            "Ссылка только если разрешено. Claims только из chosen_claims."
        )
    return ""


def _product_plan_section(product_plan: Optional[dict], mode: str) -> str:
    if not product_plan or mode == MODE_NETWORK:
        return ""
    p = product_plan.get("selected_product") or {}
    lines = [
        f"Продукт: {p.get('name', '')}",
        f"One-liner: {p.get('one_liner', '') or p.get('description', '')}",
        f"Можно утверждать: {', '.join(product_plan.get('chosen_claims') or [])}",
        f"Нельзя: {', '.join(product_plan.get('forbidden_claims') or [])}",
    ]
    if mode == MODE_HARD_AD and product_plan.get("cta_template"):
        lines.append(f"CTA шаблон: {product_plan['cta_template']}")
    return "Product plan:\n" + "\n".join(lines)


async def generate_drafts(
    post_text: str,
    post_brief: dict,
    author_directive: dict,
    policy: dict,
    product_plan: Optional[dict],
    mode: str,
    post_language: str,
    llm=None,
    strict_mode: bool = False,
    variant_override: Optional[str] = None,
) -> Dict[str, str]:
    """Генерирует 3 черновика: short, medium, long. strict_mode: короче, больше anchor, меньше прилагательных."""
    path = settings.prompts_dir / "comment_pipeline_generate.txt"
    prompt_tpl = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not prompt_tpl:
        return {"short": "", "medium": "", "long": ""}

    mode_rules = _mode_rules(mode, product_plan)
    product_section = _product_plan_section(product_plan, mode)

    lang_rule = (
        "Язык вывода: "
        + ("Русский. Все 3 комментария ТОЛЬКО на русском." if post_language == "Russian" else "English. All 3 comments ONLY in English.")
    )
    full_product = product_section + "\n\n" + lang_rule if product_section else lang_rule

    strict_note = ""
    if strict_mode:
        strict_note = "\n\nFALLBACK REGENERATE (строже): Короче. Больше anchor из поста. Меньше прилагательных. Одна мысль."

    user = prompt_tpl.format(
        mode_rules=mode_rules,
        post_text=post_text,
        post_brief_json=json.dumps(post_brief, ensure_ascii=False),
        author_directive_json=json.dumps(author_directive, ensure_ascii=False),
        product_plan_section=full_product + strict_note,
    )

    client = llm or get_llm_client()
    response = await client.chat(
        [{"role": "user", "content": user}],
        temperature=0.4 if strict_mode else 0.5,
        max_tokens=2048,
    )

    try:
        data = extract_json(response)
        if isinstance(data, dict):
            result = {
                "short": (data.get("short") or "").strip(),
                "medium": (data.get("medium") or "").strip(),
                "long": (data.get("long") or "").strip(),
            }
            if variant_override and variant_override in result:
                return {k: (result[variant_override] if k == variant_override else "") for k in ("short", "medium", "long")}
            return result
    except Exception:
        pass
    return {"short": "", "medium": "", "long": ""}
