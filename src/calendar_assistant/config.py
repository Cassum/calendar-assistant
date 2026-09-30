from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, ValidationError, model_validator


class ConfigError(RuntimeError):
    """Конфигурация неполная или некорректна — падаем сразу при старте, а не посреди работы."""


class BotConfig(BaseModel):
    token: SecretStr


# Дефолтные адреса OpenAI-совместимого API по провайдерам
_DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1",
}
# Ollama ключ не проверяет, но SDK требует непустую строку
_OLLAMA_DUMMY_KEY = "ollama"


class LLMConfig(BaseModel):
    provider: Literal["openai", "ollama"] = "openai"
    base_url: str = ""
    model: str
    temperature: float = 0.1
    api_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def _provider_defaults(self) -> LLMConfig:
        if not self.base_url:
            self.base_url = _DEFAULT_BASE_URLS[self.provider]
        if not self.api_key.get_secret_value():
            if self.provider != "ollama":
                raise ValueError(
                    "api_key обязателен для openai-совместимого провайдера — "
                    "заполни .env как LLM_API_KEY (образец: .env.example)"
                )
            self.api_key = SecretStr(_OLLAMA_DUMMY_KEY)
        return self


class DecisionConfig(BaseModel):
    layer: Literal["llm", "laya"] = "llm"
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class RemindersConfig(BaseModel):
    default_offset_minutes: int = 0
    tick_seconds: int = 30
    max_attempts: int = 3


class LangfuseConfig(BaseModel):
    host: str = "https://cloud.langfuse.com"
    public_key: SecretStr | None = None
    secret_key: SecretStr | None = None


class Config(BaseModel):
    llm: LLMConfig
    bot: BotConfig
    decision: DecisionConfig = DecisionConfig()
    reminders: RemindersConfig = RemindersConfig()
    langfuse: LangfuseConfig = LangfuseConfig()
    database_url: str = "sqlite+aiosqlite:///./calendar.db"
    log_level: str = "INFO"
    # куда писать JSON-логи помимо stdout; "" — только stdout
    log_file: str = "bot.log"

    @property
    def langfuse_enabled(self) -> bool:
        return self.langfuse.public_key is not None and self.langfuse.secret_key is not None


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"нет обязательного ключа {name} — заполни .env (образец: .env.example)")
    return value


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def load_config(path: str | Path = "config.yaml") -> Config:
    load_dotenv()
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"{p} не найден — скопируй шаблон: cp config.example.yaml {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{p} должен содержать YAML-словарь")

    raw.setdefault("bot", {})["token"] = _require_env("BOT_TOKEN")
    llm_raw = raw.setdefault("llm", {})
    provider = llm_raw.get("provider", "openai")
    if provider not in ("openai", "ollama"):
        raise ConfigError(
            f'неизвестный llm.provider "{provider}" в {p} — допустимы: "openai" | "ollama"'
        )
    if provider == "ollama":
        # Ollama работает без ключа; LLM_API_KEY игнорируется
        llm_raw.setdefault("api_key", _OLLAMA_DUMMY_KEY)
    else:
        llm_raw["api_key"] = _require_env("LLM_API_KEY")
    raw.setdefault("langfuse", {}).update(
        public_key=_optional_env("LANGFUSE_PUBLIC_KEY"),
        secret_key=_optional_env("LANGFUSE_SECRET_KEY"),
    )
    try:
        return Config(**raw)
    except ValidationError as e:
        raise ConfigError(f"{p} некорректен: {e}") from e
