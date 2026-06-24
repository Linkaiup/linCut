"""Script Agent: refines the Director's outline into production-ready prompts."""
import json
from backend.config import MINIMAX_BASE_URL, api_session


SYSTEM_PROMPT = """You are the Scriptwriter of an AI film production team. You take the Director's shot outline and refine each shot into production-ready specifications.

For each shot, enhance:
1. video_prompt: a highly detailed, specific prompt optimized for AI video generation (Hailuo). Include: subject, action, camera movement, lighting, color palette, style. Be vivid and specific. Max 200 words.
2. narration: polished voiceover text, timed to fit the shot duration. Keep it concise and impactful.
3. subtitle: clean subtitle text (shorter than narration if needed)

Respond ONLY with valid JSON. Format:
{
  "shots": [
    {
      "shot_number": 1,
      "duration": 10,
      "video_prompt": "Detailed AI video generation prompt...",
      "narration": "Polished voiceover text...",
      "subtitle": "Clean subtitle text...",
      "mood": "inspiring"
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


def _call_llm(messages: list, max_tokens: int = 3000) -> str:
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


def run(outline: dict) -> dict:
    """Refine Director's outline into production-ready shot specifications."""
    user_message = (
        f"Video title: {outline['title']}\n"
        f"Visual style: {outline['style']}\n"
        f"Total duration: {outline['total_duration']}s\n\n"
        f"Director's outline:\n{json.dumps(outline['shots'], indent=2)}\n\n"
        f"Refine each shot with detailed video prompts optimized for AI video generation."
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    content = _call_llm(messages)
    try:
        result = json.loads(_strip_markdown_fences(content))
    except json.JSONDecodeError:
        # Retry once with explicit JSON instruction
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": "Your response was not valid JSON. Please return ONLY valid JSON with no markdown or extra text."})
        content = _call_llm(messages)
        result = json.loads(_strip_markdown_fences(content))

    # Carry over metadata from outline
    result["title"] = outline["title"]
    result["style"] = outline["style"]
    result["total_duration"] = outline["total_duration"]
    return result
