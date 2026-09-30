import asyncio
from logging.config import fileConfig
from pathlib import Path

import yaml
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from calendar_assistant.db import models  # noqa: E402,F401  (регистрация таблиц в metadata)
from calendar_assistant.db.base import Base  # noqa: E402

target_metadata = Base.metadata


def _database_url() -> str:
    # 1) url, переданный программно (main()); 2) sqlalchemy.url в ini; 3) config.yaml
    url = config.attributes.get("sqlalchemy.url") or config.get_main_option("sqlalchemy.url")
    if url:
        return url
    cfg_path = Path("config.yaml")
    if cfg_path.exists():
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict) and raw.get("database_url"):
            return str(raw["database_url"])
    return "sqlite+aiosqlite:///./calendar.db"


def run_migrations_offline() -> None:
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": _database_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
