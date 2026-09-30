from __future__ import annotations

from calendar_assistant.decision import (
    KNOWN_NODES,
    NODE_UNRECOGNIZED,
    Decision,
    JsonCompleter,
)
from calendar_assistant.logs import get_logger

log = get_logger(__name__)

ROUTE_SCHEMA: dict = {
    "name": "route_decision",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "node": {"type": "string", "enum": sorted(KNOWN_NODES)},
            "reason": {"type": "string"},
        },
        "required": ["node", "reason"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = (
    "Ты — роутер Telegram-бота, который создаёт события календаря и присылает напоминания.\n"
    "Определи намерение сообщения пользователя:\n"
    "- create_event: пользователь хочет создать событие/встречу/напоминание "
    "(даже если деталей пока не хватает);\n"
    "- unrecognized: всё остальное — вопросы, разговор, мусор, просьбы, "
    "не связанные с созданием события.\n"
    "При сомнении выбирай unrecognized."
)


class LLMDecisionLayer:
    """Роутер через облачную LLM: enum-метки json_schema, confidence — честное None."""

    def __init__(self, completer: JsonCompleter):
        self._completer = completer

    async def route(self, message: str) -> Decision:
        try:
            data = await self._completer.complete_json(
                system=SYSTEM_PROMPT, user=message, schema=ROUTE_SCHEMA
            )
        except Exception as e:
            log.warning("route.llm_error", error=str(e))
            return Decision(NODE_UNRECOGNIZED, None, f"ошибка LLM-роутера: {e}", "llm")
        if not isinstance(data, dict):
            return Decision(NODE_UNRECOGNIZED, None, f"не dict: {data!r}", "llm")
        node = data.get("node")
        if node not in KNOWN_NODES:
            return Decision(NODE_UNRECOGNIZED, None, f"метка вне enum: {node!r}", "llm")
        return Decision(str(node), None, str(data.get("reason", "")), "llm")
