from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from calendar_assistant.db import repo
from calendar_assistant.db.repo import SessionFactory

DEFAULT_TITLE_FALLBACK = "Встреча"


def _clamp_offset(slot: int | None, starts_at: datetime, now: datetime) -> int | None:
    """Слот сдвига от LLM: не доверяем дальше нуля.

    <= 0 («через N минут» вылилось в -N) → без сдвига; сдвиг в прошлом
    (fire = starts - slot уже наступил) → тоже без сдвига: напоминание в момент события.
    """
    if slot is None or slot <= 0:
        return None
    starts = starts_at if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc)
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    if starts - timedelta(minutes=slot) <= current:
        return None
    return slot


@dataclass(frozen=True)
class CreatedEvent:
    event_id: int
    reminder_id: int
    fire_at: datetime
    offset_minutes: int
    title: str


class CalendarTools(Protocol):
    """Шов, через который граф (нода create_event) трогает хранение."""

    async def create_event_with_reminder(
        self,
        *,
        telegram_id: int,
        title: str,
        starts_at: datetime,
        reminder_offset_minutes: int | None,
    ) -> CreatedEvent: ...


class SqliteCalendarTools:
    """Реализация поверх async-репозитория; offset слота ? дефолт из конфига."""

    def __init__(self, factory: SessionFactory, default_offset_minutes: int = 0):
        self._factory = factory
        self._default_offset_minutes = default_offset_minutes

    async def create_event_with_reminder(
        self,
        *,
        telegram_id: int,
        title: str,
        starts_at: datetime,
        reminder_offset_minutes: int | None,
        now: datetime | None = None,
    ) -> CreatedEvent:
        await repo.upsert_user(self._factory, telegram_id)
        slot = _clamp_offset(
            reminder_offset_minutes, starts_at, now or datetime.now(timezone.utc)
        )
        offset = self._default_offset_minutes if slot is None else slot
        stored_title = title.strip() or DEFAULT_TITLE_FALLBACK
        event_id = await repo.create_event(
            self._factory,
            owner_telegram_id=telegram_id,
            title=stored_title,
            starts_at=starts_at,
            reminder_offset_minutes=slot,
        )
        fire_at = starts_at - timedelta(minutes=offset)
        reminder_id = await repo.add_reminder(self._factory, event_id=event_id, fire_at=fire_at)
        return CreatedEvent(
            event_id=event_id,
            reminder_id=reminder_id,
            fire_at=fire_at,
            offset_minutes=offset,
            title=stored_title,
        )
