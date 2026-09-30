from __future__ import annotations

from datetime import datetime
from typing import TypedDict


class GraphState(TypedDict, total=False):
    """Состояние графа MVP: вход → решение → слоты → событие → ответ."""

    message: str
    chat_id: int
    # решение Сменного слоя (после политики)
    node: str
    reason: str
    layer: str
    confidence: float | None
    # слоты
    title: str | None
    starts_at: datetime | None  # aware UTC, детерминированный слой (dates.py)
    reminder_offset_minutes: int | None
    # результат create_event
    event_id: int
    fire_at: datetime
    # исходящая реплика (LLM или Шаблонная)
    reply: str
