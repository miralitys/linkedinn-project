# agents/comment_pipeline/detectors.py — CTA, links, forbidden_claim

import re
from typing import List, Optional


# CTA patterns (EN + RU)
CTA_PATTERNS = [
    r"\bDM\s+me\b",
    r"\bdm\s+me\b",
    r"\bbook\s+a\s+call\b",
    r"\bschedule\s+a\s+call\b",
    r"\bsign\s+up\b",
    r"\btry\s+it\b",
    r"\btry\s+free\b",
    r"\bget\s+started\b",
    r"\blet'?s\s+connect\b",
    r"\blet'?s\s+chat\b",
    r"\breach\s+out\b",
    r"\bping\s+me\b",
    r"\bhit\s+me\s+up\b",
    r"\blink\s+in\s+(bio|comments)\b",
    r"\blink\s+below\b",
    r"\bв\s+личку\b",
    r"\bнапиши\s+в\s+личку\b",
    r"\bнапишите\s+в\s+личку\b",
    r"\bзапишись\b",
    r"\bзапишитесь\b",
    r"\bзабронируй\b",
    r"\bпопробуй\b",
    r"\bпопробуйте\b",
    r"\bдавай\s+свяжемся\b",
    r"\bдавайте\s+свяжемся\b",
    r"\bнапиши\s+мне\b",
    r"\bнапишите\s+мне\b",
    r"\bскинь\s+ссылку\b",
    r"\bподробнее\s+в\s+комментах\b",
]
_CTA_RE = re.compile("|".join(CTA_PATTERNS), re.IGNORECASE)

# Link patterns
LINK_PATTERNS = [
    r"https?://[^\s]+",
    r"www\.[^\s]+",
    r"linkedin\.com/[^\s]*",
    r"bit\.ly/[^\s]*",
    r"t\.me/[^\s]*",
]
_LINK_RE = re.compile("|".join(LINK_PATTERNS), re.IGNORECASE)


def detect_cta(text: str) -> bool:
    """True if text contains CTA-like phrases."""
    if not text or not text.strip():
        return False
    return bool(_CTA_RE.search(text))


def has_links(text: str) -> bool:
    """True if text contains URLs or link references."""
    if not text or not text.strip():
        return False
    return bool(_LINK_RE.search(text))


def has_em_dash(text: str) -> bool:
    """True if text contains em dash (—) or en dash (–)."""
    if not text:
        return False
    return "—" in text or "–" in text


def has_colon(text: str) -> bool:
    """True if text contains colon (:) outside of URLs."""
    if not text or not text.strip():
        return False
    no_urls = re.sub(r"https?://\S+", "", text, flags=re.IGNORECASE)
    no_urls = re.sub(r"www\.\S+", "", no_urls, flags=re.IGNORECASE)
    return ":" in no_urls


def sanitize_punctuation(text: str) -> str:
    """Удаляет em dash, en dash и двоеточие (вне URL). Оставляет только точки и запятые."""
    if not text:
        return text
    s = text.replace("—", ",").replace("–", ",")
    # Убрать двоеточие только вне URL
    parts = re.split(r"(https?://\S+|www\.\S+)", s, flags=re.IGNORECASE)
    result = []
    for part in parts:
        if re.match(r"https?://|www\.", part, re.IGNORECASE):
            result.append(part)
        else:
            result.append(part.replace(":", "."))
    return "".join(result)


def detect_forbidden_claim_violation(text: str, forbidden_claims: List[str]) -> bool:
    """True if text contains any phrase from forbidden_claims (case-insensitive)."""
    if not text or not forbidden_claims:
        return False
    text_lower = text.lower()
    for claim in forbidden_claims:
        if not claim or not isinstance(claim, str):
            continue
        if claim.lower().strip() in text_lower:
            return True
    return False


def _product_names_and_aliases(product: dict) -> List[str]:
    """Список имён продукта: name + aliases."""
    names = []
    if product:
        n = product.get("name")
        if n and isinstance(n, str):
            names.append(n.strip())
        for a in product.get("aliases") or []:
            if a and isinstance(a, str):
                names.append(a.strip())
    return [x for x in names if x]


def product_mentioned_in_draft(text: str, product_plan: Optional[dict]) -> bool:
    """True если в тексте упомянуто имя продукта или любой alias (case-insensitive)."""
    if not text or not product_plan:
        return False
    product = product_plan.get("selected_product") or {}
    names = _product_names_and_aliases(product)
    text_lower = text.lower()
    for n in names:
        if n.lower() in text_lower:
            return True
    return False


def count_product_mentions(text: str, product_plan: Optional[dict]) -> int:
    """Количество упоминаний продукта (name + aliases) в тексте."""
    if not text or not product_plan:
        return 0
    product = product_plan.get("selected_product") or {}
    names = _product_names_and_aliases(product)
    text_lower = text.lower()
    count = 0
    for n in names:
        if not n:
            continue
        n_lower = n.lower()
        count += text_lower.count(n_lower)
    return count


def detect_product_mention_any(text: str, products: List[dict]) -> bool:
    """True если текст упоминает любой продукт из списка (name или alias)."""
    if not text or not products:
        return False
    text_lower = text.lower()
    for p in products:
        if not isinstance(p, dict):
            continue
        for n in _product_names_and_aliases(p):
            if n.lower() in text_lower:
                return True
    return False
