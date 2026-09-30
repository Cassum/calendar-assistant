from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog

_HANDLER_NAME = "calendar-assistant-json"


def setup_logging(level: str = "INFO", log_file: str | Path | None = None) -> None:
    """JSON-логи в stdout и (опционально) в файл — одна и та же строка в обоих местах.

    structlog шлёт event_dict через stdlib-рейку, каждый handler рендерит его своим
    ProcessorFormatter: файл пишется с utf-8, чтобы кириллица не падала на Windows.
    """
    level_num = getattr(logging, level.upper(), logging.INFO)
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    root = logging.getLogger()
    root.setLevel(level_num)
    # повторный вызов (тесты) не должен плодить дубли handler'ов
    for h in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(h)
        h.close()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.set_name(_HANDLER_NAME)
    root.addHandler(stream_handler)

    if log_file:
        p = Path(log_file)
        if p.parent != Path("."):
            p.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(p, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.set_name(_HANDLER_NAME)
        root.addHandler(file_handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level_num),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
