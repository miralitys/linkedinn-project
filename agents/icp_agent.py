# agents/icp_agent.py
from typing import Any

from agents.base import AgentBase
from agents.utils import extract_json


class ICPAgent(AgentBase):
    name = "icp_agent"

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        hypotheses = payload.get("hypotheses", "")
        examples = payload.get("examples", "")

        system = self.get_system_prompt()
        user = self.render_user_prompt(hypotheses=hypotheses, examples=examples)
        response = await self._llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.4,
            max_tokens=2048,
        )
        try:
            data = extract_json(response)
            return {"segments": data.get("segments", data) if isinstance(data, dict) else data, "raw": response}
        except Exception:
            return {"segments": [], "raw": response, "error": "Failed to parse JSON"}
