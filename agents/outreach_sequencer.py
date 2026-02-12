# agents/outreach_sequencer.py
from typing import Any

from agents.base import AgentBase
from agents.utils import extract_json


class OutreachSequencerAgent(AgentBase):
    name = "outreach_sequencer"

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        person_summary = payload.get("person_summary", "")
        status = payload.get("status", "")
        touches_summary = payload.get("touches_summary", "")
        segment_name = payload.get("segment_name", "")
        reason = payload.get("reason", "нет")

        system = self.get_system_prompt()
        user_tpl = self.get_user_prompt_template()
        user = user_tpl.format(
            person_summary=person_summary,
            status=status,
            touches_summary=touches_summary,
            segment_name=segment_name,
            reason=reason,
        )
        response = await self._llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.4,
            max_tokens=512,
        )
        try:
            data = extract_json(response)
            return {"sequencer": data, "raw": response}
        except Exception:
            return {"sequencer": {}, "raw": response, "error": "Failed to parse JSON"}
