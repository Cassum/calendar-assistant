from __future__ import annotations

from datetime import datetime, timezone

from aiogram.exceptions import TelegramForbiddenError
from tzlocal import get_localzone

from calendar_assistant.db import repo
from calendar_assistant.db.repo import SessionFactory
from calendar_assistant.logs import get_logger

log = get_logger(__name__)


def reminder_text(title: str, fire_at: datetime) -> str:
    local = fire_at.astimezone(get_localzone()).strftime("%d.%m.%Y %H:%M")
    return f"Напоминание: «{title}» — {local}."


async def send_due_reminders(
    bot,
    factory: SessionFactory,
    *,
    max_attempts: int,
    now: datetime | None = None,
) -> int:
    """Один тик рассылки: всё pending с fire_at <= now. Возвращает число обработанных.

    Сбой → pending и повтор на следующем тике; после max_attempts → failed;
    403 (бот заблокирован) → сразу failed.
    """
    now = now or datetime.now(timezone.utc)
    due = await repo.due_reminders(factory, now)
    for r in due:
        try:
            await bot.send_message(r.chat_id, reminder_text(r.title, r.fire_at))
        except TelegramForbiddenError as e:
            await repo.mark_reminder_failed(factory, r.reminder_id)
            log.warning(
                "reminders.forbidden",
                reminder_id=r.reminder_id,
                chat_id=r.chat_id,
                error=str(e),
            )
            continue
        except Exception as e:
            attempts = await repo.bump_attempt(factory, r.reminder_id)
            if attempts >= max_attempts:
                await repo.mark_reminder_failed(factory, r.reminder_id)
                log.error(
                    "reminders.failed",
                    reminder_id=r.reminder_id,
                    attempts=attempts,
                    error=str(e),
                )
            else:
                log.warning(
                    "reminders.send_error",
                    reminder_id=r.reminder_id,
                    attempts=attempts,
                    error=str(e),
                )
            continue
        await repo.mark_reminder_sent(factory, r.reminder_id)
        log.info("reminders.sent", reminder_id=r.reminder_id, chat_id=r.chat_id)
    return len(due)
