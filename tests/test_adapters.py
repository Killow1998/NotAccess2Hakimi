"""Tests for adapter request/response transformations."""

import json

from hakimi_proxy.adapters.aistudio import AIStudioAdapter
from hakimi_proxy.adapters.antigravity import (
    AntigravityAdapter,
    _gemini_to_openai,
    _openai_to_gemini,
)
from hakimi_proxy.config import AIStudioCredential, AntigravityCredential
from hakimi_proxy.pool import PooledCredential


def _make_ai_cred() -> PooledCredential:
    return PooledCredential(credential=AIStudioCredential(id="test", api_key="AIzaSy-test"))


def _make_ag_cred() -> PooledCredential:
    return PooledCredential(
        credential=AntigravityCredential(
            id="test", client_id="cid", client_secret="cs", refresh_token="rt"
        )
    )


# --- AI Studio adapter ---

def test_aistudio_supports_model():
    adapter = AIStudioAdapter()
    assert adapter.supports_model("gemini-3.7-flash")
    assert adapter.supports_model("gemini-2.0-flash")
    assert not adapter.supports_model("gpt-4")


def test_aistudio_extract_usage():
    adapter = AIStudioAdapter()
    body = {"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
    usage = adapter.extract_usage(body)
    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 50


def test_aistudio_transform_stream_line_passthrough():
    adapter = AIStudioAdapter()
    chunk = {"choices": [{"delta": {"content": "hello"}}]}
    line = f"data: {json.dumps(chunk)}"
    transformed, usage = adapter.transform_stream_line(line)
    assert transformed == line
    assert usage is None


def test_aistudio_transform_stream_line_with_usage():
    adapter = AIStudioAdapter()
    chunk = {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    line = f"data: {json.dumps(chunk)}"
    transformed, usage = adapter.transform_stream_line(line)
    assert transformed == line
    assert usage is not None
    assert usage["prompt_tokens"] == 10


def test_aistudio_transform_stream_done():
    adapter = AIStudioAdapter()
    transformed, usage = adapter.transform_stream_line("data: [DONE]")
    assert transformed == "data: [DONE]"
    assert usage is None


def test_aistudio_transform_non_data_line():
    adapter = AIStudioAdapter()
    transformed, usage = adapter.transform_stream_line(": comment")
    assert transformed is None
    assert usage is None


# --- Antigravity adapter ---

def test_antigravity_supports_model():
    adapter = AntigravityAdapter()
    assert adapter.supports_model("gemini-3.7-flash")
    assert adapter.supports_model("gemini-2.5-pro")
    assert not adapter.supports_model("gpt-4")


def test_openai_to_gemini_basic():
    """System message goes to systemInstruction; user/assistant to contents."""
    body = {
        "model": "gemini-3.7-flash",
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
        ],
    }
    result = _openai_to_gemini(body)
    assert "systemInstruction" in result
    assert result["systemInstruction"]["parts"][0]["text"] == "You are helpful."
    assert len(result["contents"]) == 3
    assert result["contents"][0]["role"] == "user"
    assert result["contents"][1]["role"] == "model"
    assert result["contents"][2]["role"] == "user"


def test_openai_to_gemini_with_gen_config():
    """Generation config fields are mapped."""
    body = {
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.7,
        "max_tokens": 100,
        "top_p": 0.9,
    }
    result = _openai_to_gemini(body)
    gc = result["generationConfig"]
    assert gc["temperature"] == 0.7
    assert gc["maxOutputTokens"] == 100
    assert gc["topP"] == 0.9


def test_openai_to_gemini_no_system():
    """Without system message, systemInstruction is absent."""
    body = {
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hi"}],
    }
    result = _openai_to_gemini(body)
    assert "systemInstruction" not in result
    assert len(result["contents"]) == 1


def test_gemini_to_openai_basic():
    """Gemini response converts to OpenAI format."""
    gemini_body = {
        "candidates": [
            {
                "content": {"parts": [{"text": "Hello!"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 5,
            "totalTokenCount": 15,
        },
    }
    result = _gemini_to_openai(gemini_body, "gemini-3.7-flash")
    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"]["content"] == "Hello!"
    assert result["choices"][0]["finish_reason"] == "stop"
    assert result["usage"]["prompt_tokens"] == 10
    assert result["usage"]["completion_tokens"] == 5
    assert result["model"] == "gemini-3.7-flash"


def test_gemini_to_openai_max_tokens():
    """finishReason MAX_TOKENS maps to 'length'."""
    gemini_body = {
        "candidates": [
            {"content": {"parts": [{"text": "..."}]}, "finishReason": "MAX_TOKENS"}
        ],
        "usageMetadata": {},
    }
    result = _gemini_to_openai(gemini_body, "gemini-3.7-flash")
    assert result["choices"][0]["finish_reason"] == "length"


def test_antigravity_transform_stream_line():
    """Cloud Code SSE data line transforms to OpenAI SSE chunk."""
    adapter = AntigravityAdapter()
    gemini_data = {
        "response": {
            "candidates": [{"content": {"parts": [{"text": "Hello"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2},
        }
    }
    line = f"data: {json.dumps(gemini_data)}"
    transformed, usage = adapter.transform_stream_line(line)
    assert transformed is not None
    chunk = json.loads(transformed)
    assert chunk["object"] == "chat.completion.chunk"
    assert chunk["choices"][0]["delta"]["content"] == "Hello"
    assert usage is not None
    assert usage["prompt_tokens"] == 10


def test_antigravity_extract_usage():
    adapter = AntigravityAdapter()
    body = {
        "response": {
            "usageMetadata": {
                "promptTokenCount": 100,
                "candidatesTokenCount": 50,
                "totalTokenCount": 150,
            }
        }
    }
    usage = adapter.extract_usage(body)
    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 50
    assert usage["total_tokens"] == 150
