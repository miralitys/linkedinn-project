# agents/comment_agent.py
from typing import Any

from agents.base import AgentBase
from agents.utils import extract_json


class CommentAgent(AgentBase):
    name = "comment_agent"

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        post_text = payload.get("post_text", "")
        sales_avatar = payload.get("sales_avatar", "")
        goal = payload.get("goal", "network")
        author = payload.get("author") or {}
        products_raw = payload.get("products") or []

        if author and author.get("full_name"):
            author_desc = (
                f"Имя: {author.get('full_name', '')}. "
                f"Роль: {author.get('role') or '—'}. "
                f"История/стиль: {author.get('history') or '—'}"
            )
        else:
            author_desc = "Автор не выбран — пиши в нейтральном, профессиональном тоне."

        products_lines = []
        for i, p in enumerate(products_raw, 1):
            if isinstance(p, dict):
                name = p.get("name") or ""
                desc = p.get("description") or ""
                products_lines.append(f"{i}. {name}" + (f" — {desc}" if desc else ""))
            elif isinstance(p, str) and p.strip():
                products_lines.append(f"{i}. {p.strip()}")
        products_str = "\n".join(products_lines) if products_lines else "Продукты не загружены."

        # Определяем язык поста: если больше кириллицы — русский, иначе английский
        cyrillic = sum(1 for c in post_text if "\u0400" <= c <= "\u04FF")
        latin = sum(1 for c in post_text if "a" <= c.lower() <= "z")
        post_language = "Russian" if cyrillic >= latin else "English"

        system = self.get_system_prompt()
        user_tpl = self.get_user_prompt_template()
        # Маппинг целей на формат промпта
        goal_map = {
            "network": "**Network**",
            "native_ads": "**Нативная реклама**",
            "full_ads": "**Сто процентов рекламы**"
        }
        goal_formatted = goal_map.get(goal, goal)
        
        user = user_tpl.format(
            post_text=post_text,
            goal=goal_formatted,
            author=author_desc,
            products=products_str,
            post_language=post_language,
        )
        response = await self._llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.5,
            max_tokens=512,
        )
        try:
            data = extract_json(response)
            return {"comments": data, "raw": response}
        except Exception:
            return {"comments": {}, "raw": response, "error": "Failed to parse JSON"}
