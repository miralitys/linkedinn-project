# agents/content_agent.py
from typing import Any

from agents.base import AgentBase
from agents.utils import extract_json


class ContentAgent(AgentBase):
    name = "content_agent"

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        sales_avatar = payload.get("sales_avatar", "")
        segment_name = payload.get("segment_name", "")
        offer_or_lead_magnet = payload.get("offer_or_lead_magnet", "")
        thesis = payload.get("thesis", "")

        system = self.get_system_prompt()
        user_tpl = self.get_user_prompt_template()
        user = user_tpl.format(
            sales_avatar=sales_avatar,
            segment_name=segment_name,
            offer_or_lead_magnet=offer_or_lead_magnet,
            thesis=thesis,
        )
        response = await self._llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.6,
            max_tokens=2048,
        )
        try:
            data = extract_json(response)
            return {"content": data, "raw": response}
        except Exception:
            return {"content": {}, "raw": response, "error": "Failed to parse JSON"}
