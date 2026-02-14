# agents/base.py
"""Base agent: load prompts from /prompts, call LLM, return structured result."""
from pathlib import Path
import re
from typing import Any

from app.config import settings

from agents.llm_client import get_llm_client


def load_prompt(name: str, kind: str = "system") -> str:
    """Load prompt from prompts/{agent_name}_{kind}.txt or fallback to default."""
    path = settings.prompts_dir / f"{name}_{kind}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


class AgentBase:
    """Base for all agents: system + user template, LLM call, no hallucination rule."""
    name: str = "base"
    system_prompt_extra: str = (
        "НЕ ВЫДУМЫВАЙ ФАКТЫ. Если данных нет — напиши «неизвестно» и задай уточняющие вопросы. "
        "Ссылайся только на входной текст или предоставленные данные."
    )

    def __init__(self, llm_client=None):
        self._llm = llm_client or get_llm_client()

    def get_system_prompt(self) -> str:
        base = load_prompt(self.name, "system")
        if base:
            return base + "\n\n" + self.system_prompt_extra
        return self.system_prompt_extra

    def get_user_prompt_template(self) -> str:
        return load_prompt(self.name, "user") or "Входные данные:\n{payload}"

    def render_user_prompt(self, **kwargs: Any) -> str:
        """Safely render {placeholders} without crashing on literal JSON braces."""
        template = self.get_user_prompt_template()
        pattern = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

        def replacer(match: re.Match[str]) -> str:
            key = match.group(1)
            if key in kwargs:
                value = kwargs[key]
                return "" if value is None else str(value)
            return match.group(0)

        rendered = pattern.sub(replacer, template)
        # Keep compatibility with templates that used {{ }} for literal braces.
        return rendered.replace("{{", "{").replace("}}", "}")

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Override in subclass: build messages, call _llm.chat(), parse result."""
        raise NotImplementedError
