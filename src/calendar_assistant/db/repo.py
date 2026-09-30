from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from calendar_assistant.db.models import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SENT,
    Event,
    Reminder,
    User,
)

SessionFactory = async_sessionmaker[AsyncSession]


def to_utc(dt: datetime) -> datetime:
    """Нормализация на вход в БД: naive считаем UTC, aware — приводим к UTC.

    SQLite кладёт aware-время со срезанным offset (без конвертации), поэтому
    на входе обязан быть именно UTC — тогда хранимое naive читается как UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def as_utc(dt: datetime) -> datetime:
    """Нормализация на выходе из БД: naive надеваем UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class DueReminder:
    reminder_id: int
    event_id: int
    chat_id: int
    title: str
    fire_at: datetime
    attempts: int


async def upsert_user(
    factory: SessionFactory,
    telegram_id: int,
    default_reminder_offset_minutes: int | None = None,
) -> None:
    async with factory() as session:
        existing = await session.get(User, telegram_id)
        if existing is None:
            session.add(
                User(
                    telegram_id=telegram_id,
                    default_reminder_offset_minutes=default_reminder_offset_minutes,
                )
            )
        elif default_reminder_offset_minutes is not None and (
            existing.default_reminder_offset_minutes is None
        ):
            existing.default_reminder_offset_minutes = default_reminder_offset_minutes
        await session.commit()


async def create_event(
    factory: SessionFactory,
    *,
    owner_telegram_id: int,
    title: str,
    starts_at: datetime,
    reminder_offset_minutes: int | None = None,
) -> int:
    async with factory() as session:
        event = Event(
            owner_telegram_id=owner_telegram_id,
            title=title,
            starts_at=to_utc(starts_at),
            reminder_offset_minutes=reminder_offset_minutes,
        )
        session.add(event)
        await session.commit()
        return event.id


async def add_reminder(
    factory: SessionFactory,
    *,
    event_id: int,
    fire_at: datetime,
) -> int:
    async with factory() as session:
        reminder = Reminder(event_id=event_id, fire_at=to_utc(fire_at))
        session.add(reminder)
        await session.commit()
        return reminder.id


async def due_reminders(factory: SessionFactory, now: datetime) -> list[DueReminder]:
    """Все pending, у которых fire_at <= now — просроченные досылаются автоматически."""
    stmt = (
        select(Reminder, Event)
        .join(Event, Reminder.event_id == Event.id)
        .where(Reminder.status == STATUS_PENDING, Reminder.fire_at <= to_utc(now))
        .order_by(Reminder.fire_at, Reminder.id)
    )
    async with factory() as session:
        rows = (await session.execute(stmt)).all()
        return [
            DueReminder(
                reminder_id=reminder.id,
                event_id=event.id,
                chat_id=event.owner_telegram_id,
                title=event.title,
                fire_at=as_utc(reminder.fire_at),
                attempts=reminder.attempts,
            )
            for reminder, event in rows
        ]


async def mark_reminder_sent(factory: SessionFactory, reminder_id: int) -> None:
    async with factory() as session:
        await session.execute(
            update(Reminder)
            .where(Reminder.id == reminder_id, Reminder.status == STATUS_PENDING)
            .values(status=STATUS_SENT)
        )
        await session.commit()


async def mark_reminder_failed(factory: SessionFactory, reminder_id: int) -> None:
    async with factory() as session:
        await session.execute(
            update(Reminder).where(Reminder.id == reminder_id).values(status=STATUS_FAILED)
        )
        await session.commit()


async def bump_attempt(factory: SessionFactory, reminder_id: int) -> int:
    """attempts += 1, возвращает новое значение (для решения pending → failed)."""
    async with factory() as session:
        result = await session.execute(
            update(Reminder)
            .where(Reminder.id == reminder_id)
            .values(attempts=Reminder.attempts + 1)
            .returning(Reminder.attempts)
        )
        await session.commit()
        return int(result.scalar_one())
