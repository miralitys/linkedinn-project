# agents/enrichment_agent.py
from typing import Any

from agents.base import AgentBase
from agents.utils import extract_json


class EnrichmentAgent(AgentBase):
    name = "enrichment_agent"

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_input = payload.get("raw_input", "")
        entity_type = payload.get("entity_type", "person")  # company | person

        system = self.get_system_prompt()
        user_tpl = self.get_user_prompt_template()
        user = user_tpl.format(raw_input=raw_input, entity_type=entity_type)
        response = await self._llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
            max_tokens=2048,
        )
        try:
            data = extract_json(response)
            return {"enrichment": data, "raw": response}
        except Exception:
            return {"enrichment": {}, "raw": response, "error": "Failed to parse JSON"}
