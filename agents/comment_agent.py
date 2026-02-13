# agents/comment_agent.py
from typing import Any

from agents.base import AgentBase
from agents.comment_pipeline.pipeline import run_comment_pipeline


class CommentAgent(AgentBase):
    name = "comment_agent"

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        post_text = payload.get("post_text", "")
        goal = payload.get("goal", "network")
        author = payload.get("author") or {}
        products_raw = payload.get("products") or []
        author_answers_66 = payload.get("author_answers_66") or payload.get("fingerprint") or {}

        if not post_text or not post_text.strip():
            return {"comments": {"short": "", "medium": "", "long": ""}, "raw": ""}

        try:
            finals = await run_comment_pipeline(
                post_text=post_text,
                author_answers_66=author_answers_66,
                products=products_raw,
                mode=goal,
                author=author,
                llm=self._llm,
            )
            return {"comments": finals, "raw": str(finals)}
        except Exception as e:
            return {"comments": {"short": "", "medium": "", "long": ""}, "raw": "", "error": str(e)}
