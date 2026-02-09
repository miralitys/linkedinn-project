# agents/utils.py
from __future__ import annotations

import json
import re


def extract_json(text: str) -> dict | list:
    """Extract first JSON object or array from text (handles markdown code blocks)."""
    text = text.strip()
    # Remove markdown code block
    for pattern in (r"```(?:json)?\s*([\s\S]*?)```", r"```\s*([\s\S]*?)```"):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            text = m.group(1).strip()
            break
    # Find first { or [
    start_obj = text.find("{")
    start_arr = text.find("[")
    if start_obj >= 0 and (start_arr < 0 or start_obj < start_arr):
        depth = 0
        for i in range(start_obj, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start_obj : i + 1])
    if start_arr >= 0:
        depth = 0
        for i in range(start_arr, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start_arr : i + 1])
    return json.loads(text)
