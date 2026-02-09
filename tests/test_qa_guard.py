# tests/test_qa_guard.py
"""QA Guard heuristics: mock LLM and check structured output."""
import pytest
from agents.qa_guard import QAGuardAgent
from agents.utils import extract_json


def test_extract_json_from_markdown():
    text = '''Some text
```json
{"ok": true, "risks": {"hallucination": 0}, "fixes": []}
```
'''
    out = extract_json(text)
    assert out["ok"] is True
    assert out["risks"]["hallucination"] == 0


def test_extract_json_plain():
    out = extract_json('{"ok": false, "risks": {"spam_pattern": 80}, "fixes": ["Remove repetition"]}')
    assert out["ok"] is False
    assert out["risks"]["spam_pattern"] == 80
    assert "Remove repetition" in out["fixes"]


@pytest.mark.asyncio
async def test_qa_guard_returns_structure(monkeypatch):
    """Mock LLM to return fixed JSON; check agent returns ok, risks, fixes."""
    async def mock_chat(messages, **kwargs):
        return '{"ok": false, "risks": {"hallucination": 50, "tone_drift": 0, "spam_pattern": 0, "aggressiveness": 20, "policy_risk": 0}, "fixes": ["Check fact X"], "rewritten_text": null}'

    class MockClient:
        chat = mock_chat

    agent = QAGuardAgent(llm_client=MockClient())
    result = await agent.run({"context": "Professional tone", "content_type": "post", "text": "We increased revenue by 999%."})
    assert "ok" in result
    assert "risks" in result
    assert "fixes" in result
    assert result["ok"] is False
    assert result["risks"].get("hallucination", 0) >= 0
