# agents/analytics_agent.py — stub for A9
from typing import Any

from agents.base import AgentBase


class AnalyticsAgent(AgentBase):
    name = "analytics_agent"

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "stub": True,
            "message": "Analytics Agent (A9) — заглушка. Сводка: комментарии, посты, коннекты, warm, DM, ответы, созвоны; бутылочное горлышко.",
            "payload": payload,
        }
