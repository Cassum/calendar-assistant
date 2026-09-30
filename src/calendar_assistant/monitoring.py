from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from calendar_assistant.config import LangfuseConfig
from calendar_assistant.logs import get_logger

log = get_logger(__name__)

_client: Any = None


class _NoopObs:
    """Заглушка, когда трейсы выключены: API тот же, сетевых вызовов нет."""

    def update(self, **_: Any) -> None:
        return None

    def end(self, **_: Any) -> None:
        return None


def setup_langfuse(cfg: LangfuseConfig) -> bool:
    """Голая обвязка SDK: инициализация только при заданных ключах.

    False — трейсы выключены (ключи в .env отсутствуют), всё ниже работает no-op.
    """
    global _client
    if cfg.public_key is None or cfg.secret_key is None:
        return False
    from langfuse import Langfuse  # лениво: тяжёлый OTel-импорт только при включении

    _client = Langfuse(
        public_key=cfg.public_key.get_secret_value(),
        secret_key=cfg.secret_key.get_secret_value(),
        host=cfg.host,
    )
    log.info("langfuse.enabled", host=cfg.host)
    return True


def flush_langfuse() -> None:
    if _client is None:
        return
    try:
        _client.flush()
    except Exception as e:
        log.warning("langfuse.flush_error", error=str(e))


@contextmanager
def _observation(kind: str, name: str, **kwargs: Any) -> Iterator[Any]:
    if _client is None:
        yield _NoopObs()
        return
    with _client.start_as_current_observation(name=name, as_type=kind, **kwargs) as obs:
        yield obs


def span(name: str, *, input: Any = None) -> Any:
    """Span верхнего уровня (сообщение пользователя) — корень трейса."""
    return _observation("span", name, input=input)


def generation(
    name: str,
    *,
    input: Any = None,
    model: str | None = None,
    usage_details: dict | None = None,
) -> Any:
    """Один вызов LLM: latency берётся из трейса, вход/выход и usage — наши."""
    return _observation(
        "generation",
        name,
        input=input,
        model=model,
        usage_details=usage_details,
    )
