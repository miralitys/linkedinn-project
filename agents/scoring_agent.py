# agents/scoring_agent.py
"""Агент: оценка релевантности новостей и постов Reddit для бизнеса."""
import re
from typing import Any

from agents.base import AgentBase


class ScoringAgent(AgentBase):
    name = "scoring_agent"

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = payload.get("title", "")
        body = payload.get("body", "") or payload.get("content", "")
        subreddit = payload.get("subreddit", "")
        comments = payload.get("comments", [])
        
        author = payload.get("author", "")
        products = payload.get("products", "")
        icp = payload.get("icp", "")

        subreddit_info = f"Subreddit: r/{subreddit}\n" if subreddit else ""
        comments_info = ""
        if comments and isinstance(comments, list):
            comments_text = "\n".join([f"Comment {i+1}: {c}" for i, c in enumerate(comments[:3])])
            comments_info = f"Top comments:\n{comments_text}\n" if comments_text else ""

        system = self.get_system_prompt()
        user_tpl = self.get_user_prompt_template()
        user = user_tpl.format(
            author=author or "Не указано",
            products=products or "Не указано",
            icp=icp or "Не указано",
            title=title or "",
            body=body or "",
            subreddit_info=subreddit_info,
            comments_info=comments_info,
        )
        
        response = await self._llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3,
            max_tokens=256,
        )
        
        # Парсим ответ в формате: Score: XX/100 | Flag: YES/NO | Reason: {текст}
        score_result = self._parse_score_response(response or "")
        
        return {
            "score": score_result.get("score", 0),
            "flag": score_result.get("flag", "NO"),
            "reason": score_result.get("reason", ""),
            "raw": response,
        }

    def _parse_score_response(self, text: str) -> dict[str, Any]:
        """Парсит ответ агента в формате: Score: XX/100 | Flag: YES/NO | Reason: {текст}"""
        if not text:
            return {"score": 0, "flag": "NO", "reason": "No response"}
        
        # Ищем паттерн: Score: XX/100 | Flag: YES/NO | Reason: текст
        pattern = r"Score:\s*(\d+)/100\s*\|\s*Flag:\s*(YES|NO)\s*\|\s*Reason:\s*(.+)"
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        
        if match:
            score = int(match.group(1))
            flag = match.group(2).upper()
            reason = match.group(3).strip()
            return {"score": score, "flag": flag, "reason": reason}
        
        # Если паттерн не найден, пытаемся извлечь score из текста
        score_match = re.search(r"Score:\s*(\d+)", text, re.IGNORECASE)
        if score_match:
            score = int(score_match.group(1))
            flag = "YES" if score >= 70 else "NO"
            return {"score": score, "flag": flag, "reason": "Parsed from text"}
        
        return {"score": 0, "flag": "NO", "reason": "Parse error"}
