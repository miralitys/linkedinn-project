# agents/comment_pipeline/product_plan.py — SelectProductAndPlan

from typing import Any, Dict, List, Optional

from agents.comment_pipeline.config import HARD_AD_CTA_FALLBACK, MODE_HARD_AD, MODE_NATIVE_AD


def _tag_overlap_score(post_tags: List[str], product_tags: List[str], product_icp: List[str]) -> int:
    """Эвристика: overlap тегов поста и продукта. 0-100."""
    if not product_tags and not product_icp:
        return 50  # neutral
    post_set = {t.lower().strip() for t in (post_tags or []) if t}
    prod_set = {t.lower().strip() for t in (product_tags or []) + (product_icp or []) if t}
    if not prod_set:
        return 50
    overlap = len(post_set & prod_set)
    total = len(prod_set)
    return min(100, int(100 * (overlap / total if total else 0) + 20 * overlap))


def select_product_and_plan(
    post_brief: dict,
    products: List[dict],
    author_directive: dict,
    policy: dict,
    mode: str,
    selected_product_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Выбирает продукт и формирует ProductPlan.
    - native_ad: только если match_score >= min_match_score_for_product
    - hard_ad: продукт обязателен (selected или first)
    """
    if not products or mode == "network":
        return None

    min_score = policy.get("min_match_score_for_product", 0)
    allowed_limit = policy.get("allowed_claims_limit", 0)

    post_tags = post_brief.get("tags") or []
    best_product = None
    best_score = 0

    for i, p in enumerate(products):
        if not isinstance(p, dict):
            continue
        pid = str(p.get("name", "") or i)
        if selected_product_id and pid != selected_product_id and str(i) != selected_product_id:
            continue
        tags = p.get("tags") or []
        icp = p.get("icp_tags") or []
        score = _tag_overlap_score(post_tags, tags, icp)
        if mode == MODE_NATIVE_AD and score < min_score:
            continue
        if score >= best_score or (mode == MODE_HARD_AD and not best_product):
            best_score = score
            best_product = p

    if mode == MODE_NATIVE_AD and (not best_product or best_score < min_score):
        return None

    if mode == MODE_HARD_AD and not best_product and products:
        best_product = products[0] if isinstance(products[0], dict) else None
        if best_product:
            best_score = _tag_overlap_score(
                post_tags,
                best_product.get("tags") or [],
                best_product.get("icp_tags") or [],
            )

    if not best_product:
        return None

    allowed = best_product.get("allowed_claims") or []
    chosen = allowed[:allowed_limit] if allowed_limit else []
    forbidden = best_product.get("forbidden_claims") or []
    cta_templates = best_product.get("cta_templates") or []
    cta_template = cta_templates[0] if cta_templates else HARD_AD_CTA_FALLBACK

    return {
        "selected_product_id": str(best_product.get("name", "")),
        "selected_product": best_product,
        "match_score": best_score,
        "angle": "",  # можно добавить LLM для angle
        "mention_style": "SOFT" if mode == MODE_NATIVE_AD else "DIRECT",
        "chosen_claims": chosen,
        "forbidden_claims": forbidden,
        "cta_template": cta_template,
        "link": best_product.get("link") or "",
    }
