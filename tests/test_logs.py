from __future__ import annotations

import json
import logging

from calendar_assistant.logs import get_logger, setup_logging


def _lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class TestSetupLogging:
    def test_structlog_event_written_to_file(self, tmp_path):
        log_file = tmp_path / "bot.log"
        setup_logging("INFO", log_file)
        get_logger("test.file").info("probe.event", chat_id=42, текст="встреча")
        events = _lines(log_file)
        hit = [e for e in events if e.get("event") == "probe.event"]
        assert hit, f"probe.event не найден в {events}"
        assert hit[0]["chat_id"] == 42
        assert hit[0]["текст"] == "встреча"
        assert hit[0]["level"] == "info"
        assert "_record" not in hit[0]

    def test_foreign_stdlib_record_does_not_break(self, tmp_path):
        log_file = tmp_path / "bot.log"
        setup_logging("INFO", log_file)
        logging.getLogger("aiogram").info("чужая запись из стороннего логгера")
        events = _lines(log_file)
        assert any("чужая запись" in str(e.get("event", "")) for e in events), events

    def test_no_file_when_disabled(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        setup_logging("INFO", None)
        get_logger("test.nofile").info("only.stdout.event")
        assert not (tmp_path / "bot.log").exists()

    def test_rerun_does_not_duplicate_handlers(self, tmp_path):
        log_file = tmp_path / "bot.log"
        setup_logging("INFO", log_file)
        setup_logging("INFO", log_file)
        get_logger("test.once").info("single.event")
        events = [e for e in _lines(log_file) if e.get("event") == "single.event"]
        assert len(events) == 1
