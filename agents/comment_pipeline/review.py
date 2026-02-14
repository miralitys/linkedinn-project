# agents/comment_pipeline/review.py — Review(draft)

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from agents.comment_pipeline.detectors import (
    count_product_mentions,
    detect_anchor_copy_overlap,
    detect_cta,
    detect_forbidden_claim_violation,
    detect_language_mismatch,
    detect_personal_stance,
    detect_post_copy_overlap,
    detect_post_rhetoric_reaction,
    detect_product_mention_any,
    has_colon,
    has_em_dash,
    has_links,
    product_mentioned_in_draft,
)
from agents.llm_client import get_llm_client
from agents.utils import extract_json
from agents.comment_pipeline.config import (
    MODE_HARD_AD,
    MODE_NATIVE_AD,
    MODE_NETWORK,
    REVIEW_THRESHOLDS,
)


def rule_compliance_check(
    draft: str,
    policy: dict,
    product_plan: Optional[dict],
    products: List[dict],
    mode: str,
    expected_language: Optional[str] = None,
    post_text: Optional[str] = None,
    anchors: Optional[List[str]] = None,
) -> List[str]:
    """
    Rule-based compliance check. Returns list of fail flags.
    Используется и в review_draft, и в _quick_review.
    """
    flags: List[str] = []
    draft = draft or ""

    # Punctuation policy: no em dash, no colon.
    if has_em_dash(draft):
        flags.append("em_dash")
    if has_colon(draft):
        flags.append("colon")
    if detect_language_mismatch(draft, expected_language):
        flags.append("language_mismatch")
    if expected_language and not detect_personal_stance(draft, expected_language):
        flags.append("no_personal_stance")
    if detect_post_copy_overlap(draft, post_text or ""):
        flags.append("post_copy_overlap")
    if detect_anchor_copy_overlap(draft, anchors or []):
        flags.append("anchor_copy_overlap")
    if detect_post_rhetoric_reaction(draft):
        flags.append("rhetoric_reaction")

    if mode == MODE_NETWORK:
        if detect_cta(draft):
            flags.append("cta")
        if has_links(draft):
            flags.append("link")
        if detect_product_mention_any(draft, products or []):
            flags.append("product_mention")

    elif mode == MODE_NATIVE_AD:
        if detect_cta(draft):
            flags.append("cta")
        if has_links(draft):
            flags.append("link")
        max_mentions = policy.get("max_product_mentions", 1)
        if count_product_mentions(draft, product_plan) > max_mentions:
            flags.append("product_mentions")

    elif mode == MODE_HARD_AD:
        if policy.get("product_required") and product_plan:
            if not product_mentioned_in_draft(draft, product_plan):
                flags.append("product_missing")
        if policy.get("cta_required") and not detect_cta(draft):
            flags.append("cta_missing")
        if product_plan and detect_forbidden_claim_violation(
            draft, product_plan.get("forbidden_claims") or []
        ):
            flags.append("forbidden_claim_violation")

    return flags


def _policy_fail_rules(mode: str, product_plan: Optional[dict]) -> str:
    if mode == MODE_NETWORK:
        return "- Network: product_mention, cta, link -> fail"
    if mode == MODE_NATIVE_AD:
        return "- Native: link, cta -> fail; product_mentions > 1 -> fail; salesiness > policy.salesiness_max -> fail"
    if mode == MODE_HARD_AD:
        return "- Hard: product_missing, cta_missing -> fail; forbidden_claim_violation -> fail; salesiness > policy.salesiness_max -> fail"
    return ""


async def review_draft(
    draft: str,
    variant: str,
    post_text: str,
    post_brief: dict,
    author_directive: dict,
    policy: dict,
    product_plan: Optional[dict],
    mode: str,
    products: Optional[List[dict]] = None,
    expected_language: Optional[str] = None,
    llm=None,
) -> Dict[str, Any]:
    """Возвращает Review JSON: pass, scores, flags, patch_plan."""
    products = products or []
    rule_flags = rule_compliance_check(
        draft,
        policy,
        product_plan,
        products,
        mode,
        expected_language=expected_language,
        post_text=post_text,
        anchors=post_brief.get("anchors") if isinstance(post_brief, dict) else [],
    )

    thresholds = REVIEW_THRESHOLDS.get(variant, REVIEW_THRESHOLDS["medium"])
    th_str = ", ".join(f"{k}<={v}" if "max" in k or "smell" in k else f"{k}>={v}" for k, v in thresholds.items())

    path = settings.prompts_dir / "comment_pipeline_review.txt"
    prompt_tpl = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not prompt_tpl:
        return _quick_review(
            draft,
            variant,
            policy,
            product_plan,
            products,
            mode,
            expected_language=expected_language,
            post_text=post_text,
            anchors=post_brief.get("anchors") if isinstance(post_brief, dict) else [],
        )

    user = prompt_tpl.format(
        variant=variant,
        thresholds=th_str,
        policy_fail_rules=_policy_fail_rules(mode, product_plan),
        draft=draft,
        anchors=json.dumps(post_brief.get("anchors", []), ensure_ascii=False),
        constraints=json.dumps(author_directive.get("constraints", {}), ensure_ascii=False),
        product_plan_section=json.dumps(product_plan, ensure_ascii=False) if product_plan else "{}",
    )

    client = llm or get_llm_client()
    response = await client.chat(
        [{"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=512,
    )

    try:
        data = extract_json(response)
        if isinstance(data, dict):
            flags = list(dict.fromkeys((data.get("flags") or []) + rule_flags))
            fail_flags = {"fake_personal_claim", "lecture_mode", "toxicity", "em_dash", "colon", "language_mismatch"}
            fail_flags |= {"no_personal_stance", "post_copy_overlap", "anchor_copy_overlap", "rhetoric_reaction"}
            if mode == MODE_NETWORK:
                fail_flags |= {"product_mention", "cta", "link"}
            if mode == MODE_NATIVE_AD:
                fail_flags |= {"link", "cta", "product_mentions"}
            if mode == MODE_HARD_AD:
                fail_flags |= {"forbidden_claim_violation", "product_missing", "cta_missing"}

            has_fail = any(f in flags for f in fail_flags)
            data["pass"] = not has_fail and data.get("pass", True)
            data["flags"] = flags
            return data
    except Exception:
        pass
    return _quick_review(
        draft,
        variant,
        policy,
        product_plan,
        products,
        mode,
        expected_language=expected_language,
        post_text=post_text,
        anchors=post_brief.get("anchors") if isinstance(post_brief, dict) else [],
    )


def _quick_review(
    draft: str,
    variant: str,
    policy: dict,
    product_plan: Optional[dict],
    products: List[dict],
    mode: str,
    expected_language: Optional[str] = None,
    post_text: Optional[str] = None,
    anchors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Rule-based fallback review (без LLM)."""
    flags: List[str] = []
    if not draft or len(draft.strip()) < 50:
        flags.append("too_short")
    flags.extend(
        rule_compliance_check(
            draft,
            policy,
            product_plan,
            products or [],
            mode,
            expected_language=expected_language,
            post_text=post_text,
            anchors=anchors,
        )
    )
    patch_plan = []
    if "language_mismatch" in flags:
        target_lang = "English" if (expected_language or "").strip().lower() == "english" else "Russian"
        patch_plan.append(
            {
                "op": "replace",
                "hint": f"Rewrite the comment fully in {target_lang}, keep the same meaning and tone.",
            }
        )
    return {
        "pass": len(flags) == 0,
        "scores": {"persona_fit": 70, "ai_smell": 20, "post_anchor": 70, "clarity": 75, "integrity": 95, "salesiness": 10},
        "flags": flags,
        "patch_plan": patch_plan,
    }
