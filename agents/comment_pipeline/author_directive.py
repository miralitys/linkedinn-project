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


def _parse_author_history_profile(author: Optional[dict]) -> dict:
    """
    Extract style.* overrides from setup author history text.
    Expected lines format: 'style.tone_default: ...'
    """
    if not author or not isinstance(author, dict):
        return {}
    history = author.get("history")
    if not history or not isinstance(history, str):
        return {}
    out: dict = {}
    for raw_line in history.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        k = key.strip()
        v = value.strip()
        if not v:
            continue
        if k.startswith("style."):
            out[k[len("style.") :]] = v
        elif k.startswith("anti_ai."):
            out[k] = v
    return out


def compile_author_directive(
    author_answers_66: dict,
    author: Optional[dict] = None,
) -> dict:
    """
    Компилирует fingerprint (66 ответов) в AuthorDirective.
    Устраняет только логические ошибки UI, не меняет характер.
    """
    fp = author_answers_66 or {}
    style_overrides = _parse_author_history_profile(author)

    def _style_value(key: str, default: Any = None) -> Any:
        if key in style_overrides and style_overrides.get(key) not in (None, ""):
            return style_overrides.get(key)
        return _get(fp, f"style.{key}", default)

    # experience_policy
    exp_policy = _style_value("self_reference_policy") or "Да, но только если помогает мысли"
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
    directness = _style_value("directness")
    if directness is None:
        directness = 5
    try:
        directness = int(float(directness))
    except (TypeError, ValueError):
        directness = 5
    directness = max(1, min(10, directness))

    # humor_level: slider 1-10
    humor_level = _style_value("humor_level")
    if humor_level is None:
        humor_level = 4
    try:
        humor_level = int(float(humor_level))
    except (TypeError, ValueError):
        humor_level = 4
    humor_level = max(1, min(10, humor_level))

    # roughness: anti_ai.roughness
    roughness = _get(fp, "anti_ai.roughness")
    if "anti_ai.roughness" in style_overrides:
        roughness = style_overrides.get("anti_ai.roughness")
    if roughness is None:
        roughness = 6
    try:
        roughness = int(float(roughness))
    except (TypeError, ValueError):
        roughness = 6
    roughness = max(1, min(10, roughness))

    voice = {
        "tone_default": _style_value("tone_default") or "neutral",
        "energy": _style_value("energy") or "Спокойно и без напряга",
        "directness": directness,
        "humor_type": _style_value("humor_type") or "Легкий",
        "humor_level": humor_level,
        "sentence_style": _style_value("sentence_style") or "Смешанный",
        "roughness": roughness,
    }

    structure = {
        "opening_pattern": _style_value("opening_pattern") or "Сразу с конкретики из поста",
        "structure_pref": _style_value("structure_pref") or "Якорь из поста → мысль → вопрос",
        "paragraph_pref": _style_value("paragraph_pref") or "1–2",
        "end_question_preference": _style_value("end_question_preference") or "Почти всегда",
    }

    intent = {
        "comment_goal": _get(fp, "interaction.comment_goal") or "Получить ответ автора",
    }

    self_reference = {
        "experience_policy": exp_policy,
        "micro_detail_policy": micro_policy,
        "status_mentions": _style_value("status_mentions") or "Только если напрямую усиливает мысль",
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

    profile_signals = {
        "identity_roles": _ensure_list(_get(fp, "identity.roles")),
        "expertise_topics": _ensure_list(_get(fp, "expertise.topics")),
        "interaction_playbook": {
            "support_style": _get(fp, "interaction.support_style") or "",
            "validation_style": _get(fp, "interaction.validation_style") or "",
            "challenge_style": _get(fp, "interaction.challenge_style") or "",
        },
        "domain_playbook": {
            "logistics_explain_style": _get(fp, "domain.logistics.explain_style") or "",
            "ai_position": _get(fp, "domain.ai.position") or "",
            "ai_theses": _ensure_list(_get(fp, "domain.ai.theses")),
        },
        "debate_playbook": {
            "deescalation": _get(fp, "debate.deescalation") or "",
            "common_topic": _get(fp, "debate.common_topic") or "",
            "argument_style": _get(fp, "debate.argument_style") or "",
        },
        "style_playbook": {
            "empathy_mode": _style_value("empathy_mode") or "",
            "experience_injection": _style_value("experience_injection") or "",
            "what_is_point": _style_value("what_is_point") or "",
            "flex_level": _style_value("flex_level") or "",
            "handling_stupid": _style_value("handling_stupid") or "",
        },
        "mandatory_rules": _ensure_list(_get(fp, "rules.mandatory")),
    }

    result = {
        "voice": voice,
        "structure": structure,
        "intent": intent,
        "self_reference": self_reference,
        "constraints": constraints,
        "profile_signals": profile_signals,
    }

    # Merge author (setup) if provided — name, role, history for context
    if author and isinstance(author, dict):
        result["author_context"] = {
            "full_name": author.get("full_name") or "",
            "role": author.get("role") or "",
            "history": author.get("history") or "",
        }

    return result
