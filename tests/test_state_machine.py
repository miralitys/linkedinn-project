# tests/test_state_machine.py
import pytest
from app.models import PersonStatus
from app.state_machine import can_transition, may_send_dm, suggested_next_status


def test_can_transition_new_to_connected():
    assert can_transition(PersonStatus.NEW.value, PersonStatus.CONNECTED.value) is True


def test_can_transition_new_to_warm_not_allowed():
    assert can_transition(PersonStatus.NEW.value, PersonStatus.WARM.value) is False


def test_can_transition_connected_to_engaged():
    assert can_transition(PersonStatus.CONNECTED.value, PersonStatus.ENGAGED.value) is True


def test_can_transition_warm_to_dm_sent():
    assert can_transition(PersonStatus.WARM.value, PersonStatus.DM_SENT.value) is True


def test_suggested_next_status_new():
    assert PersonStatus.CONNECTED.value in suggested_next_status(PersonStatus.NEW.value)


def test_suggested_next_status_won():
    assert suggested_next_status(PersonStatus.WON.value) == []


def test_may_send_dm_warm_allowed():
    allowed, reason = may_send_dm(PersonStatus.WARM.value, has_warm_context=True, first_month_strict=True)
    assert allowed is True


def test_may_send_dm_new_strict_not_allowed():
    allowed, reason = may_send_dm(PersonStatus.NEW.value, has_warm_context=False, first_month_strict=True)
    assert allowed is False
    assert "cold" in reason.lower() or "прогрев" in reason.lower()
