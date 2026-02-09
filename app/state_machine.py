# app/state_machine.py
"""State machine for Person status + guardrails (first month, DM only with reason)."""
from app.models import PersonStatus

# Valid transitions: from_status -> [to_status, ...]
ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    PersonStatus.NEW.value: [PersonStatus.CONNECTED.value],
    PersonStatus.CONNECTED.value: [PersonStatus.ENGAGED.value, PersonStatus.LOST.value],
    PersonStatus.ENGAGED.value: [PersonStatus.WARM.value, PersonStatus.LOST.value],
    PersonStatus.WARM.value: [PersonStatus.DM_SENT.value, PersonStatus.LOST.value],
    PersonStatus.DM_SENT.value: [PersonStatus.REPLIED.value, PersonStatus.LOST.value],
    PersonStatus.REPLIED.value: [PersonStatus.CALL_BOOKED.value, PersonStatus.DM_SENT.value, PersonStatus.LOST.value],
    PersonStatus.CALL_BOOKED.value: [PersonStatus.WON.value, PersonStatus.LOST.value],
    PersonStatus.WON.value: [],
    PersonStatus.LOST.value: [],
}


def can_transition(from_status: str, to_status: str) -> bool:
    allowed = ALLOWED_TRANSITIONS.get(from_status, [])
    return to_status in allowed


def suggested_next_status(current: str) -> list[str]:
    return ALLOWED_TRANSITIONS.get(current, [])


def is_cold_dm(status: str) -> bool:
    """DM to someone not yet Warm is 'cold' for guardrails."""
    return status in (PersonStatus.NEW.value, PersonStatus.CONNECTED.value)


def may_send_dm(
    current_status: str,
    has_warm_context: bool,
    first_month_strict: bool,
) -> tuple[bool, str]:
    """
    Guardrail: in first month almost no cold outreach; DM only after warm + reason.
    Returns (allowed, reason).
    """
    if current_status in (PersonStatus.WARM.value, PersonStatus.DM_SENT.value, PersonStatus.REPLIED.value):
        return True, "OK"
    if is_cold_dm(current_status):
        if first_month_strict:
            return False, "В первый месяц cold DM не рекомендуются. Сначала прогрев (Engaged → Warm)."
        if not has_warm_context:
            return False, "Нужен повод: лид-магнит, контекст из комментария или полезный материал."
    return False, "Переведите контакт в Warm перед отправкой DM."
