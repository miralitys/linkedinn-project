# agents/news_post_agent.py
"""Агент: авторский LinkedIn-пост на основе новости (профиль автора + продукты + цель)."""
from typing import Any

from agents.base import AgentBase


def _get_length_range(length: str) -> tuple[int, int]:
    """Возвращает (минимум, максимум) для указанной длины."""
    ranges = {
        "short": (600, 900),
        "medium": (900, 1400),
        "long": (1400, 2200),
    }
    return ranges.get(length, (900, 1400))


def _count_chars(text: str) -> int:
    """Подсчитывает количество знаков без пробелов и переносов."""
    return len("".join((text or "").split()))


async def _adjust_post_length(post_text: str, length: str, llm) -> str:
    """Корректирует длину поста до нужного диапазона."""
    min_chars, max_chars = _get_length_range(length)
    current_chars = _count_chars(post_text)
    
    if min_chars <= current_chars <= max_chars:
        return post_text
    
    if current_chars < min_chars:
        # Нужно расширить пост
        diff = min_chars - current_chars
        adjustment_prompt = f"""Пост слишком короткий ({current_chars} знаков без пробелов). Нужно минимум {min_chars} знаков без пробелов.
Расширь пост, добавив примерно {diff} знаков без пробелов. Сохрани структуру и смысл, добавь детали, разверни мысли.

Текущий пост:
{post_text}

Верни расширенный пост длиной минимум {min_chars} и максимум {max_chars} знаков без пробелов."""
        response = await llm.chat([
            {"role": "user", "content": adjustment_prompt}
        ])
        adjusted = (response or "").strip()
        adjusted_chars = _count_chars(adjusted)
        if min_chars <= adjusted_chars <= max_chars:
            return adjusted
        # Если все еще не в диапазоне, попробуем еще раз или вернем как есть
        return adjusted if adjusted_chars >= min_chars else post_text
    
    else:  # current_chars > max_chars
        # Нужно сократить пост
        diff = current_chars - max_chars
        adjustment_prompt = f"""Пост слишком длинный ({current_chars} знаков без пробелов). Нужно максимум {max_chars} знаков без пробелов.
Сократи пост примерно на {diff} знаков без пробелов. Сохрани структуру и смысл, убери повторы, сожми формулировки.

Текущий пост:
{post_text}

Верни сокращенный пост длиной минимум {min_chars} и максимум {max_chars} знаков без пробелов."""
        response = await llm.chat([
            {"role": "user", "content": adjustment_prompt}
        ])
        adjusted = (response or "").strip()
        adjusted_chars = _count_chars(adjusted)
        if min_chars <= adjusted_chars <= max_chars:
            return adjusted
        # Если все еще не в диапазоне, попробуем еще раз или вернем как есть
        return adjusted if adjusted_chars <= max_chars else post_text


class NewsPostAgent(AgentBase):
    name = "news_post_agent"

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        news_text = payload.get("news_text", "") or payload.get("post_text", "")
        sales_avatar = payload.get("sales_avatar", "")
        goal = payload.get("goal", "network")
        author = payload.get("author") or {}
        products_raw = payload.get("products") or []

        if author and (author.get("full_name") or author.get("history")):
            author_desc = (
                f"Имя: {author.get('full_name', '')}. "
                f"Роль: {author.get('role') or '—'}. "
                f"История/стиль: {author.get('history') or '—'}"
            )
        else:
            author_desc = "Автор не выбран — пиши в общем тоне, нейтрально."

        products_lines = []
        for i, p in enumerate(products_raw, 1):
            if isinstance(p, dict):
                name = p.get("name") or ""
                one_liner = p.get("one_liner") or ""
                desc = p.get("description") or ""
                human = one_liner or desc
                products_lines.append(f"{i}. {name}" + (f" — {human}" if human else ""))
            elif isinstance(p, str) and p.strip():
                products_lines.append(f"{i}. {p.strip()}")
        products_str = "\n".join(products_lines) if products_lines else "Продукты не загружены."

        goal_label = {
            "network": "network",
            "native_ads": "native_ads",
            "full_ads": "full_ads",
        }.get(goal, goal)

        length = payload.get("length", "medium")
        length_label = {
            "short": "короткий",
            "medium": "средний",
            "long": "длинный",
        }.get(length, "средний")

        system = self.get_system_prompt()
        user = self.render_user_prompt(
            news_text=news_text,
            sales_avatar=sales_avatar,
            goal=goal_label,
            author=author_desc,
            products=products_str,
            length=length_label,
        )
        response = await self._llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.5,
            max_tokens=2048,
        )
        post_text = (response or "").strip()
        
        # Проверяем и корректируем длину поста
        min_chars, max_chars = _get_length_range(length)
        current_chars = _count_chars(post_text)
        
        if not (min_chars <= current_chars <= max_chars):
            # Корректируем длину
            post_text = await _adjust_post_length(post_text, length, self._llm)
            current_chars = _count_chars(post_text)
        
        return {
            "post": post_text,
            "raw": response,
            "length": current_chars,
            "length_range": {"min": min_chars, "max": max_chars},
            "length_valid": min_chars <= current_chars <= max_chars,
        }
