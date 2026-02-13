# agents/comment_pipeline/author_directive.py — CompileAuthorDirective(author_answers_66)

import logging
from typing import Any, Dict, Optional

from agents.comment_pipeline.config import TABOO_TOPICS_NORMALIZE

logger = logging.getLogger(__name__)


def _get(fp: dict, path: str, default=None) -> Any:
    """Get nested value: 'style.tone_default' -> fp['style']['tone_default']."""
    cur = fp
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is None:
            return default
    return cur


def _ensure_list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v] if v else []


def _fix_no_restrictions(lst: list, exclusive: str) -> list:
    """Если 'Нет ограничений' и есть другие пункты — удалить 'Нет ограничений'."""
    if not lst or exclusive not in lst:
        return lst
    if len(lst) == 1:
        return lst
    return [x for x in lst if x != exclusive]


def _normalize_taboo_topics(topics: list) -> list:
    """Нормализует опечатки в taboo_topics; неизвестные логирует как unknown."""
    result = []
    for t in topics:
        if not t or not isinstance(t, str):
            continue
        key = t.strip().lower()
        normalized = TABOO_TOPICS_NORMALIZE.get(key)
        if normalized is not None:
            if normalized not in result:
                result.append(normalized)
        else:
            logger.debug("taboo_topics unknown (not in normalize map): %r", t)
            if t not in result:
                result.append(t)
    return result


def compile_author_directive(
    author_answers_66: dict,
    author: Optional[dict] = None,
) -> dict:
    """
    Компилирует fingerprint (66 ответов) в AuthorDirective.
    Устраняет только логические ошибки UI, не меняет характер.
    """
    fp = author_answers_66 or {}

    # experience_policy
    exp_policy = _get(fp, "style.self_reference_policy") or "Да, но только если помогает мысли"
    if exp_policy == "Вообще не упоминать опыт":
        forbidden_personal_patterns = [
            "I did", "in my experience", "founders I know", "I built", "my clients",
            "я сделал", "в моём опыте", "основатели которых я знаю", "я построил", "мои клиенты",
        ]
    else:
        forbidden_personal_patterns = []

    # micro_detail_policy
    micro_policy = _get(fp, "background.micro_detail_policy") or "Редко, если в тему"
    micro_detail_constraint = (
        "max 1 micro-insert <= 8 words, only if directly related to anchor"
        if micro_policy == "Редко, если в тему"
        else ("forbidden" if micro_policy == "Никогда" else "allowed")
    )

    # taboo_topics: safety.taboo_topics + safety.never_topics (с нормализацией опечаток)
    taboo = _ensure_list(_get(fp, "safety.taboo_topics"))
    never = _ensure_list(_get(fp, "safety.never_topics"))
    taboo = _fix_no_restrictions(never, "Нет") + taboo
    taboo = _normalize_taboo_topics(taboo)

    # humor_taboo
    humor_taboo = _ensure_list(_get(fp, "safety.humor_taboo"))
    humor_taboo = _fix_no_restrictions(humor_taboo, "Нет ограничений")

    # banned_phrases
    banned = _ensure_list(_get(fp, "anti_ai.banned_phrases"))
    banned_extra = _ensure_list(_get(fp, "anti_ai.banned_phrases_extra"))
    banned = list(dict.fromkeys(banned + banned_extra))

    # hated_smells
    hated = _ensure_list(_get(fp, "anti_ai.hated_smells"))

    # directness: slider 1-10, default 5
    directness = _get(fp, "style.directness")
    if directness is None:
        directness = 5
    try:
        directness = int(float(directness))
    except (TypeError, ValueError):
        directness = 5
    directness = max(1, min(10, directness))

    # humor_level: slider 1-10
    humor_level = _get(fp, "style.humor_level")
    if humor_level is None:
        humor_level = 4
    try:
        humor_level = int(float(humor_level))
    except (TypeError, ValueError):
        humor_level = 4
    humor_level = max(1, min(10, humor_level))

    # roughness: anti_ai.roughness
    roughness = _get(fp, "anti_ai.roughness")
    if roughness is None:
        roughness = 6
    try:
        roughness = int(float(roughness))
    except (TypeError, ValueError):
        roughness = 6
    roughness = max(1, min(10, roughness))

    voice = {
        "tone_default": _get(fp, "style.tone_default") or "neutral",
        "energy": _get(fp, "style.energy") or "Спокойно и без напряга",
        "directness": directness,
        "humor_type": _get(fp, "style.humor_type") or "Легкий",
        "humor_level": humor_level,
        "sentence_style": _get(fp, "style.sentence_style") or "Смешанный",
        "roughness": roughness,
    }

    structure = {
        "opening_pattern": _get(fp, "style.opening_pattern") or "Сразу с конкретики из поста",
        "structure_pref": _get(fp, "style.structure_pref") or "Якорь из поста → мысль → вопрос",
        "paragraph_pref": _get(fp, "style.paragraph_pref") or "1–2",
        "end_question_preference": _get(fp, "style.end_question_preference") or "Почти всегда",
    }

    intent = {
        "comment_goal": _get(fp, "interaction.comment_goal") or "Получить ответ автора",
    }

    self_reference = {
        "experience_policy": exp_policy,
        "micro_detail_policy": micro_policy,
        "status_mentions": _get(fp, "style.status_mentions") or "Только если напрямую усиливает мысль",
        "forbidden_personal_patterns": forbidden_personal_patterns,
        "micro_detail_constraint": micro_detail_constraint,
    }

    constraints = {
        "taboo_topics": taboo,
        "taboo_style": humor_taboo,
        "banned_phrases": banned,
        "hated_smells": hated,
        "therapy_handling": _get(fp, "safety.therapy_handling") or "Говорю «не моя зона» и возвращаю к практике",
        "toxic_handling": _get(fp, "safety.toxic_handling") or "Спокойно обозначаю неприемлемость",
    }

    result = {
        "voice": voice,
        "structure": structure,
        "intent": intent,
        "self_reference": self_reference,
        "constraints": constraints,
    }

    # Merge author (setup) if provided — name, role, history for context
    if author and isinstance(author, dict):
        result["author_context"] = {
            "full_name": author.get("full_name") or "",
            "role": author.get("role") or "",
            "history": author.get("history") or "",
        }

    return result
