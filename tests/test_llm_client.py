import pytest

from app.llm_client import generate_text, has_api_key, strip_code_fences


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_has_api_key_false_when_unset():
    assert has_api_key() is False


def test_has_api_key_true_when_set(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    assert has_api_key() is True


def test_generate_text_returns_none_without_key():
    assert generate_text("irrelevant prompt") is None


def test_strip_code_fences_removes_leading_and_trailing():
    raw = "```python\ndef compute(inputs):\n    return 1\n```"
    assert strip_code_fences(raw) == "def compute(inputs):\n    return 1"


def test_strip_code_fences_leaves_plain_code_untouched():
    raw = "def compute(inputs):\n    return 1"
    assert strip_code_fences(raw) == raw


def test_strip_code_fences_does_not_touch_mid_content_backticks():
    # a fence only strips at the true start/end of the string, never mid-content
    raw = "def compute(inputs):\n    # not ```a real fence```\n    return 1"
    assert strip_code_fences(raw) == raw
