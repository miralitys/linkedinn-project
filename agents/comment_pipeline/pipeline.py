# agents/comment_pipeline/pipeline.py — главный пайплайн

import logging
from typing import Any, Dict, Optional

from agents.comment_pipeline.author_directive import compile_author_directive
from agents.comment_pipeline.detectors import sanitize_punctuation
from agents.comment_pipeline.edit import edit_draft
from agents.comment_pipeline.generate import generate_drafts
from agents.comment_pipeline.policy import get_policy
from agents.comment_pipeline.post_brief import build_post_brief
from agents.comment_pipeline.product_plan import select_product_and_plan
from agents.comment_pipeline.review import review_draft
from agents.comment_pipeline.config import GOAL_TO_MODE, MODE_HARD_AD, MODE_NATIVE_AD, MODE_NETWORK

_LOG = logging.getLogger(__name__)

MAX_FIXES = 2


def _detect_language(post_text: str) -> str:
    cyrillic = sum(1 for c in post_text if "\u0400" <= c <= "\u04FF")
    latin = sum(1 for c in post_text if "a" <= c.lower() <= "z")
    return "Russian" if cyrillic > latin else "English"


async def _self_review_fix_loop(
    draft: str,
    variant: str,
    post_text: str,
    post_brief: dict,
    author_directive: dict,
    policy: dict,
    product_plan: Optional[dict],
    mode: str,
    post_language: str,
    products: list,
    llm=None,
) -> str:
    """До 2 фиксов: review -> edit -> review. Если fail — fallback regenerate с stricter constraints."""
    current = draft
    for attempt in range(MAX_FIXES + 1):
        review = await review_draft(
            current,
            variant,
            post_brief,
            author_directive,
            policy,
            product_plan,
            mode,
            products=products,
            llm=llm,
        )
        if review.get("pass"):
            return sanitize_punctuation(current)
        patch_plan = review.get("patch_plan") or []
        if not patch_plan:
            if attempt < MAX_FIXES:
                continue
            break
        if attempt < MAX_FIXES:
            current = await edit_draft(
                current,
                patch_plan,
                author_directive.get("constraints", {}),
                llm=llm,
            )

    # Fallback: regenerate with stricter constraints
    try:
        fallback_drafts = await generate_drafts(
            post_text,
            post_brief,
            author_directive,
            policy,
            product_plan,
            mode,
            post_language,
            llm=llm,
            strict_mode=True,
            variant_override=variant,
        )
        fallback_text = fallback_drafts.get(variant, "").strip()
        if fallback_text:
            review = await review_draft(
                fallback_text,
                variant,
                post_brief,
                author_directive,
                policy,
                product_plan,
                mode,
                products=products,
                llm=llm,
            )
            if review.get("pass"):
                return sanitize_punctuation(fallback_text)
            return sanitize_punctuation(fallback_text)  # use fallback even if review fails
    except Exception as e:
        _LOG.warning("Fallback regenerate failed for %s: %s", variant, e)
    return sanitize_punctuation(current)


async def run_comment_pipeline(
    post_text: str,
    author_answers_66: dict,
    products: list,
    mode: str,
    author: Optional[dict] = None,
    llm=None,
) -> Dict[str, Any]:
    """
    Полный пайплайн: post_brief -> author_directive -> policy -> product_plan -> generate -> review_fix.
    Возвращает { short, medium, long }.
    """
    if not post_text or not post_text.strip():
        return {"short": "", "medium": "", "long": ""}

    mode = GOAL_TO_MODE.get(mode, mode)
    if mode not in (MODE_NETWORK, MODE_NATIVE_AD, MODE_HARD_AD):
        mode = MODE_NETWORK

    post_language = _detect_language(post_text)

    # 1) BuildPostBrief
    post_brief = await build_post_brief(post_text, llm=llm)

    # 2) CompileAuthorDirective
    author_directive = compile_author_directive(author_answers_66 or {}, author=author)

    # 3) GetPolicy
    policy = get_policy(mode)

    # 4) ProductPlan
    product_plan = None
    if mode != MODE_NETWORK and products:
        product_plan = select_product_and_plan(
            post_brief,
            products,
            author_directive,
            policy,
            mode,
        )
        if mode == MODE_HARD_AD and not product_plan and products:
            # Fallback: use first product
            product_plan = select_product_and_plan(
                post_brief,
                products,
                author_directive,
                policy,
                mode,
                selected_product_id=str(products[0].get("name", "")),
            )

    # 5) GenerateDrafts
    drafts = await generate_drafts(
        post_text,
        post_brief,
        author_directive,
        policy,
        product_plan,
        mode,
        post_language,
        llm=llm,
    )

    # 6) SelfReviewFixLoop for each
    finals = {}
    for variant, text in drafts.items():
        if not text:
            finals[variant] = ""
            continue
        finals[variant] = await _self_review_fix_loop(
            text,
            variant,
            post_text,
            post_brief,
            author_directive,
            policy,
            product_plan,
            mode,
            post_language,
            products or [],
            llm=llm,
        )

    return finals
