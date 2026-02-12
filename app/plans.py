# app/plans.py — тарифы и лимиты
"""Конфигурация планов: лимиты и доступ к фичам."""
from typing import Any, Optional

PLANS: dict[str, dict[str, Any]] = {
    "starter": {
        "name": "Starter",
        "people": 10,
        "priority_profiles": 3,
        "priority_update_interval": "5h",  # до 5ч
        "post_generations_month": 10,
        "comment_generations_month": 30,
        "rss_sources": 2,
        "reddit_sources": 3,
        "history_days": 7,
        "personas": 1,  # 1 автор
        "features": [],
        "price_monthly": 0,
        "price_quarterly": 0,
        "price_annual": 0,
    },
    "pro": {
        "name": "Pro",
        "people": 50,
        "priority_profiles": 20,
        "priority_update_interval": "3h",  # до 3ч
        "post_generations_month": 30,
        "comment_generations_month": 300,
        "rss_sources": 5,
        "reddit_sources": 10,
        "history_days": 180,
        "personas": 2,
        "analytics_level": "basic",
        "features": ["analytics"],
        "price_monthly": 99,
        "price_quarterly": 237,  # 3 mo × $79 (Save 20%)
        "price_annual": 708,     # 12 mo × $59 (Save 40%)
    },
    "enterprise": {
        "name": "Enterprise",
        "people": 100,
        "priority_profiles": 50,
        "priority_update_interval": "1h",  # до 1ч
        "post_generations_month": 100,
        "comment_generations_month": 1000,
        "rss_sources": 20,
        "reddit_sources": 20,
        "history_days": 730,
        "personas": 5,
        "analytics_level": "extended",
        "features": ["analytics", "inbox", "training", "export_import", "priority_support"],
        "price_monthly": 499,
        "price_quarterly": 1197,  # 3 mo × $399 (Save 20%)
        "price_annual": 3588,    # 12 mo × $299 (Save 40%)
    },
    "tester": {
        # Те же права что и Pro, но бесплатно (для бета-тестеров)
        "name": "Tester",
        "people": 50,
        "priority_profiles": 20,
        "priority_update_interval": "3h",
        "post_generations_month": 30,
        "comment_generations_month": 300,
        "rss_sources": 5,
        "reddit_sources": 10,
        "history_days": 180,
        "personas": 2,
        "analytics_level": "basic",
        "features": ["analytics"],
        "price_monthly": 0,
        "price_quarterly": 0,
        "price_annual": 0,
    },
    "admin": {
        # Полный доступ без ограничений (внутренние пользователи)
        "name": "Admin",
        "people": 999_999,
        "priority_profiles": 999_999,
        "priority_update_interval": "1h",
        "post_generations_month": 999_999,
        "comment_generations_month": 999_999,
        "rss_sources": 999_999,
        "reddit_sources": 999_999,
        "history_days": 9999,
        "personas": 999,
        "analytics_level": "extended",
        "features": ["analytics", "inbox", "training", "export_import", "priority_support"],
        "price_monthly": 0,
        "price_quarterly": 0,
        "price_annual": 0,
    },
}

DEFAULT_PLAN = "starter"


def get_plan(plan_name: Optional[str]) -> dict[str, Any]:
    """Возвращает конфиг плана. Если не найден — Starter."""
    if not plan_name or plan_name not in PLANS:
        return PLANS[DEFAULT_PLAN].copy()
    return PLANS[plan_name].copy()
