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
    """Удаляет em dash, en dash и двоеточие (вне URL). Остальную пунктуацию сохраняет."""
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


def _script_letter_counts(text: str) -> tuple[int, int]:
    """Возвращает (cyrillic_count, latin_count)."""
    if not text:
        return (0, 0)
    cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04FF")
    latin = sum(1 for c in text if "a" <= c.lower() <= "z")
    return (cyrillic, latin)


def detect_language_mismatch(text: str, expected_language: Optional[str]) -> bool:
    """
    True, если язык текста явно не совпадает с expected_language.
    expected_language: "English" | "Russian" (case-insensitive).
    """
    lang = (expected_language or "").strip().lower()
    if lang not in {"english", "russian"}:
        return False
    cyrillic, latin = _script_letter_counts(text or "")
    if cyrillic + latin < 12:
        # Слишком мало букв для уверенного вывода.
        return False
    if lang == "english":
        return cyrillic >= 10 and cyrillic > latin
    # expected Russian
    return latin >= 12 and latin > cyrillic


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


_WORD_RE = re.compile(r"[a-zA-Zа-яА-Я0-9']+")


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [w.lower() for w in _WORD_RE.findall(text)]


def _has_ngram_overlap(
    source_tokens: List[str],
    target_tokens: List[str],
    *,
    ngram_size: int,
    max_shared_ngrams: int,
) -> bool:
    if len(source_tokens) < ngram_size or len(target_tokens) < ngram_size:
        return False
    source_ngrams = {
        tuple(source_tokens[i : i + ngram_size])
        for i in range(len(source_tokens) - ngram_size + 1)
    }
    shared = 0
    for i in range(len(target_tokens) - ngram_size + 1):
        if tuple(target_tokens[i : i + ngram_size]) in source_ngrams:
            shared += 1
            if shared > max_shared_ngrams:
                return True
    return False


def detect_post_copy_overlap(
    draft: str,
    post_text: str,
    *,
    ngram_size: int = 4,
    max_shared_ngrams: int = 1,
) -> bool:
    """
    True if draft appears to copy phrases from post verbatim.
    Uses n-gram overlap as a lightweight plagiarism guard.
    """
    if not draft or not post_text:
        return False
    draft_tokens = _tokenize(draft)
    post_tokens = _tokenize(post_text)
    return _has_ngram_overlap(
        source_tokens=post_tokens,
        target_tokens=draft_tokens,
        ngram_size=ngram_size,
        max_shared_ngrams=max_shared_ngrams,
    )


def detect_anchor_copy_overlap(
    draft: str,
    anchors: Optional[List[str]],
    *,
    ngram_size: int = 3,
    max_shared_ngrams: int = 0,
) -> bool:
    """
    True if draft reuses anchor phrases too literally.
    Anchors should stay semantic context, not be copied as wording.
    """
    if not draft or not anchors:
        return False
    draft_tokens = _tokenize(draft)
    if len(draft_tokens) < ngram_size:
        return False
    for anchor in anchors:
        if not anchor or not isinstance(anchor, str):
            continue
        anchor_tokens = _tokenize(anchor)
        if _has_ngram_overlap(
            source_tokens=anchor_tokens,
            target_tokens=draft_tokens,
            ngram_size=ngram_size,
            max_shared_ngrams=max_shared_ngrams,
        ):
            return True
    return False


_POST_RHETORIC_PATTERNS = [
    r"\b(comparison|analogy|metaphor)\s+(is|was)\s+(spot on|accurate|right|true)\b",
    r"\b(comparison|analogy|metaphor)\s+(nails it|hits different|works|checks out)\b",
    r"\b(casino (comparison|analogy|metaphor))\s+(is|was)?\s*(spot on|accurate|right|true|nails it|hits different)\b",
    r"\b(i agree with (the )?(comparison|analogy|metaphor))\b",
    r"\b(casino comparison)\b",
    r"\b(сравнение|аналогия|метафора)\s+(точн(о|ая)|верн(о|ая)|в точку)\b",
    r"\b(сравнение|аналогия|метафора)\s+(зашл[ао]|попал[ао]\s+в\s+точку|работает)\b",
    r"\b(сравнение про казино)\b",
]
_POST_RHETORIC_RE = re.compile("|".join(_POST_RHETORIC_PATTERNS), re.IGNORECASE)


def detect_post_rhetoric_reaction(text: str) -> bool:
    """
    True if comment reacts to post wording/metaphor itself
    instead of adding an independent viewpoint.
    """
    if not text or not text.strip():
        return False
    return bool(_POST_RHETORIC_RE.search(text))


def strip_post_rhetoric_reaction(text: str) -> str:
    """
    Removes sentence-level rhetoric reactions to the post wording/metaphor.
    Keeps the author's own viewpoint while dropping "comparison is spot on" style phrasing.
    """
    if not text or not text.strip():
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [s for s in sentences if s.strip() and not detect_post_rhetoric_reaction(s)]
    if not kept:
        return text.strip()
    return " ".join(kept).strip()


def detect_personal_stance(
    text: str,
    expected_language: Optional[str] = None,
) -> bool:
    """
    True if text contains explicit personal stance markers.
    We require this to keep comments authored from a real POV.
    """
    if not text or not text.strip():
        return False
    t = text.lower()

    en_patterns = [
        r"\bi think\b",
        r"\bi feel\b",
        r"\bi believe\b",
        r"\bfor me\b",
        r"\bin my view\b",
        r"\bin my experience\b",
        r"\bfrom my side\b",
        r"\bi've seen\b",
    ]
    ru_patterns = [
        r"\bя думаю\b",
        r"\bмне кажется\b",
        r"\bна мой взгляд\b",
        r"\bпо моему опыту\b",
        r"\bпо моему мнению\b",
        r"\bя вижу\b",
        r"\bдля меня\b",
    ]

    lang = (expected_language or "").strip().lower()
    patterns = en_patterns if lang == "english" else ru_patterns if lang == "russian" else (en_patterns + ru_patterns)
    return any(re.search(p, t) for p in patterns)
