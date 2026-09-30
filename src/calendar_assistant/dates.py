from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from dateparser.search import search_dates
from tzlocal import get_localzone

# «за N единиц» / «полчаса» — это сдвиги напоминаний, а не дата события
_OFFSET_TEXT_RE = re.compile(
    r"^(?:за\s+)?(?:"
    r"\d+\s*(?:минут\w*|мин\b|час\w*|секунд\w*|сек\b|дн\w*|недел\w*|мес\w*)"
    r"|полчаса|сутки"
    r")$",
    re.IGNORECASE,
)
# «в 15:00» / «15:00» без даты: dateparser с PREFER_DATES_FROM=future на
# прошедшем времени отдаёт мусор (1 сентября) — дату собираем сами
_TIME_ONLY_RE = re.compile(r"^(?:в\s+)?(\d{1,2}:\d{2})$", re.IGNORECASE)

# «в 14 часов» — время, а не длительность: dateparser иначе даёт «база +14ч»
_CLOCK_RE = re.compile(r"\bв\s+(\d{1,2})\s*час(?:ов|а)?\b", re.IGNORECASE)
# «в 10 утра» / «в 9 вечера» — час в HH:00, вечер/ночь со сдвигом на 12
_MERIDIAN_RE = re.compile(r"\bв\s+(\d{1,2})\s*(утра|дня|вечера|ночи)\b", re.IGNORECASE)


def _normalize_times(text: str) -> str:
    text = _CLOCK_RE.sub(lambda m: f"в {int(m.group(1)):02d}:00", text)

    def _meridian(m: re.Match) -> str:
        hour = int(m.group(1))
        if m.group(2).lower() in ("вечера", "ночи") and hour < 12:
            hour += 12
        return f"в {hour:02d}:00"

    return _MERIDIAN_RE.sub(_meridian, text)


def _local_naive_base(now: datetime | None) -> datetime:
    local_tz = get_localzone()
    if now is None:
        return datetime.now(tz=local_tz).replace(tzinfo=None)
    if now.tzinfo is not None:
        return now.astimezone(local_tz).replace(tzinfo=None)
    return now


def extract_event_datetime(text: str, now: datetime | None = None) -> datetime | None:
    """Дата/время СОБЫТИЯ из реплики — детерминированный слой, не LLM.

    dateparser (ru) + RELATIVE_BASE=now: «завтра», «через 2 дня», «в пятницу».
    Возвращает aware UTC или None, если даты события нет (одни сдвиги не в счёт).
    """
    base = _local_naive_base(now)
    matches = search_dates(
        _normalize_times(text),
        languages=["ru"],
        settings={"RELATIVE_BASE": base, "PREFER_DATES_FROM": "future"},
    )
    chosen: tuple[str, datetime] | None = None
    for mtext, mdt in matches or []:
        if _OFFSET_TEXT_RE.match(mtext.strip()):
            continue
        chosen = (mtext.strip(), mdt)
        break
    if chosen is None:
        return None
    mtext, mdt = chosen

    time_only = _TIME_ONLY_RE.match(mtext)
    if time_only:
        hour, minute = (int(p) for p in time_only.group(1).split(":"))
        rebuilt = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if rebuilt <= base:
            rebuilt += timedelta(days=1)
        mdt = rebuilt

    if mdt.tzinfo is None:
        mdt = mdt.replace(tzinfo=get_localzone())
    return mdt.astimezone(timezone.utc)
