from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from calendar_assistant.calendar_tools import SqliteCalendarTools, _clamp_offset
from calendar_assistant.db.base import Base
from calendar_assistant.db.models import Event
from calendar_assistant.db.repo import SessionFactory
from calendar_assistant.db.session import create_engine_and_sessions

NOW = datetime(2026, 10, 1, 14, 45, tzinfo=timezone.utc)
STARTS_IN_2H = NOW + timedelta(hours=2)


class TestClampOffset:
    def test_negative_slot_dropped(self):
        """«через 10 минут» → слот -10: без сдвига, fire = начало события."""
        assert _clamp_offset(-10, STARTS_IN_2H, NOW) is None

    def test_zero_slot_dropped(self):
        assert _clamp_offset(0, STARTS_IN_2H, NOW) is None

    def test_none_slot_untouched(self):
        assert _clamp_offset(None, STARTS_IN_2H, NOW) is None

    def test_slot_with_fire_in_past_dropped(self):
        """Событие через 10 минут и слот 10 → fire = сейчас: напоминание сразу, отбрасываем."""
        starts = NOW + timedelta(minutes=10)
        assert _clamp_offset(10, starts, NOW) is None

    def test_valid_slot_kept(self):
        assert _clamp_offset(30, STARTS_IN_2H, NOW) == 30

    def test_naive_datetimes_do_not_crash(self):
        assert _clamp_offset(30, STARTS_IN_2H.replace(tzinfo=None), NOW.replace(tzinfo=None)) == 30


async def _db(tmp_path) -> tuple:
    engine, factory = create_engine_and_sessions(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _stored_offsets(factory: SessionFactory) -> list:
    async with factory() as session:
        rows = (await session.execute(select(Event.reminder_offset_minutes))).all()
        return [r[0] for r in rows]


class TestCreateEventWithReminderClamp:
    async def test_garbage_negative_slot_becomes_no_offset(self, tmp_path):
        engine, factory = await _db(tmp_path)
        tools = SqliteCalendarTools(factory, default_offset_minutes=0)
        made = await tools.create_event_with_reminder(
            telegram_id=777,
            title="Холодильник",
            starts_at=NOW + timedelta(minutes=3),
            reminder_offset_minutes=-3,
            now=NOW,
        )
        assert made.offset_minutes == 0
        assert made.fire_at == NOW + timedelta(minutes=3)
        assert await _stored_offsets(factory) == [None]
        await engine.dispose()

    async def test_past_fire_slot_becomes_no_offset(self, tmp_path):
        engine, factory = await _db(tmp_path)
        tools = SqliteCalendarTools(factory, default_offset_minutes=0)
        made = await tools.create_event_with_reminder(
            telegram_id=777,
            title="Пельмени",
            starts_at=NOW + timedelta(minutes=10),
            reminder_offset_minutes=10,
            now=NOW,
        )
        assert made.offset_minutes == 0
        assert made.fire_at == NOW + timedelta(minutes=10)
        assert await _stored_offsets(factory) == [None]
        await engine.dispose()

    async def test_valid_slot_untouched(self, tmp_path):
        engine, factory = await _db(tmp_path)
        tools = SqliteCalendarTools(factory, default_offset_minutes=0)
        made = await tools.create_event_with_reminder(
            telegram_id=777,
            title="Встреча",
            starts_at=STARTS_IN_2H,
            reminder_offset_minutes=30,
            now=NOW,
        )
        assert made.offset_minutes == 30
        assert made.fire_at == STARTS_IN_2H - timedelta(minutes=30)
        assert await _stored_offsets(factory) == [30]
        await engine.dispose()
