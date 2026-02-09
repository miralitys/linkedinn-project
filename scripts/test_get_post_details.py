#!/usr/bin/env python3
"""
Ручная проверка Get Post Details endpoint Fresh LinkedIn Profile Data.
Запуск: python scripts/test_get_post_details.py
Требует RAPIDAPI_KEY в .env.
"""
import sys
sys.path.insert(0, ".")

import httpx
from app.config import settings

HOST = "fresh-linkedin-profile-data.p.rapidapi.com"
SAMPLE_URN = "7133388569078894592"


def main():
    if not settings.rapidapi_key:
        print("❌ RAPIDAPI_KEY не задан. Добавьте в .env:")
        print("   RAPIDAPI_KEY=your-key")
        return 1

    url = f"https://{HOST}/get-post-details"
    params = {"urn": SAMPLE_URN}
    headers = {"X-RapidAPI-Key": settings.rapidapi_key, "X-RapidAPI-Host": HOST}

    print(f"GET {url}")
    print(f"Params: urn={SAMPLE_URN}")
    print("-" * 50)

    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, params=params, headers=headers)

    print(f"Status: {resp.status_code}")
    print(f"Headers: {dict(resp.headers)}")
    print("-" * 50)

    try:
        body = resp.json()
        import json
        print("Response JSON:")
        print(json.dumps(body, indent=2, ensure_ascii=False)[:2000])
    except Exception:
        print("Response (raw):", resp.text[:1000])

    if resp.status_code == 200:
        print("\n✅ Endpoint существует и возвращает 200")
    elif resp.status_code == 404:
        print("\n⚠️ 404 — endpoint может называться иначе или пост не найден")
    elif resp.status_code in (400, 401, 403):
        print(f"\n⚠️ {resp.status_code} — проверьте ключ или параметры API")
    return 0


if __name__ == "__main__":
    sys.exit(main())
