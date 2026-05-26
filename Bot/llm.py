"""Single point of access for LLM calls.

Swap providers/models here without touching call sites. DeepSeek's API is
OpenAI-compatible, so we use the openai SDK pointed at api.deepseek.com.
"""

import os
from openai import OpenAI

_BASE_URL = "https://api.deepseek.com"
_MODEL = "deepseek-v4-flash"

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY not set. Add it to .env at the project root."
            )
        _client = OpenAI(api_key=api_key, base_url=_BASE_URL)
    return _client


def ask(prompt: str, max_tokens: int = 1000) -> str:
    """Single-turn user prompt → raw text response.

    Reasoning is disabled — the call sites in this project expect short,
    direct answers (STAY/CLICK n, JSON selectors, "N" or "all"). With
    thinking enabled, reasoning tokens eat the max_tokens budget before
    `content` emits, leaving an empty string.
    """
    response = _get_client().chat.completions.create(
        model=_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"thinking": {"type": "disabled"}},
    )
    return response.choices[0].message.content or ""
