# agents/comment_pipeline/author_relevance.py — relevance filter for author answers (66)

from __future__ import annotations

from typing import Any, Dict, List, Tuple


_AI_HINTS = {
    "ai",
    "llm",
    "model",
    "models",
    "automation",
    "agent",
    "agents",
    "prompt",
    "prompts",
    "codex",
    "claude",
    "chatgpt",
    "developer-tools",
    "coding",
    "code",
    "software",
}

_LOGISTICS_HINTS = {
    "logistics",
    "freight",
    "broker",
    "carrier",
    "trucking",
    "shipment",
    "supply chain",
    "supply-chain",
    "transport",
}

_MARKETING_HINTS = {
    "marketing",
    "brand",
    "growth",
    "content",
    "audience",
    "community",
    "positioning",
}

_PERSONAL_HINTS = {
    "family",
    "kids",
    "marriage",
    "husband",
    "wife",
    "parent",
    "parenting",
    "relationship",
    "personal",
    "life",
}


def _clip_value(value: Any, max_len: int = 120) -> Any:
    if isinstance(value, str):
        v = value.strip()
        return v if len(v) <= max_len else (v[: max_len - 3] + "...")
    if isinstance(value, list):
        out = []
        for item in value[:4]:
            out.append(_clip_value(item, max_len=60))
        return out
    return value


def _flatten_leaves(data: Any, prefix: str = "") -> List[Tuple[str, Any]]:
    if isinstance(data, dict):
        out: List[Tuple[str, Any]] = []
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_flatten_leaves(value, path))
        return out
    # treat lists/scalars as leaf answers
    return [(prefix, data)]


def _detect_domains(post_text: str, post_brief: Dict[str, Any] | None = None) -> set[str]:
    pb = post_brief or {}
    tags = [str(t).strip().lower() for t in (pb.get("tags") or []) if t]
    joined = " ".join(
        [
            (post_text or "").lower(),
            (pb.get("main_claim") or "").lower(),
            (pb.get("context") or "").lower(),
            (pb.get("topic_summary") or "").lower(),
            " ".join(tags),
        ]
    )
    domains: set[str] = set()
    if any(h in joined for h in _AI_HINTS):
        domains.add("ai")
    if any(h in joined for h in _LOGISTICS_HINTS):
        domains.add("logistics")
    if any(h in joined for h in _MARKETING_HINTS):
        domains.add("marketing")
    if any(h in joined for h in _PERSONAL_HINTS):
        domains.add("personal")
    return domains


def _is_relevant(path: str, domains: set[str]) -> tuple[bool, str]:
    p = (path or "").lower()

    # Always keep style/voice/safety/rules interaction signals.
    for prefix in ("style.", "interaction.", "anti_ai.", "safety.", "rules.", "privacy.", "debate."):
        if p.startswith(prefix):
            return True, "core_voice_or_rules"

    # Usually useful for positioning/context.
    for prefix in ("identity.", "expertise."):
        if p.startswith(prefix):
            return True, "author_positioning"

    if p.startswith("domain.ai."):
        return ("ai" in domains), ("domain_match_ai" if "ai" in domains else "domain_mismatch")
    if p.startswith("domain.logistics."):
        return (
            ("logistics" in domains),
            ("domain_match_logistics" if "logistics" in domains else "domain_mismatch"),
        )
    if p.startswith("domain.marketing."):
        return (
            ("marketing" in domains),
            ("domain_match_marketing" if "marketing" in domains else "domain_mismatch"),
        )

    # Personal/family context should be applied only when relevant to post topic.
    if "family" in p or p.startswith("background."):
        return ("personal" in domains), ("personal_context_match" if "personal" in domains else "not_relevant_now")

    return True, "default_relevant"


def build_author_applicability(
    author_answers_66: Dict[str, Any],
    post_text: str,
    post_brief: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    leaves = _flatten_leaves(author_answers_66 or {})
    domains = _detect_domains(post_text or "", post_brief or {})

    applied_paths: List[str] = []
    skipped_paths: List[str] = []
    applied_examples: List[Dict[str, Any]] = []
    skipped_examples: List[Dict[str, Any]] = []

    for path, value in leaves:
        ok, reason = _is_relevant(path, domains)
        if ok:
            applied_paths.append(path)
            if len(applied_examples) < 25:
                applied_examples.append(
                    {
                        "path": path,
                        "value_preview": _clip_value(value),
                        "reason": reason,
                    }
                )
        else:
            skipped_paths.append(path)
            if len(skipped_examples) < 25:
                skipped_examples.append({"path": path, "reason": reason})

    return {
        "post_domains": sorted(domains),
        "applied_paths": applied_paths,
        "skipped_paths": skipped_paths,
        "applied_examples": applied_examples,
        "skipped_examples": skipped_examples,
    }
