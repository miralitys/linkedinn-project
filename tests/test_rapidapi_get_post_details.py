"""
Тест Get Post Details endpoint Fresh LinkedIn Profile Data.
Запуск: pytest tests/test_rapidapi_get_post_details.py -v -s
Требует RAPIDAPI_KEY в .env.
"""
import pytest
import httpx

from app.config import settings


HOST = "fresh-linkedin-profile-data.p.rapidapi.com"
# Пример URN из реального LinkedIn поста (числовой ID)
SAMPLE_URN = "7133388569078894592"


def test_get_post_details_endpoint_exists():
    """Проверяем, существует ли endpoint get-post-details и какие параметры принимает."""
    if not settings.rapidapi_key:
        pytest.skip("RAPIDAPI_KEY не задан в .env")

    # Вариант 1: параметр urn
    url = f"https://{HOST}/get-post-details"
    params_urn = {"urn": SAMPLE_URN}
    headers = {"X-RapidAPI-Key": settings.rapidapi_key, "X-RapidAPI-Host": HOST}

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params_urn, headers=headers)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        pytest.skip(f"RapidAPI is unreachable in this environment: {e}")

    print(f"\nGET {url}?urn={SAMPLE_URN}")
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        body = resp.json()
        print(f"Response keys: {list(body.keys()) if isinstance(body, dict) else 'not dict'}")
        if isinstance(body, dict) and "data" in body:
            data = body["data"]
            print(f"data keys: {list(data.keys())[:15] if isinstance(data, dict) else 'not dict'}...")
    else:
        print(f"Body: {resp.text[:500]}")

    # 200 = OK, 404 = endpoint или пост не найден
    assert resp.status_code in (200, 404, 400, 401), f"Unexpected status: {resp.status_code}"
