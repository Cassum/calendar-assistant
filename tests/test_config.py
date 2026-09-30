from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from calendar_assistant import config as config_mod
from calendar_assistant.config import ConfigError, LLMConfig, load_config


@pytest.fixture
def clean_env(monkeypatch):
    """Изолируем от реального .env: load_dotenv — no-op, ключи заданы явно."""
    monkeypatch.setattr(config_mod, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.delenv("LLM_API_KEY", raising=False)


def _write_yaml(tmp_path: Path, llm_block: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(f"llm:\n{llm_block}\nbot:\n  token: x\n", encoding="utf-8")
    return p


class TestLLMConfigDefaults:
    def test_openai_requires_api_key(self):
        with pytest.raises(ValidationError, match="api_key"):
            LLMConfig(model="gpt-4o-mini")

    def test_openai_default_base_url(self):
        cfg = LLMConfig(model="gpt-4o-mini", api_key="sk-test")
        assert cfg.provider == "openai"
        assert cfg.base_url == "https://api.openai.com/v1"

    def test_ollama_without_key(self):
        cfg = LLMConfig(provider="ollama", model="qwen3:8b")
        assert cfg.base_url == "http://localhost:11434/v1"
        assert cfg.api_key.get_secret_value() == "ollama"

    def test_ollama_explicit_base_url_respected(self):
        cfg = LLMConfig(provider="ollama", model="qwen3:8b", base_url="http://gpu-box:11434/v1")
        assert cfg.base_url == "http://gpu-box:11434/v1"

    def test_unknown_provider_rejected(self):
        with pytest.raises(ValidationError):
            LLMConfig(provider="grok", model="m", api_key="k")  # type: ignore[arg-type]


class TestLoadConfig:
    def test_openai_env_key_required(self, clean_env, tmp_path):
        p = _write_yaml(tmp_path, '  provider: "openai"\n  model: "openai/gpt-4o-mini"\n')
        with pytest.raises(ConfigError, match="LLM_API_KEY"):
            load_config(p)

    def test_openai_env_key_injected(self, clean_env, monkeypatch, tmp_path):
        monkeypatch.setenv("LLM_API_KEY", "sk-or-secret")
        p = _write_yaml(tmp_path, '  provider: "openai"\n  model: "openai/gpt-4o-mini"\n')
        cfg = load_config(p)
        assert cfg.llm.api_key.get_secret_value() == "sk-or-secret"
        assert cfg.llm.base_url == "https://api.openai.com/v1"

    def test_ollama_works_without_api_key(self, clean_env, tmp_path):
        p = _write_yaml(
            tmp_path,
            '  provider: "ollama"\n  model: "qwen3:8b"\n',
        )
        cfg = load_config(p)
        assert cfg.llm.provider == "ollama"
        assert cfg.llm.base_url == "http://localhost:11434/v1"
        assert cfg.llm.model == "qwen3:8b"
        assert cfg.llm.api_key.get_secret_value() == "ollama"

    def test_ollama_ignores_llm_api_key(self, clean_env, monkeypatch, tmp_path):
        monkeypatch.setenv("LLM_API_KEY", "stale-key-from-cloud")
        p = _write_yaml(tmp_path, '  provider: "ollama"\n  model: "qwen3:8b"\n')
        cfg = load_config(p)
        assert cfg.llm.api_key.get_secret_value() == "ollama"

    def test_unknown_provider_fails_startup(self, clean_env, tmp_path):
        p = _write_yaml(tmp_path, '  provider: "grok"\n  model: "m"\n')
        with pytest.raises(ConfigError, match="provider"):
            load_config(p)
