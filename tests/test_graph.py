from __future__ import annotations

from datetime import timedelta

from tzlocal import get_localzone

from calendar_assistant.calendar_tools import CreatedEvent
from calendar_assistant.decision import NODE_CREATE_EVENT, NODE_UNRECOGNIZED, Decision
from calendar_assistant.graph import (
    TEMPLATE_MISSING_SLOTS,
    TEMPLATE_SAVE_ERROR,
    TEMPLATE_UNRECOGNIZED,
    build_graph,
)

EXAMPLE = "Встреча с Иваном завтра в 15:00, напомни за полчаса"


class FakeLayer:
    def __init__(self, decision: Decision):
        self._decision = decision

    async def route(self, message: str) -> Decision:
        return self._decision


class FakeLlm:
    """Только complete_json: если respond-нода зовёт текст — упадёт AttributeError."""

    def __init__(self, *, slots=None, json_error=False):
        self._slots = slots if slots is not None else {"title": "Встреча с Иваном", "reminder_offset_minutes": 30}
        self._json_error = json_error

    async def complete_json(self, *, system: str, user: str, schema: dict) -> dict:
        if self._json_error:
            raise RuntimeError("json boom")
        return self._slots


class FakeTools:
    def __init__(self, *, fail=False):
        self.calls: list[dict] = []
        self._fail = fail

    async def create_event_with_reminder(
        self, *, telegram_id: int, title: str, starts_at, reminder_offset_minutes
    ) -> CreatedEvent:
        self.calls.append(
            {
                "telegram_id": telegram_id,
                "title": title,
                "starts_at": starts_at,
                "reminder_offset_minutes": reminder_offset_minutes,
            }
        )
        if self._fail:
            raise RuntimeError("db boom")
        offset = 0 if reminder_offset_minutes is None else reminder_offset_minutes
        stored = title.strip() or "Встреча"
        return CreatedEvent(
            event_id=1,
            reminder_id=2,
            fire_at=starts_at - timedelta(minutes=offset),
            offset_minutes=offset,
            title=stored,
        )


def _decision(node: str, confidence: float | None = None) -> Decision:
    return Decision(node, confidence, "fake", "llm")


def _graph(decision, llm=None, tools=None, threshold=0.5):
    return build_graph(
        decision_layer=FakeLayer(decision),
        llm=llm or FakeLlm(),
        tools=tools or FakeTools(),
        threshold=threshold,
        layer_name="llm",
    )


async def test_happy_path_creates_event_and_template_reply():
    graph = _graph(_decision(NODE_CREATE_EVENT))
    result = await graph.ainvoke({"message": EXAMPLE, "chat_id": 42})
    assert result["reply"].startswith("Создал: «Встреча с Иваном» —")
    assert "Напомню за 30 минут" in result["reply"]
    assert result["title"] == "Встреча с Иваном"
    assert result["event_id"] == 1
    assert result["fire_at"] == result["starts_at"] - timedelta(minutes=30)
    assert result["reminder_offset_minutes"] == 30
    assert result["starts_at"].astimezone(get_localzone()).hour == 15


async def test_happy_path_passes_chat_id_to_tools():
    tools = FakeTools()
    graph = _graph(_decision(NODE_CREATE_EVENT), tools=tools)
    await graph.ainvoke({"message": EXAMPLE, "chat_id": 42})
    assert tools.calls[0]["telegram_id"] == 42
    assert tools.calls[0]["reminder_offset_minutes"] == 30


async def test_missing_datetime_gets_template():
    tools = FakeTools()
    graph = _graph(_decision(NODE_CREATE_EVENT), tools=tools)
    result = await graph.ainvoke({"message": "привет как дела", "chat_id": 1})
    assert result["reply"] == TEMPLATE_MISSING_SLOTS
    assert tools.calls == []


async def test_unrecognized_gets_template():
    graph = _graph(_decision(NODE_UNRECOGNIZED))
    result = await graph.ainvoke({"message": "что такое второе начало термодинамики?", "chat_id": 1})
    assert result["reply"] == TEMPLATE_UNRECOGNIZED


async def test_low_confidence_routed_to_unrecognized():
    graph = _graph(_decision(NODE_CREATE_EVENT, confidence=0.3), threshold=0.5)
    result = await graph.ainvoke({"message": EXAMPLE, "chat_id": 1})
    assert result["reply"] == TEMPLATE_UNRECOGNIZED
    assert result["confidence"] == 0.3


async def test_slots_llm_error_still_creates_event():
    graph = _graph(_decision(NODE_CREATE_EVENT), llm=FakeLlm(json_error=True))
    result = await graph.ainvoke({"message": EXAMPLE, "chat_id": 1})
    assert result["title"] == "Встреча"  # fallback из кода
    assert result["event_id"] == 1
    assert result["reply"].startswith("Создал: «Встреча»")


async def test_respond_is_template_without_llm_call():
    """respond не зовёт LLM: у FakeLlm нет complete_text — вызов упал бы с AttributeError."""
    graph = _graph(_decision(NODE_CREATE_EVENT))
    result = await graph.ainvoke({"message": EXAMPLE, "chat_id": 1})
    assert result["reply"] == (
        f"Создал: «Встреча с Иваном» — "
        f"{result['starts_at'].astimezone(get_localzone()).strftime('%d.%m.%Y %H:%M')}. "
        f"Напомню за 30 минут ({result['fire_at'].astimezone(get_localzone()).strftime('%d.%m.%Y %H:%M')})."
    )


async def test_save_error_gets_template():
    graph = _graph(_decision(NODE_CREATE_EVENT), tools=FakeTools(fail=True))
    result = await graph.ainvoke({"message": EXAMPLE, "chat_id": 1})
    assert result["reply"] == TEMPLATE_SAVE_ERROR
