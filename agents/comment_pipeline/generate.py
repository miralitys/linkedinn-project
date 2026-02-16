# agents/comment_pipeline/generate.py — GenerateDrafts

import json
import logging
import re
from typing import Any, Dict, Optional

from app.config import settings
from agents.llm_client import get_llm_client
from agents.utils import extract_json
from agents.comment_pipeline.config import MODE_HARD_AD, MODE_NATIVE_AD, MODE_NETWORK


_LOG = logging.getLogger(__name__)
_VARIANT_LABEL_RE = re.compile(
    r"(?im)^\s*(?:[-*•]\s*|\d+[.)]\s*)?[\"']?(short|medium|long)[\"']?\s*[:=\-]\s*(.*)$"
)
_VARIANT_HEADING_RE = re.compile(
    r"(?im)^\s*(?:[-*•]\s*|\d+[.)]\s*)?[\"']?(short|medium|long)[\"']?\s*$"
)
_V2_PROMPT_VERSIONS = {"v2", "comments_v2", "high_engagement_2026"}
_META_ERROR_RE = re.compile(
    r"(?is)(patch_plan|#\s*post|черновик комментария отсутствует|"
    r"не вижу текста комментария|предоставьте текст комментария|"
    r"i don't see the comment text|provide the comment text|draft is missing)"
)


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


def _resolve_prompt_path(prompt_version: str) -> "Path":
    from pathlib import Path

    version = (prompt_version or "").strip().lower()
    if version in {"v2", "comments_v2", "high_engagement_2026"}:
        v2 = settings.prompts_dir / "comment_pipeline_generate_v2.txt"
        if v2.exists():
            return v2
    return settings.prompts_dir / "comment_pipeline_generate.txt"


def _extract_labeled_variants(text: str) -> Dict[str, str]:
    out = {"short": "", "medium": "", "long": ""}
    src = (text or "").replace("\r\n", "\n")
    matches = list(_VARIANT_LABEL_RE.finditer(src))
    if not matches:
        return out
    for i, m in enumerate(matches):
        key = (m.group(1) or "").strip().lower()
        if key not in out:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(src)
        tail = src[start:end].strip()
        value = ((m.group(2) or "").strip() + (" " + tail if tail else "")).strip()
        value = value.replace("```", " ")
        value = re.sub(r"\s+", " ", value)
        out[key] = value.strip(" \t\r\n\"'")
    return out


def _extract_heading_variants(text: str) -> Dict[str, str]:
    out = {"short": "", "medium": "", "long": ""}
    src = (text or "").replace("\r\n", "\n")
    matches = list(_VARIANT_HEADING_RE.finditer(src))
    if not matches:
        return out
    for i, m in enumerate(matches):
        key = (m.group(1) or "").strip().lower()
        if key not in out:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(src)
        value = src[start:end].strip()
        value = value.replace("```", " ")
        value = re.sub(r"\s+", " ", value)
        out[key] = value.strip(" \t\r\n\"'")
    return out


def _extract_three_blocks(text: str) -> Dict[str, str]:
    out = {"short": "", "medium": "", "long": ""}
    src = (text or "").replace("```", "").strip()
    if not src:
        return out
    blocks = [re.sub(r"\s+", " ", b).strip(" \t\r\n\"'") for b in re.split(r"\n\s*\n+", src) if b.strip()]
    blocks = [b for b in blocks if b and not b.lower().startswith("3 comments")]
    if len(blocks) < 3:
        return out
    out["short"], out["medium"], out["long"] = blocks[0], blocks[1], blocks[2]
    return out


def _is_v2_prompt(prompt_version: str) -> bool:
    return (prompt_version or "").strip().lower() in _V2_PROMPT_VERSIONS


def _contains_meta_error_text(text: str) -> bool:
    return bool(_META_ERROR_RE.search(text or ""))


def _sanitize_result(result: Dict[str, str]) -> Dict[str, str]:
    out = {"short": "", "medium": "", "long": ""}
    for key in out:
        value = (result.get(key) or "").strip()
        if value and not _contains_meta_error_text(value):
            out[key] = value
    return out


def _parse_any_variants(raw: str) -> Dict[str, str]:
    try:
        data = extract_json(raw)
        if isinstance(data, dict):
            return {
                "short": (data.get("short") or "").strip(),
                "medium": (data.get("medium") or "").strip(),
                "long": (data.get("long") or "").strip(),
            }
    except Exception:
        pass
    for extractor in (_extract_labeled_variants, _extract_heading_variants, _extract_three_blocks):
        parsed = extractor(raw)
        if any(parsed.values()):
            return parsed
    return {"short": "", "medium": "", "long": ""}


async def generate_drafts(
    post_text: str,
    post_brief: dict,
    author_directive: dict,
    author_answers_66: Optional[dict],
    author_applicability: dict,
    policy: dict,
    product_plan: Optional[dict],
    mode: str,
    post_language: str,
    author_name: str = "Author",
    author_voice_phrases: Optional[list[str]] = None,
    llm=None,
    strict_mode: bool = False,
    variant_override: Optional[str] = None,
    prompt_version: str = "default",
) -> Dict[str, str]:
    """Генерирует 3 черновика: short, medium, long. strict_mode: короче, больше anchor, меньше прилагательных."""
    path = _resolve_prompt_path(prompt_version)
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

    default_phrases = (
        ["system beats speed", "chaos costs money", "discipline decides"]
        if post_language == "English"
        else ["порядок решает", "хаос стоит денег", "система важнее скорости"]
    )
    phrases = [str(x).strip() for x in (author_voice_phrases or []) if str(x).strip()]
    while len(phrases) < 3:
        phrases.append(default_phrases[len(phrases)])

    user = prompt_tpl.format(
        mode_rules=mode_rules,
        post_text=post_text,
        author_name=(author_name or "Author"),
        phrase1=phrases[0],
        phrase2=phrases[1],
        phrase3=phrases[2],
        post_brief_json=json.dumps(post_brief, ensure_ascii=False),
        author_directive_json=json.dumps(author_directive, ensure_ascii=False),
        author_answers_66_json=json.dumps(author_answers_66 or {}, ensure_ascii=False),
        author_applicability_json=json.dumps(author_applicability or {}, ensure_ascii=False),
        product_plan_section=full_product + strict_note,
    )

    client = llm or get_llm_client()
    response = await client.chat(
        [{"role": "user", "content": user}],
        temperature=0.4 if strict_mode else 0.5,
        max_tokens=2048,
    )

    result = _sanitize_result(_parse_any_variants(response))
    should_retry_v2 = _is_v2_prompt(prompt_version) and (
        not any(result.values()) or any(_contains_meta_error_text(v) for v in (response or "").splitlines())
    )
    if should_retry_v2:
        retry_user = (
            user
            + "\n\nIMPORTANT: return only direct comments, no explanations and no requests for extra input."
            + "\nFormat exactly:"
            + "\nshort: ..."
            + "\nmedium: ..."
            + "\nlong: ..."
        )
        retry_response = await client.chat(
            [{"role": "user", "content": retry_user}],
            temperature=0.2,
            max_tokens=2048,
        )
        retry_result = _sanitize_result(_parse_any_variants(retry_response))
        if any(retry_result.values()):
            result = retry_result

    if any(result.values()):
        if variant_override and variant_override in result:
            return {k: (result[variant_override] if k == variant_override else "") for k in ("short", "medium", "long")}
        return result
    preview = re.sub(r"\s+", " ", str(response or "")).strip()[:500]
    _LOG.warning(
        "generate_drafts: unable to parse LLM response prompt_version=%s strict=%s preview=%r",
        prompt_version,
        strict_mode,
        preview,
    )
    return {"short": "", "medium": "", "long": ""}
