# agents/comment_pipeline/pipeline.py — главный пайплайн

import asyncio
import logging
from typing import Any, Dict, Optional

from agents.comment_pipeline.author_directive import compile_author_directive
from agents.comment_pipeline.author_relevance import build_author_applicability
from agents.comment_pipeline.detectors import sanitize_punctuation, strip_post_rhetoric_reaction
from agents.comment_pipeline.edit import edit_draft
from agents.comment_pipeline.generate import generate_drafts
from agents.comment_pipeline.policy import get_policy
from agents.comment_pipeline.post_brief import build_post_brief
from agents.comment_pipeline.product_plan import select_product_and_plan
from agents.comment_pipeline.review import review_draft
from agents.comment_pipeline.config import GOAL_TO_MODE, MODE_HARD_AD, MODE_NATIVE_AD, MODE_NETWORK

_LOG = logging.getLogger(__name__)

MAX_FIXES = 1
ALL_VARIANTS = ("short", "medium", "long")
DEFAULT_FALLBACK_VARIANTS = {"medium", "long"}


def _final_cleanup(text: str) -> str:
    return strip_post_rhetoric_reaction(sanitize_punctuation(text or ""))


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
    author_applicability: dict,
    policy: dict,
    product_plan: Optional[dict],
    mode: str,
    post_language: str,
    products: list,
    allow_fallback: bool = True,
    llm=None,
) -> str:
    """До 2 фиксов: review -> edit -> review. Если fail — fallback regenerate с stricter constraints."""
    current = draft
    for attempt in range(MAX_FIXES + 1):
        review = await review_draft(
            current,
            variant,
            post_text,
            post_brief,
            author_directive,
            policy,
            product_plan,
            mode,
            products=products,
            expected_language=post_language,
            llm=llm,
        )
        if review.get("pass"):
            return _final_cleanup(current)
        flags = review.get("flags") or []
        patch_plan = review.get("patch_plan") or []
        if not patch_plan and "language_mismatch" in (review.get("flags") or []):
            target_lang = "English" if post_language == "English" else "Russian"
            patch_plan = [
                {
                    "op": "replace",
                    "hint": f"Rewrite the whole comment in {target_lang}, keep meaning and tone.",
                }
            ]
        if not patch_plan and any(f in flags for f in ("anchor_copy_overlap", "post_copy_overlap", "rhetoric_reaction")):
            patch_plan = [
                {
                    "op": "replace",
                    "hint": (
                        "Rewrite from an independent viewpoint. Use the post only as semantic context, "
                        "do not quote or evaluate the post wording or metaphors directly. "
                        "Keep one core idea and end naturally."
                    ),
                }
            ]
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

    if allow_fallback:
        # Fallback: regenerate with stricter constraints
        try:
            fallback_drafts = await generate_drafts(
                post_text,
                post_brief,
                author_directive,
                author_applicability,
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
                    post_text,
                    post_brief,
                    author_directive,
                    policy,
                    product_plan,
                    mode,
                    products=products,
                    expected_language=post_language,
                    llm=llm,
                )
                if review.get("pass"):
                    return _final_cleanup(fallback_text)
                fallback_patch = review.get("patch_plan") or []
                if fallback_patch:
                    edited_fallback = await edit_draft(
                        fallback_text,
                        fallback_patch,
                        author_directive.get("constraints", {}),
                        llm=llm,
                    )
                    review2 = await review_draft(
                        edited_fallback,
                        variant,
                        post_text,
                        post_brief,
                        author_directive,
                        policy,
                        product_plan,
                        mode,
                        products=products,
                        expected_language=post_language,
                        llm=llm,
                    )
                    if review2.get("pass"):
                        return _final_cleanup(edited_fallback)
        except Exception as e:
            _LOG.warning("Fallback regenerate failed for %s: %s", variant, e)
    return _final_cleanup(current)


async def prepare_comment_pipeline(
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

    # 2) Relevance filter for 66 answers and compile directive
    author_applicability = build_author_applicability(
        author_answers_66 or {},
        post_text=post_text,
        post_brief=post_brief,
    )
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
        author_applicability,
        policy,
        product_plan,
        mode,
        post_language,
        llm=llm,
    )

    return {
        "post_text": post_text,
        "post_language": post_language,
        "post_brief": post_brief,
        "author_directive": author_directive,
        "author_applicability": author_applicability,
        "policy": policy,
        "product_plan": product_plan,
        "mode": mode,
        "products": products or [],
        "drafts": drafts or {"short": "", "medium": "", "long": ""},
    }


async def finalize_comment_variants(
    pipeline_ctx: Dict[str, Any],
    *,
    variants: Optional[list[str]] = None,
    review_variants: Optional[set[str]] = None,
    fallback_variants: Optional[set[str]] = None,
    llm=None,
) -> Dict[str, str]:
    selected = [v for v in (variants or list(ALL_VARIANTS)) if v in ALL_VARIANTS]
    reviewed = review_variants if review_variants is not None else {"medium", "long"}
    fallback_for = fallback_variants if fallback_variants is not None else DEFAULT_FALLBACK_VARIANTS
    drafts = pipeline_ctx.get("drafts") or {}

    async def _finalize_one(variant: str) -> str:
        text = (drafts.get(variant) or "").strip()
        if not text:
            return ""
        if variant not in reviewed:
            return _final_cleanup(text)
        return await _self_review_fix_loop(
            text,
            variant,
            pipeline_ctx.get("post_text", ""),
            pipeline_ctx.get("post_brief") or {},
            pipeline_ctx.get("author_directive") or {},
            pipeline_ctx.get("author_applicability") or {},
            pipeline_ctx.get("policy") or {},
            pipeline_ctx.get("product_plan"),
            pipeline_ctx.get("mode", MODE_NETWORK),
            pipeline_ctx.get("post_language", "English"),
            pipeline_ctx.get("products") or [],
            allow_fallback=variant in fallback_for,
            llm=llm,
        )

    tasks: dict[str, asyncio.Task[str]] = {
        variant: asyncio.create_task(_finalize_one(variant)) for variant in selected
    }
    results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)
    finals: Dict[str, str] = {k: "" for k in ALL_VARIANTS}

    for variant, result in zip(tasks.keys(), results_list):
        if isinstance(result, Exception):
            _LOG.warning("Finalize failed for %s: %s", variant, result)
            finals[variant] = sanitize_punctuation((drafts.get(variant) or "").strip())
        else:
            finals[variant] = result or ""
    return finals


async def run_comment_pipeline(
    post_text: str,
    author_answers_66: dict,
    products: list,
    mode: str,
    author: Optional[dict] = None,
    llm=None,
) -> Dict[str, Any]:
    pipeline_ctx = await prepare_comment_pipeline(
        post_text=post_text,
        author_answers_66=author_answers_66,
        products=products,
        mode=mode,
        author=author,
        llm=llm,
    )
    finals = await finalize_comment_variants(
        pipeline_ctx,
        variants=list(ALL_VARIANTS),
        review_variants={"medium", "long"},
        fallback_variants=DEFAULT_FALLBACK_VARIANTS,
        llm=llm,
    )
    return finals
