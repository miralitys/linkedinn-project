#!/usr/bin/env python3
"""Проверка запроса к OpenRouter (Claude). Запуск: python scripts/test_openrouter.py"""
import asyncio
import sys

# чтобы подхватить .env и app
sys.path.insert(0, ".")


async def main():
    from agents.llm_client import get_llm_client
    from app.config import settings

    print("Провайдер:", settings.lfas_llm_provider)
    print("Модель:", settings.lfas_llm_model)
    print("OPENROUTER_API_KEY задан:", bool(settings.openrouter_api_key))
    print("Запрос к OpenRouter...")

    client = get_llm_client()
    reply = await client.chat(
        [
            {"role": "system", "content": "Ты помощник. Отвечай кратко."},
            {"role": "user", "content": "Напиши одно предложение: привет, это тест API."},
        ],
        temperature=0.3,
        max_tokens=100,
    )
    print("Ответ:", reply)
    print("OK, API работает.")


if __name__ == "__main__":
    asyncio.run(main())
