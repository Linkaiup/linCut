"""Shared MiniMax text completion helper."""
import json

from backend.core.settings import MINIMAX_BASE_URL, http


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def complete(messages: list, *, max_tokens: int = 2000, temperature: float = 0.7) -> str:
    resp = http.post(
        f"{MINIMAX_BASE_URL}/text/chatcompletion_v2",
        json={
            "model": "MiniMax-M1",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    )
    resp.raise_for_status()
    data = resp.json()

    base = data.get("base_resp", {})
    if base.get("status_code", 0) != 0:
        raise RuntimeError(
            f"MiniMax API error: {base.get('status_msg', 'unknown')} (code {base.get('status_code')})"
        )

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("MiniMax API returned empty response")
    return content


def parse_json_object(raw: str) -> dict:
    return json.loads(strip_code_fences(raw))


def unwrap_payload(data: dict, list_key: str = "segments") -> dict:
    if isinstance(data.get(list_key), list):
        return data
    for key in ("blueprint", "plan", "result", "data", "outline"):
        nested = data.get(key)
        if isinstance(nested, dict) and isinstance(nested.get(list_key), list):
            return nested
    return data
