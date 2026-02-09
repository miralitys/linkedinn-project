# agents/lead_magnet_builder.py — stub for A8
from typing import Any

from agents.base import AgentBase


class LeadMagnetBuilderAgent(AgentBase):
    name = "lead_magnet_builder"

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "stub": True,
            "message": "Lead Magnet Builder (A8) — заглушка. Вход: offer/segment. Выход: PDF/Doc structure + 3 варианта подачи.",
            "payload": payload,
        }
