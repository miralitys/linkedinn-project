# agents/kol_curator.py — stub for A10
from typing import Any

from agents.base import AgentBase


class KOLCuratorAgent(AgentBase):
    name = "kol_curator"

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "stub": True,
            "message": "KOL Curator (A10) — заглушка. Поиск лидеров мнений, приоритеты, список 30–100.",
            "payload": payload,
        }
