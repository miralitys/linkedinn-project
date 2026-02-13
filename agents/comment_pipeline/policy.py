# agents/comment_pipeline/policy.py — GetPolicy(mode)

from agents.comment_pipeline.config import MODE_NETWORK, POLICIES


def get_policy(mode: str) -> dict:
    """Возвращает CommentPolicy по mode. Fallback на network."""
    return dict(POLICIES.get(mode, POLICIES[MODE_NETWORK]))
