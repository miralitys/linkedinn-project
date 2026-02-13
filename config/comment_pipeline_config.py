# config/comment_pipeline_config.py — политики и пороги для comment pipeline

MODE_NETWORK = "network"
MODE_NATIVE_AD = "native_ad"
MODE_HARD_AD = "hard_ad"

GOAL_TO_MODE = {
    "network": MODE_NETWORK,
    "native_ads": MODE_NATIVE_AD,
    "native_ad": MODE_NATIVE_AD,
    "full_ads": MODE_HARD_AD,
    "hard_ad": MODE_HARD_AD,
}

# CommentPolicy по режиму
POLICIES = {
    MODE_NETWORK: {
        "product_inclusion": "NONE",
        "product_required": False,
        "max_product_mentions": 0,
        "cta_allowed": False,
        "cta_required": False,
        "link_allowed": False,
        "salesiness_max": 10,
        "allowed_claims_limit": 0,
    },
    MODE_NATIVE_AD: {
        "product_inclusion": "SOFT_MATCH",
        "product_required": False,
        "max_product_mentions": 1,
        "cta_allowed": False,
        "cta_required": False,
        "link_allowed": False,
        "min_match_score_for_product": 70,
        "salesiness_max": 25,
        "allowed_claims_limit": 1,
    },
    MODE_HARD_AD: {
        "product_inclusion": "DIRECT",
        "product_required": True,
        "max_product_mentions": 2,
        "cta_allowed": True,
        "cta_required": True,
        "link_allowed": "depends_on_product",
        "salesiness_max": 60,
        "allowed_claims_limit": 2,
    },
}

# Пороги для Review по варианту длины
REVIEW_THRESHOLDS = {
    "short": {
        "ai_smell": 25,
        "post_anchor": 80,
        "clarity": 80,
        "integrity": 95,
        "persona_fit": 70,
    },
    "medium": {
        "ai_smell": 35,
        "post_anchor": 65,
        "clarity": 72,
        "integrity": 95,
        "persona_fit": 70,
    },
    "long": {
        "ai_smell": 40,
        "post_anchor": 60,
        "clarity": 66,
        "integrity": 95,
        "persona_fit": 68,
    },
}

# Целевые длины (символы)
TARGET_LENGTHS = {
    "short": (180, 260),
    "medium": (300, 600),
    "long": (700, 1200),
}
