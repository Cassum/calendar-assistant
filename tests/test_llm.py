from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from openai import BadRequestError

from calendar_assistant.config import LLMConfig
from calendar_assistant.llm import LLMClient

SCHEMA = {"name": "event_slots", "strict": True, "schema": {"type": "object"}}


def _bad_request() -> BadRequestError:
    req = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")
    return BadRequestError(
        "response_format json_schema не поддерживается",
        response=httpx.Response(400, request=req),
        body=None,
    )


def _ok(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=None,
    )


class FakeCompletions:
    """chat.completions.create: ровно N отказов на json_schema, потом успех."""

    def __init__(self, schema_errors: int = 0):
        self.schema_errors = schema_errors
        self.calls: list[dict] = []

    async def create(self, **payload):
        self.calls.append(payload)
        if self.schema_errors and payload.get("response_format", {}).get("type") == "json_schema":
            self.schema_errors -= 1
            raise _bad_request()
        return _ok('{"title": "Встреча", "reminder_offset_minutes": 30}')


def _client(schema_errors: int = 0) -> tuple[LLMClient, FakeCompletions]:
    llm = LLMClient(LLMConfig(provider="ollama", model="qwen3:8b"))
    fake = FakeCompletions(schema_errors)
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return llm, fake


class TestReasoningEffort:
    async def test_ollama_thinking_disabled(self):
        """Ollama на /v1 сам включает thinking — без этого ответы дольше таймаута."""
        llm, fake = _client()
        await llm.complete_json(system="s", user="u", schema=SCHEMA)
        assert fake.calls[0]["extra_body"] == {"reasoning_effort": "none"}

    async def test_openai_provider_no_extra_body(self):
        llm = LLMClient(LLMConfig(model="m", api_key="k"))
        fake = FakeCompletions()
        llm._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
        await llm.complete_json(system="s", user="u", schema=SCHEMA)
        assert "extra_body" not in fake.calls[0]


class TestSchemaFallback:
    async def test_json_schema_rejected_falls_back_to_json_object(self):
        llm, fake = _client(schema_errors=1)
        out = await llm.complete_json(system="s", user="u", schema=SCHEMA)
        assert out["title"] == "Встреча"
        assert [c["response_format"]["type"] for c in fake.calls] == [
            "json_schema",
            "json_object",
        ]

    async def test_fallback_persists_for_next_calls(self):
        llm, fake = _client(schema_errors=1)
        await llm.complete_json(system="s", user="u", schema=SCHEMA)
        fake.calls.clear()
        await llm.complete_json(system="s", user="u", schema=SCHEMA)
        assert [c["response_format"]["type"] for c in fake.calls] == ["json_object"]

    async def test_plain_json_mode_error_reraises(self):
        llm, fake = _client()

        async def create(**payload):
            raise _bad_request()

        fake.create = create  # type: ignore[method-assign]
        with pytest.raises(BadRequestError):
            await llm.complete_json(system="s", user="u", schema=SCHEMA)

    async def test_json_schema_passthrough_when_supported(self):
        llm, fake = _client()
        await llm.complete_json(system="s", user="u", schema=SCHEMA)
        assert fake.calls[0]["response_format"] == {"type": "json_schema", "json_schema": SCHEMA}
        assert llm._schema_rejected is False
