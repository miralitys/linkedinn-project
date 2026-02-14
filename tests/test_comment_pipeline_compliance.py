"""Unit tests for rule_compliance_check — без LLM."""

import pytest

from agents.comment_pipeline.author_directive import compile_author_directive
from agents.comment_pipeline.config import MODE_HARD_AD, MODE_NATIVE_AD, MODE_NETWORK, POLICIES
from agents.comment_pipeline.detectors import detect_language_mismatch
from agents.comment_pipeline.review import _quick_review, rule_compliance_check


def test_rule_compliance_network_cta():
    policy = POLICIES[MODE_NETWORK]
    flags = rule_compliance_check(
        "Great post! DM me for more info.",
        policy,
        None,
        [],
        MODE_NETWORK,
    )
    assert "cta" in flags


def test_rule_compliance_network_link():
    policy = POLICIES[MODE_NETWORK]
    flags = rule_compliance_check(
        "Check out https://example.com for details.",
        policy,
        None,
        [],
        MODE_NETWORK,
    )
    assert "link" in flags


def test_rule_compliance_network_product_mention():
    policy = POLICIES[MODE_NETWORK]
    products = [{"name": "MyProduct", "aliases": ["MP"]}]
    flags = rule_compliance_check(
        "MyProduct is great for this use case.",
        policy,
        None,
        products,
        MODE_NETWORK,
    )
    assert "product_mention" in flags


def test_rule_compliance_network_product_mention_via_alias():
    policy = POLICIES[MODE_NETWORK]
    products = [{"name": "MyProduct", "aliases": ["MP"]}]
    flags = rule_compliance_check(
        "MP helps with this.",
        policy,
        None,
        products,
        MODE_NETWORK,
    )
    assert "product_mention" in flags


def test_rule_compliance_network_clean():
    policy = POLICIES[MODE_NETWORK]
    flags = rule_compliance_check(
        "Interesting perspective. I agree with the main point about scaling.",
        policy,
        None,
        [],
        MODE_NETWORK,
    )
    assert flags == []


def test_rule_compliance_native_cta():
    policy = POLICIES[MODE_NATIVE_AD]
    product_plan = {"selected_product": {"name": "ToolX"}, "forbidden_claims": []}
    flags = rule_compliance_check(
        "ToolX is useful here. Book a call to learn more.",
        policy,
        product_plan,
        [],
        MODE_NATIVE_AD,
    )
    assert "cta" in flags


def test_rule_compliance_native_product_mentions_exceed():
    policy = POLICIES[MODE_NATIVE_AD]
    product_plan = {"selected_product": {"name": "ToolX"}, "forbidden_claims": []}
    flags = rule_compliance_check(
        "ToolX helps with this. I use ToolX daily.",
        policy,
        product_plan,
        [],
        MODE_NATIVE_AD,
    )
    assert "product_mentions" in flags


def test_rule_compliance_native_single_mention_ok():
    policy = POLICIES[MODE_NATIVE_AD]
    product_plan = {"selected_product": {"name": "ToolX"}, "forbidden_claims": []}
    flags = rule_compliance_check(
        "ToolX helps with this use case.",
        policy,
        product_plan,
        [],
        MODE_NATIVE_AD,
    )
    assert "product_mentions" not in flags


def test_rule_compliance_hard_product_missing():
    policy = POLICIES[MODE_HARD_AD]
    product_plan = {
        "selected_product": {"name": "MyApp", "aliases": ["MA"]},
        "forbidden_claims": ["guaranteed results"],
    }
    flags = rule_compliance_check(
        "Great solution for your problem. DM me.",
        policy,
        product_plan,
        [],
        MODE_HARD_AD,
    )
    assert "product_missing" in flags
    assert "cta_missing" not in flags


def test_rule_compliance_hard_product_via_alias():
    policy = POLICIES[MODE_HARD_AD]
    product_plan = {
        "selected_product": {"name": "MyApp", "aliases": ["MA", "My Application"]},
        "forbidden_claims": [],
    }
    flags = rule_compliance_check(
        "MA is perfect for this. DM me for a demo.",
        policy,
        product_plan,
        [],
        MODE_HARD_AD,
    )
    assert "product_missing" not in flags


def test_rule_compliance_hard_cta_missing():
    policy = POLICIES[MODE_HARD_AD]
    product_plan = {
        "selected_product": {"name": "MyApp"},
        "forbidden_claims": [],
    }
    flags = rule_compliance_check(
        "MyApp solves this problem. No CTA here.",
        policy,
        product_plan,
        [],
        MODE_HARD_AD,
    )
    assert "cta_missing" in flags


def test_rule_compliance_hard_forbidden_claim():
    policy = POLICIES[MODE_HARD_AD]
    product_plan = {
        "selected_product": {"name": "MyApp"},
        "forbidden_claims": ["guaranteed results", "100% success"],
    }
    flags = rule_compliance_check(
        "MyApp gives you guaranteed results. DM me.",
        policy,
        product_plan,
        [],
        MODE_HARD_AD,
    )
    assert "forbidden_claim_violation" in flags


def test_rule_compliance_hard_clean():
    policy = POLICIES[MODE_HARD_AD]
    product_plan = {
        "selected_product": {"name": "MyApp"},
        "forbidden_claims": ["guaranteed results"],
    }
    flags = rule_compliance_check(
        "MyApp helps with this workflow. DM me to discuss.",
        policy,
        product_plan,
        [],
        MODE_HARD_AD,
    )
    assert "product_missing" not in flags
    assert "cta_missing" not in flags
    assert "forbidden_claim_violation" not in flags


def test_quick_review_uses_rule_compliance():
    """_quick_review вызывает rule_compliance_check и не требует LLM."""
    result = _quick_review(
        "DM me for more.",
        "short",
        POLICIES[MODE_NETWORK],
        None,
        [],
        MODE_NETWORK,
    )
    assert result["pass"] is False
    assert "cta" in result["flags"]


def test_quick_review_too_short():
    result = _quick_review(
        "Short.",
        "short",
        POLICIES[MODE_NETWORK],
        None,
        [],
        MODE_NETWORK,
    )
    assert result["pass"] is False
    assert "too_short" in result["flags"]


def test_quick_review_pass():
    result = _quick_review(
        "Interesting take on scaling. I've seen similar challenges in practice.",
        "short",
        POLICIES[MODE_NETWORK],
        None,
        [],
        MODE_NETWORK,
    )
    assert result["pass"] is True
    assert result["flags"] == []


def test_rule_compliance_em_dash():
    """Em dash (—) и двоеточие (:) дают fail."""
    policy = POLICIES[MODE_NETWORK]
    flags = rule_compliance_check(
        "Interesting point — I agree.",
        policy,
        None,
        [],
        MODE_NETWORK,
    )
    assert "em_dash" in flags


def test_rule_compliance_colon():
    policy = POLICIES[MODE_NETWORK]
    flags = rule_compliance_check(
        "Main idea: we need to scale.",
        policy,
        None,
        [],
        MODE_NETWORK,
    )
    assert "colon" in flags


def test_detect_language_mismatch_for_english():
    text_ru = "Это короткий комментарий на русском языке, в котором почти нет английских слов."
    assert detect_language_mismatch(text_ru, "English") is True


def test_detect_language_mismatch_for_russian():
    text_en = "This is an English comment and it should fail when Russian output is expected."
    assert detect_language_mismatch(text_en, "Russian") is True


def test_rule_compliance_language_mismatch_flag():
    policy = POLICIES[MODE_NETWORK]
    flags = rule_compliance_check(
        "Это русский комментарий, хотя пост на английском и ответ должен быть только на английском.",
        policy,
        None,
        [],
        MODE_NETWORK,
        expected_language="English",
    )
    assert "language_mismatch" in flags


def test_quick_review_language_mismatch_has_patch_plan():
    result = _quick_review(
        "Это русский комментарий для английского поста, что не должно проходить.",
        "short",
        POLICIES[MODE_NETWORK],
        None,
        [],
        MODE_NETWORK,
        expected_language="English",
    )
    assert result["pass"] is False
    assert "language_mismatch" in result["flags"]
    assert isinstance(result["patch_plan"], list) and len(result["patch_plan"]) > 0


def test_sanitize_punctuation():
    from agents.comment_pipeline.detectors import sanitize_punctuation

    assert "—" not in sanitize_punctuation("Test — value")
    assert ":" not in sanitize_punctuation("Point: something")
    assert "https://x.com" in sanitize_punctuation("See https://x.com for details")


def test_taboo_topics_normalize_typo():
    """Опечатка 'Полигия' нормализуется в 'Политика'."""
    fp = {"safety": {"taboo_topics": ["Полигия"], "never_topics": []}}
    result = compile_author_directive(fp)
    taboo = result["constraints"]["taboo_topics"]
    assert "Политика" in taboo
    assert "Полигия" not in taboo
