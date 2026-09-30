from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tzlocal import get_localzone

from calendar_assistant.dates import extract_event_datetime

LOCAL = get_localzone()
BASE = datetime(2026, 9, 30, 12, 0)  # среда


def _expect(wall: datetime) -> datetime:
    return wall.replace(tzinfo=LOCAL).astimezone(timezone.utc)


def test_tomorrow_time_ignores_offset_phrase():
    got = extract_event_datetime(
        "Встреча с Иваном завтра в 15:00, напомни за полчаса", now=BASE
    )
    assert got == _expect(datetime(2026, 10, 1, 15, 0))


def test_offset_phrase_first_still_finds_event():
    got = extract_event_datetime(
        "напомни за полчаса о встрече завтра в 15:00", now=BASE
    )
    assert got == _expect(datetime(2026, 10, 1, 15, 0))


def test_relative_days_with_time():
    got = extract_event_datetime("встреча через 2 дня в 10:00", now=BASE)
    assert got == _expect(datetime(2026, 10, 2, 10, 0))


def test_time_only_in_future_today():
    got = extract_event_datetime("встреча в 18:00", now=datetime(2026, 9, 30, 16, 0))
    assert got == _expect(datetime(2026, 9, 30, 18, 0))


def test_time_only_already_past_shifts_to_tomorrow():
    got = extract_event_datetime("встреча в 15:00", now=datetime(2026, 9, 30, 16, 0))
    assert got == _expect(datetime(2026, 10, 1, 15, 0))


def test_weekday_prefers_upcoming():
    got = extract_event_datetime("поставь встречу в пятницу", now=datetime(2026, 9, 30, 16, 0))
    assert got == _expect(datetime(2026, 10, 2, 0, 0))


def test_no_date_returns_none():
    assert extract_event_datetime("привет как дела", now=BASE) is None


def test_only_offset_returns_none():
    assert extract_event_datetime("напомни за полчаса", now=BASE) is None


def test_result_is_aware_utc():
    got = extract_event_datetime("завтра в 15:00", now=BASE)
    assert got is not None
    assert got.tzinfo is not None
    assert got.utcoffset() == timedelta(0)


def test_aware_now_accepted():
    now = BASE.replace(tzinfo=LOCAL)
    got = extract_event_datetime("завтра в 15:00", now=now)
    assert got == _expect(datetime(2026, 10, 1, 15, 0))


def test_tomorrow_with_hour_word():
    # регресс: «в 14 часов» парсер держал за длительность (база +14ч → 02.10 10:18)
    got = extract_event_datetime(
        "покормить котят завтра в 14 часов", now=datetime(2026, 9, 30, 20, 18)
    )
    assert got == _expect(datetime(2026, 10, 1, 14, 0))


def test_hour_word_only_past_time_shifts_to_tomorrow():
    got = extract_event_datetime("встреча в 14 часов", now=datetime(2026, 9, 30, 20, 18))
    assert got == _expect(datetime(2026, 10, 1, 14, 0))


def test_meridian_morning_today():
    got = extract_event_datetime("встреча в 10 утра", now=datetime(2026, 9, 30, 8, 0))
    assert got == _expect(datetime(2026, 9, 30, 10, 0))


def test_meridian_evening_today():
    got = extract_event_datetime("встреча в 9 вечера", now=datetime(2026, 9, 30, 16, 0))
    assert got == _expect(datetime(2026, 9, 30, 21, 0))


def test_duration_through_hours_untouched():
    # «через N часов» — это длительность, её нормализация не трогает
    got = extract_event_datetime(
        "встреча через 14 часов", now=datetime(2026, 9, 30, 20, 18)
    )
    assert got == _expect(datetime(2026, 10, 1, 10, 18))
