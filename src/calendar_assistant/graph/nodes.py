from __future__ import annotations

from typing import Protocol

from langgraph.graph import END, START, StateGraph
from tzlocal import get_localzone

from calendar_assistant.calendar_tools import CalendarTools
from calendar_assistant.dates import extract_event_datetime
from calendar_assistant.decision import (
    KNOWN_NODES,
    NODE_CREATE_EVENT,
    NODE_UNRECOGNIZED,
    Decision,
    DecisionLayer,
    apply_policy,
)
from calendar_assistant.graph.state import GraphState
from calendar_assistant.logs import get_logger

log = get_logger(__name__)

EXAMPLE = "Встреча с Иваном завтра в 15:00, напомни за полчаса"
TEMPLATE_UNRECOGNIZED = f'Не понял запрос. Например: «{EXAMPLE}»'
TEMPLATE_MISSING_SLOTS = f'Не хватает даты/времени. Например: «{EXAMPLE}»'
TEMPLATE_SAVE_ERROR = "Не получилось сохранить событие. Попробуй ещё раз."

SLOT_SCHEMA: dict = {
    "name": "event_slots",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "title": {"type": ["string", "null"]},
            "reminder_offset_minutes": {"type": ["integer", "null"]},
        },
        "required": ["title", "reminder_offset_minutes"],
        "additionalProperties": False,
    },
}

SLOTS_SYSTEM = (
    "Ты извлекаешь слоты события календаря из сообщения пользователя.\n"
    "Верни JSON:\n"
    "- title: краткое название события (2-6 слов), null, если названия нет;\n"
    "- reminder_offset_minutes: смещение напоминания от начала события В МИНУТАХ, "
    "только из явной формулировки «за N до»/«напомни за N» "
    "(«за полчаса» → 30, «за 10 минут» → 10, «за день» → 1440); "
    "иначе null. Отрицательных чисел здесь не бывает.\n"
    "Дата и время тебя НЕ интересуют — их извлекает код: "
    "«через 10 минут», «через 3 минуты», «через 2 часа» — это ВРЕМЯ СОБЫТИЯ, "
    "а не сдвиг напоминания; в reminder_offset_minutes класть null."
)


class Llm(Protocol):
    """JSON по схеме: всё, что графу нужно от llm.LLMClient."""

    async def complete_json(self, *, system: str, user: str, schema: dict) -> dict: ...


def _fmt_local(dt) -> str:
    return dt.astimezone(get_localzone()).strftime("%d.%m.%Y %H:%M")


def build_graph(
    *,
    decision_layer: DecisionLayer,
    llm: Llm,
    tools: CalendarTools,
    threshold: float,
    layer_name: str,
):
    """Собрать граф MVP: route → create_event → respond (Шаблонная реплика) + unrecognized."""

    async def route_node(state: GraphState) -> GraphState:
        try:
            decision = await decision_layer.route(state["message"])
        except Exception as e:
            log.warning("route.layer_error", error=str(e))
            decision = Decision(NODE_UNRECOGNIZED, None, f"ошибка слоя: {e}", layer_name)  # type: ignore[arg-type]
        decision = apply_policy(decision, threshold)
        log.info(
            "route.decided",
            node=decision.node,
            layer=decision.layer,
            confidence=decision.confidence,
            reason=decision.reason,
        )
        return {
            "node": decision.node,
            "reason": decision.reason,
            "layer": decision.layer,
            "confidence": decision.confidence,
        }

    async def create_event_node(state: GraphState) -> GraphState:
        message = state["message"]
        starts_at = extract_event_datetime(message)
        if starts_at is None:
            log.info("create_event.missing_datetime", message=message)
            return {"reply": TEMPLATE_MISSING_SLOTS}
        title: str | None = None
        offset: int | None = None
        try:
            slots = await llm.complete_json(system=SLOTS_SYSTEM, user=message, schema=SLOT_SCHEMA)
            title = slots.get("title") or None
            offset = slots.get("reminder_offset_minutes")
        except Exception as e:
            log.warning("create_event.slots_llm_error", error=str(e))
        try:
            created = await tools.create_event_with_reminder(
                telegram_id=state["chat_id"],
                title=title or "",
                starts_at=starts_at,
                reminder_offset_minutes=offset,
            )
        except Exception as e:
            log.error("create_event.save_error", error=str(e))
            return {"reply": TEMPLATE_SAVE_ERROR}
        log.info(
            "create_event.created",
            event_id=created.event_id,
            reminder_id=created.reminder_id,
            title=created.title,
            starts_at=created.fire_at,
            offset_minutes=created.offset_minutes,
        )
        return {
            "title": created.title,
            "starts_at": starts_at,
            "reminder_offset_minutes": created.offset_minutes,
            "event_id": created.event_id,
            "fire_at": created.fire_at,
        }

    def respond_node(state: GraphState) -> GraphState:
        offset = state["reminder_offset_minutes"]
        title = state["title"]
        starts_local = _fmt_local(state["starts_at"])
        fire_local = _fmt_local(state["fire_at"])
        reply = f"Создал: «{title}» — {starts_local}."
        if offset:
            reply += f" Напомню за {offset} минут ({fire_local})."
        return {
            "reply": reply
        }

    async def unrecognized_node(state: GraphState) -> GraphState:
        return {"reply": TEMPLATE_UNRECOGNIZED}

    def after_route(state: GraphState) -> str:
        node = state.get("node")
        return node if node in KNOWN_NODES else NODE_UNRECOGNIZED

    def after_create(state: GraphState) -> str:
        return "respond" if state.get("fire_at") else END

    g: StateGraph = StateGraph(GraphState)
    g.add_node("route", route_node)
    g.add_node("create_event", create_event_node)
    g.add_node("respond", respond_node)
    g.add_node("unrecognized", unrecognized_node)
    g.add_edge(START, "route")
    g.add_conditional_edges(
        "route",
        after_route,
        {NODE_CREATE_EVENT: "create_event", NODE_UNRECOGNIZED: "unrecognized"},
    )
    g.add_conditional_edges("create_event", after_create, {"respond": "respond", END: END})
    g.add_edge("respond", END)
    g.add_edge("unrecognized", END)
    return g.compile()
