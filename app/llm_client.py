"""Shared LLM client — Gemini-backed.

Every call site (Stage 3's proof generation, Layer 3b's adversarial suite,
the Q&A agent) goes through `generate_text()`, which treats a missing key,
a missing SDK, or any API failure identically: return `None` and let the
caller fall through to its own honest "skipped, not faked" path. Nothing
here ever raises past this boundary — callers only ever see a string or
`None`.
"""
from __future__ import annotations

import os
import re
from typing import Optional

DEFAULT_MODEL = "gemini-2.5-flash"

_LEADING_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n")
_TRAILING_FENCE = re.compile(r"\n```\s*$")


def strip_code_fences(text: str) -> str:
    """Gemini wraps generated code in markdown fences even when told not
    to, more often than not — strip a fence only at the true start/end of
    the string (never mid-content) so callers get bare source that
    parses, rather than every generated proof failing on a stray ```."""
    stripped = text.strip()
    stripped = _LEADING_FENCE.sub("", stripped)
    stripped = _TRAILING_FENCE.sub("", stripped)
    return stripped.strip()


def has_api_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def generate_text(prompt: str, max_output_tokens: int = 400) -> Optional[str]:
    if not has_api_key():
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    try:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=max_output_tokens),
        )
        text = response.text
        return text if text else None  # empty/refused response is still "no answer", not a string
    except Exception:
        return None
