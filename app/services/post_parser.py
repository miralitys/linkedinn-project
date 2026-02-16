# app/services/post_parser.py
"""
Парсинг поста по прямой ссылке: Playwright открывает URL, скриншот карточки поста → OpenAI Vision → JSON.
Генерация постов и комментариев — через OpenRouter (Claude). Требует: playwright, openai.
"""
import base64
import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

from app.config import settings

# Селекторы для карточки поста (LinkedIn и др.) — по порядху попытки
POST_CARD_SELECTORS = [
    "article",
    "[role='article']",
    ".feed-shared-update-v2",
    ".scaffold-finite-scroll__content > div",
    "main section",
    "main",
]

VISION_PROMPT = """По скриншоту карточки поста в соцсети (LinkedIn или другой) верни строго один JSON-объект без markdown и без пояснений.
Схема:
{
  "author_name": "имя автора поста (как на экране)",
  "author_profile_url": "URL профиля или null если не видно",
  "post_url": "URL этого поста или null",
  "published_at": "дата публикации поста КАК НА ЭКРАНЕ LinkedIn (например 5 дн. или 7 фев 2026 или 2023-11-23 09:39:26). НЕ текущую дату!",
  "text": "полный текст поста — СТРОГО ДОСЛОВНАЯ транскрипция",
  "media_present": true или false,
  "reactions_count": число или null,
  "comments_count": число или null,
  "reposts_count": число или null,
  "views_count": число или null
}
Если чего-то не видно — используй null. published_at — ОБЯЗАТЕЛЬНО дата создания поста на LinkedIn (относительная: 5 дн., 1 нед., или точная: 7 фев 2026, 2023-11-23). Никогда не подставляй текущую дату.

═══════════════════════════════════════════════════════════════
ОБЯЗАТЕЛЬНОЕ ПРАВИЛО ДЛЯ "text" — OCR/ТРАНСКРИПЦИЯ, НЕ ПЕРЕСКАЗ:
═══════════════════════════════════════════════════════════════
Ты выполняешь функцию OCR: переносишь текст с картинки 1:1, слово в слово.

ЗАПРЕЩЕНО:
- Перефразировать, упрощать, подбирать синонимы или антонимы.
- Менять слова: "beneficial" нельзя заменять на "risky", "aging" на "trust", "establish" на "promote". Каждое слово — как на экране.
- Обрезать конец поста. Последняя фраза должна быть полностью: например "create that Reddit account today; you will thank yourself later", а не "create that account today!".

ОБЯЗАТЕЛЬНО:
- Копировать каждое слово дословно. Язык оригинала не менять (английский → английский).
- Включить весь текст от первого до последнего предложения. Концовка "you will thank yourself later" и подобные фразы — обязательны.
Результат — дословная копия, как при OCR."""


def _user_facing_openai_error(exc: Exception) -> str:
    """
    Возвращает безопасный текст ошибки для UI без внутренних деталей API/trace.
    Полный текст исключения пишется только в серверные логи.
    """
    msg = str(exc or "").lower()
    if "invalid_api_key" in msg or "incorrect api key" in msg:
        return "OPENAI_API_KEY некорректный. Проверьте ключ в .env и перезапустите сервер."
    if "insufficient_quota" in msg or "quota" in msg or "billing" in msg:
        return "У OpenAI закончился лимит/биллинг. Проверьте квоту и оплату аккаунта."
    if "rate limit" in msg or "too many requests" in msg:
        return "OpenAI временно ограничил запросы. Подождите немного и повторите."
    if "timed out" in msg or "timeout" in msg:
        return "OpenAI не ответил вовремя. Повторите попытку."
    if "model" in msg and "not found" in msg:
        return "Указанная модель OpenAI недоступна. Проверьте OPENAI_MODEL."
    if "unsupported parameter" in msg:
        return "Текущая модель OpenAI не поддерживает параметры запроса. Обновите настройки модели."
    return "Ошибка распознавания через OpenAI. Повторите попытку позже."


async def _screenshot_post_card(url: str, user_data_dir: Optional[str] = None) -> tuple[Optional[bytes], Optional[str]]:
    """Открывает url в Chromium, снимает скриншот карточки поста (или страницы). Возвращает (PNG bytes, None) или (None, error_message)."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None, "Playwright не установлен. Выполните: pip install playwright && playwright install chromium"

    try:
        async with async_playwright() as p:
            if user_data_dir:
                profile_directory = (settings.playwright_profile_directory or "Default").strip() or "Default"
                persistent_args = [f"--profile-directory={profile_directory}"]
                try:
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir,
                        channel="chrome",
                        headless=True,
                        viewport={"width": 1200, "height": 1400},
                        timeout=15000,
                        args=persistent_args,
                        ignore_default_args=["--use-mock-keychain"],
                    )
                except Exception:
                    # Fallback: bundled Chromium без channel/args.
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir,
                        headless=True,
                        viewport={"width": 1200, "height": 1400},
                        timeout=15000,
                        ignore_default_args=["--use-mock-keychain"],
                    )
                page = context.pages[0] if context.pages else await context.new_page()
            else:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={"width": 1200, "height": 1400},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                page = await context.new_page()

            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(3000)

            # Закрываем и скрываем всё, что перекрывает пост (модалки входа, оверлеи)
            for _ in range(3):
                try:
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(300)
                except Exception:
                    pass
            await page.evaluate("""() => {
                const closeSelectors = [
                    'button[aria-label="Dismiss"]', 'button[aria-label="Закрыть"]', 'button[aria-label="Close"]',
                    '.artdeco-modal__dismiss', 'button.artdeco-modal__dismiss',
                    '[data-test-id="modal-dismiss"]', 'button[aria-label*="ismiss"]', 'button[aria-label*="lose"]'
                ];
                for (const sel of closeSelectors) {
                    const btn = document.querySelector(sel);
                    if (btn) { btn.click(); return; }
                }
                document.querySelectorAll('[role="dialog"], .artdeco-modal').forEach(m => {
                    const close = m.querySelector('button[aria-label], .artdeco-modal__dismiss');
                    if (close) close.click();
                });
            }""")
            await page.wait_for_timeout(500)
            # Скрываем оверлеи и модалки (Sign in, cookie banner и т.п.), чтобы пост не перекрывался
            await page.add_style_tag(content="""[role="dialog"], .artdeco-modal, .sign-in-modal, [data-test-modal], .modal-overlay, .artdeco-modal__backdrop, [class*="auth-wall"], [class*="sign-in-overlay"] { display: none !important; visibility: hidden !important; opacity: 0 !important; pointer-events: none !important; }""")
            await page.wait_for_timeout(300)

            # Раскрываем «see more» — JS ищет и кликает все кнопки/спаны с текстом "see more", "… more", "ещё" и т.п.
            async def _click_see_more():
                return await page.evaluate("""() => {
                    const expandTexts = ['see more', '… more', '... more', '...more', 'ещё', 'показать ещё'];
                    const collapseText = 'see less';
                    const els = document.querySelectorAll('button, span[role="button"], .feed-shared-inline-show-more-text__see-more-less-toggle');
                    let clicked = 0;
                    for (const el of els) {
                        const t = (el.textContent || el.innerText || '').toLowerCase();
                        if (t.includes(collapseText)) continue;
                        if (expandTexts.some(v => t.includes(v)) || el.classList.contains('feed-shared-inline-show-more-text__see-more-less-toggle')) {
                            try {
                                el.scrollIntoView({ block: 'center' });
                                el.click();
                                clicked++;
                            } catch (e) {}
                        }
                    }
                    return clicked;
                }""")

            for _ in range(3):  # до 3 итераций (может быть несколько «see more»)
                n = await _click_see_more()
                await page.wait_for_timeout(1200)
                if n == 0:
                    break

            # Дополнительно: селекторы LinkedIn
            for sel in ["button.feed-shared-inline-show-more-text__see-more-less-toggle", "button:has-text('see more')", "button:has-text('See more')", "span:has-text('… more')"]:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0:
                        await btn.scroll_into_view_if_needed()
                        await btn.click(timeout=2000)
                        await page.wait_for_timeout(1500)
                except Exception:
                    pass

            screenshot_bytes = None
            for selector in POST_CARD_SELECTORS:
                try:
                    loc = page.locator(selector).first
                    if await loc.count() > 0:
                        await loc.scroll_into_view_if_needed()
                        await page.wait_for_timeout(500)
                        # Повторная попытка раскрыть «see more» внутри найденной карточки
                        for see_more_sel in ["button.feed-shared-inline-show-more-text__see-more-less-toggle", "button:has-text('see more')", "button:has-text('See more')", "span:has-text('… more')", "button:has-text('ещё')", "span:has-text('ещё')"]:
                            try:
                                btn = loc.locator(see_more_sel).first
                                if await btn.count() > 0:
                                    await btn.scroll_into_view_if_needed()
                                    await btn.click(timeout=2000)
                                    await page.wait_for_timeout(1500)
                                    break
                            except Exception:
                                continue
                        screenshot_bytes = await loc.screenshot(type="png", timeout=5000)
                        break
                except Exception:
                    continue
            if not screenshot_bytes:
                screenshot_bytes = await page.screenshot(type="png")

            if user_data_dir:
                await context.close()
            else:
                await browser.close()
            return screenshot_bytes, None
    except Exception as e:
        logging.exception("post_parser screenshot failed: %s", e)
        return None, str(e)


async def capture_post_screenshot_base64(url: str, user_data_dir: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """
    Делает скриншот карточки поста и возвращает (base64_png, None) или (None, error_message).
    Нужен как лёгкий fallback для UI, когда данные поста пришли не из OCR.
    """
    screenshot_bytes, screenshot_error = await _screenshot_post_card(url, user_data_dir=user_data_dir)
    if not screenshot_bytes:
        return None, screenshot_error or "Не удалось сделать скриншот страницы."
    return base64.standard_b64encode(screenshot_bytes).decode("ascii"), None


def _parse_vision_json(raw: str) -> Optional[dict[str, Any]]:
    """Извлекает JSON из ответа модели (может быть обёрнут в ```json ... ```)."""
    raw = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        raw = m.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def parse_post_from_url(
    url: str,
    *,
    user_data_dir: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    openai_model: str = "gpt-5.2",
) -> dict[str, Any]:
    """
    Открывает url, снимает скриншот карточки поста, отправляет в OpenAI Vision, возвращает распознанный JSON.
    При ошибке возвращает {"error": "..."}.
    """
    screenshot_bytes, screenshot_error = await _screenshot_post_card(url, user_data_dir=user_data_dir)
    if not screenshot_bytes:
        return {"error": screenshot_error or "Не удалось сделать скриншот страницы."}

    b64 = base64.standard_b64encode(screenshot_bytes).decode("ascii")
    api_key = openai_api_key or settings.openai_api_key
    if not api_key:
        return {"error": "OPENAI_API_KEY не задан. Нужен для распознавания текста по скриншоту (функция «Распознать по ссылке»)."}

    try:
        from openai import AsyncOpenAI
    except ImportError:
        return {"error": "Пакет openai не установлен."}

    client = AsyncOpenAI(api_key=api_key)
    content: list[Any] = [
        {"type": "text", "text": VISION_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]
    resp = None
    vision_error: Optional[Exception] = None
    request_kwargs = {
        "model": openai_model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
    }
    # У разных моделей OpenAI разный параметр лимита токенов:
    # сначала пробуем современный max_completion_tokens, затем fallback на max_tokens.
    for token_param in ("max_completion_tokens", "max_tokens"):
        try:
            resp = await client.chat.completions.create(
                **request_kwargs,
                **{token_param: 8192},
            )
            vision_error = None
            break
        except Exception as e:
            vision_error = e
            msg = str(e or "").lower()
            if "unsupported parameter" in msg and token_param in msg:
                continue
            break

    if resp is None:
        e = vision_error or Exception("unknown_openai_error")
        logging.exception("post_parser vision failed: %s", e)
        return {"error": _user_facing_openai_error(e)}

    raw = (resp.choices[0].message.content or "").strip() if resp.choices else ""
    parsed = _parse_vision_json(raw)
    if not parsed:
        return {"error": "Модель не вернула валидный JSON.", "raw": raw[:500]}

    parsed.setdefault("post_url", url)
    parsed["_screenshot_base64"] = b64
    return parsed
