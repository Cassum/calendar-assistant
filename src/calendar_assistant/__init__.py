import asyncio
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from alembic import command
from alembic.config import Config as AlembicConfig
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from calendar_assistant.bot import build_dispatcher
from calendar_assistant.calendar_tools import SqliteCalendarTools
from calendar_assistant.config import Config, ConfigError, load_config
from calendar_assistant.db.session import create_engine_and_sessions
from calendar_assistant.decision import make_decision_layer
from calendar_assistant.graph import build_graph
from calendar_assistant.llm import LLMClient
from calendar_assistant.logs import get_logger, setup_logging
from calendar_assistant.monitoring import flush_langfuse, setup_langfuse
from calendar_assistant.reminders import send_due_reminders


def _find_alembic_ini() -> Path:
    candidates = [
        Path.cwd() / "alembic.ini",
        Path(__file__).resolve().parents[2] / "alembic.ini",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise ConfigError("alembic.ini не найден — запускай из корня репозитория")


def _upgrade_db(database_url: str) -> None:
    cfg = AlembicConfig(str(_find_alembic_ini()))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


async def _run(cfg: Config) -> None:
    log = get_logger("calendar_assistant")
    engine, factory = create_engine_and_sessions(cfg.database_url)

    llm = LLMClient(cfg.llm)
    decision_layer = make_decision_layer(cfg, llm)
    tools = SqliteCalendarTools(factory, cfg.reminders.default_offset_minutes)
    graph = build_graph(
        decision_layer=decision_layer,
        llm=llm,
        tools=tools,
        threshold=cfg.decision.threshold,
        layer_name=cfg.decision.layer,
    )

    bot = Bot(token=cfg.bot.token.get_secret_value())
    dp: Dispatcher = build_dispatcher(graph)

    scheduler = AsyncIOScheduler(timezone="UTC")

    async def _tick() -> None:
        await send_due_reminders(bot, factory, max_attempts=cfg.reminders.max_attempts)

    scheduler.add_job(
        _tick,
        "interval",
        seconds=cfg.reminders.tick_seconds,
        id="reminders",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    scheduler.start()
    log.info(
        "bot.starting",
        decision_layer=cfg.decision.layer,
        tick_seconds=cfg.reminders.tick_seconds,
    )
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()
        flush_langfuse()
        log.info("bot.stopped")


def main() -> None:
    try:
        cfg = load_config()
        _upgrade_db(cfg.database_url)
    except ConfigError as e:
        print(f"Ошибка конфигурации: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    setup_logging(cfg.log_level, cfg.log_file)
    log = get_logger("calendar_assistant")
    langfuse_on = setup_langfuse(cfg.langfuse)
    log.info(
        "config.loaded",
        decision_layer=cfg.decision.layer,
        llm_provider=cfg.llm.provider,
        llm_base_url=cfg.llm.base_url,
        llm_model=cfg.llm.model,
        database_url=cfg.database_url,
        langfuse_enabled=langfuse_on,
        log_level=cfg.log_level,
    )
    try:
        asyncio.run(_run(cfg))
    except KeyboardInterrupt:
        log.info("bot.interrupted")
