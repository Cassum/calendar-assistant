from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from sqlalchemy import select

from calendar_assistant.calendar_tools import SqliteCalendarTools
from calendar_assistant.db.base import Base
from calendar_assistant.db.models import Reminder
from calendar_assistant.db.repo import SessionFactory
from calendar_assistant.db.session import create_engine_and_sessions
from calendar_assistant.reminders import send_due_reminders

NOW = datetime(2026, 10, 1, 14, 45, tzinfo=timezone.utc)


class FakeBot:
    def __init__(self, *, fail_with: Exception | None = None):
        self.sent: list[tuple[int, str]] = []
        self._fail_with = fail_with
        self.calls = 0

    async def send_message(self, chat_id: int, text: str) -> None:
        self.calls += 1
        if self._fail_with is not None:
            raise self._fail_with
        self.sent.append((chat_id, text))


async def _db(tmp_path) -> tuple:
    engine, factory = create_engine_and_sessions(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _make_due(factory: SessionFactory, *, fire_at: datetime) -> None:
    tools = SqliteCalendarTools(factory, default_offset_minutes=0)
    made = await tools.create_event_with_reminder(
        telegram_id=777,
        title="Дедлайн",
        starts_at=fire_at,
        reminder_offset_minutes=0,
    )
    assert made.fire_at == fire_at


async def _statuses(factory: SessionFactory) -> list[tuple[str, int]]:
    async with factory() as session:
        rows = (await session.execute(select(Reminder.status, Reminder.attempts))).all()
        return sorted((status, attempts) for status, attempts in rows)


async def test_due_reminder_is_sent(tmp_path):
    engine, factory = await _db(tmp_path)
    await _make_due(factory, fire_at=NOW - timedelta(minutes=5))
    await _make_due(factory, fire_at=NOW + timedelta(hours=1))  # ещё не время

    bot = FakeBot()
    handled = await send_due_reminders(bot, factory, max_attempts=3, now=NOW)
    assert handled == 1
    assert len(bot.sent) == 1
    assert bot.sent[0][0] == 777
    assert "Дедлайн" in bot.sent[0][1]
    assert await _statuses(factory) == [("pending", 0), ("sent", 0)]
    await engine.dispose()


async def test_send_error_retries_then_failed(tmp_path):
    engine, factory = await _db(tmp_path)
    await _make_due(factory, fire_at=NOW - timedelta(minutes=5))

    bot = FakeBot(fail_with=RuntimeError("net down"))
    for i in range(1, 4):
        await send_due_reminders(bot, factory, max_attempts=3, now=NOW)
        expected = ("failed", 3) if i == 3 else ("pending", i)
        assert await _statuses(factory) == [expected]
    assert bot.calls == 3
    await engine.dispose()


async def test_forbidden_fails_immediately(tmp_path):
    engine, factory = await _db(tmp_path)
    await _make_due(factory, fire_at=NOW - timedelta(minutes=5))

    forbidden = TelegramForbiddenError(
        method=SendMessage(chat_id=777, text="x"),
        message="Forbidden: bot was blocked by the user",
    )
    bot = FakeBot(fail_with=forbidden)
    await send_due_reminders(bot, factory, max_attempts=3, now=NOW)

    assert await _statuses(factory) == [("failed", 0)]
    await engine.dispose()
