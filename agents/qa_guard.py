# agents/qa_guard.py
from typing import Any

from agents.base import AgentBase
from agents.utils import extract_json


class QAGuardAgent(AgentBase):
    name = "qa_guard"

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        context = payload.get("context", "")
        content_type = payload.get("content_type", "post")
        text = payload.get("text", "")

        system = self.get_system_prompt()
        user = self.render_user_prompt(context=context, content_type=content_type, text=text)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            response = await self._llm.chat(messages, temperature=0.2, max_tokens=2048)
        except TypeError:
            # Support tests/mocks where chat is attached as a plain class function.
            chat_fn = getattr(type(self._llm), "chat", None)
            if not callable(chat_fn):
                raise
            response = await chat_fn(messages, temperature=0.2, max_tokens=2048)
        try:
            data = extract_json(response)
            ok = data.get("ok", False)
            risks = data.get("risks", {})
            for k in ("hallucination", "tone_drift", "spam_pattern", "aggressiveness", "policy_risk"):
                if k not in risks:
                    risks[k] = 0
            return {
                "ok": ok,
                "risks": risks,
                "fixes": data.get("fixes", []),
                "rewritten_text": data.get("rewritten_text"),
                "raw": response,
            }
        except Exception:
            return {
                "ok": False,
                "risks": {},
                "fixes": [],
                "rewritten_text": None,
                "raw": response,
                "error": "Failed to parse JSON",
            }
