# agents/setup_agent.py
from typing import Any

from agents.base import AgentBase
from agents.utils import extract_json


class SetupAgent(AgentBase):
    name = "setup_agent"

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        product = payload.get("product", "")
        icp_raw = payload.get("icp_raw", "")
        tone = payload.get("tone", "")
        goals = payload.get("goals", "")

        system = self.get_system_prompt()
        user = self.render_user_prompt(
            product=product,
            icp_raw=icp_raw,
            tone=tone,
            goals=goals,
        )
        response = await self._llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.5,
            max_tokens=4096,
        )
        try:
            data = extract_json(response)
            return {"data": data, "raw": response}
        except Exception:
            return {"data": None, "raw": response, "error": "Failed to parse JSON"}
