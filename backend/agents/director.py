"""Director Agent: understands user intent and creates a shot-by-shot outline."""
import json
import logging
from backend.config import MINIMAX_BASE_URL, api_session

logger = logging.getLogger("lincut.director")


SYSTEM_PROMPT = """You are the Director of an AI film production team. Your job is to take the user's creative idea and break it down into a detailed shot-by-shot outline for a short video.

For each shot, provide:
1. shot_number: sequential number
2. duration: in seconds (total should match requested length)
3. visual_description: detailed description for AI video generation (style, camera angle, lighting, motion, subject)
4. narration: voiceover text for this shot (in English)
5. mood: emotional tone (e.g. "inspiring", "dramatic", "calm", "energetic")

Also provide:
- title: a short title for the video
- style: overall visual style (e.g. "cinematic sci-fi", "warm documentary", "minimal modern")
- total_duration: total video length in seconds

Respond ONLY with valid JSON. No markdown, no explanation. Example format:
{
  "title": "AI Writing Assistant",
  "style": "cinematic sci-fi with neon accents",
  "total_duration": 30,
  "shots": [
    {
      "shot_number": 1,
      "duration": 10,
      "visual_description": "A writer staring at a blank screen...",
      "narration": "Every great story starts with a blank page.",
      "mood": "contemplative"
    }
  ]
}"""


def _strip_markdown_fences(text: str) -> str:
    """Strip markdown code fences from LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def _call_llm(messages: list, max_tokens: int = 2000) -> str:
    """Call MiniMax LLM and return the content string."""
    url = f"{MINIMAX_BASE_URL}/text/chatcompletion_v2"
    payload = {
        "model": "MiniMax-M1",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }
    resp = api_session.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()

    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise RuntimeError(f"MiniMax API error: {base_resp.get('status_msg', 'unknown')} (code {base_resp.get('status_code')})")

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("MiniMax API returned empty response")
    return content


def _coerce_outline(data: dict) -> dict:
    """Unwrap nested LLM response shapes like {\"outline\": {...}}."""
    if isinstance(data.get("shots"), list):
        return data
    for key in ("outline", "video", "result", "data"):
        nested = data.get(key)
        if isinstance(nested, dict) and isinstance(nested.get("shots"), list):
            return nested
    return data


def _normalize_outline(outline: dict, user_prompt: str, duration: int) -> dict:
    """Fill missing top-level fields with sensible defaults."""
    if not outline.get("title"):
        outline["title"] = (user_prompt[:50].strip() or "Untitled Video")
    if not outline.get("style"):
        outline["style"] = "cinematic"
    if not outline.get("total_duration"):
        outline["total_duration"] = duration
    return outline


def _parse_outline(content: str, user_prompt: str, duration: int) -> dict:
    """Parse and validate Director JSON output."""
    outline = _coerce_outline(json.loads(_strip_markdown_fences(content)))
    shots = outline.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("Director response missing non-empty 'shots' array")

    outline = _normalize_outline(outline, user_prompt, duration)
    missing = [k for k in ("title", "style", "total_duration", "shots") if k not in outline]
    if missing:
        raise ValueError(f"Director response missing fields: {', '.join(missing)}")

    logger.debug("Director outline: title=%r, shots=%d", outline["title"], len(shots))
    return outline


def run(user_prompt: str, duration: int = 30, num_shots: int = 3) -> dict:
    """Generate a shot outline from user's creative prompt."""
    user_message = (
        f"Create a {duration}-second video with {num_shots} shots.\n"
        f"Theme: {user_prompt}\n"
        f"Each shot should be approximately {duration // num_shots} seconds."
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    content = _call_llm(messages)
    retry_hint = (
        "Your response was invalid. Return ONLY valid JSON with these required top-level keys: "
        "title (string), style (string), total_duration (number), shots (non-empty array). "
        "Each shot needs: shot_number, duration, visual_description, narration, mood. "
        "No markdown, no explanation."
    )
    try:
        return _parse_outline(content, user_prompt, duration)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Director parse failed (%s), retrying once", e)
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": retry_hint})
        content = _call_llm(messages)
        try:
            return _parse_outline(content, user_prompt, duration)
        except (json.JSONDecodeError, ValueError) as e2:
            raise RuntimeError(f"Director returned invalid outline: {e2}") from e2
