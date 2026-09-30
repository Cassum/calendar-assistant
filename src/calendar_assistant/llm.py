from __future__ import annotations

import asyncio
import json

from openai import AsyncOpenAI, BadRequestError

from calendar_assistant import monitoring
from calendar_assistant.config import LLMConfig
from calendar_assistant.logs import get_logger

log = get_logger(__name__)

# бесплатные модели отдают пустой content в духе 1 ответа из 10 — повторяем
_MAX_ATTEMPTS = 3
_EMPTY_PAUSE_SECONDS = 1.0


def _usage_details(resp) -> dict | None:
    u = getattr(resp, "usage", None)
    if u is None:
        return None
    return {
        "input": u.prompt_tokens,
        "output": u.completion_tokens,
        "total": u.total_tokens,
    }


class LLMClient:
    """JSON-ответы через OpenAI-совместимый API (облако или Ollama).

    Реализует JsonCompleter (шов сменного слоя) и Llm графа (слоты события).
    Каждый вызов — отдельная generation в langfuse (когда трейсы включены).
    """

    def __init__(self, cfg: LLMConfig):
        self._client = AsyncOpenAI(
            base_url=cfg.base_url,
            api_key=cfg.api_key.get_secret_value(),
            timeout=60.0,  # бесплатные провайдеры подвешивают ответы минутами
            max_retries=2,
        )
        self._model = cfg.model
        self._temperature = cfg.temperature
        # Ollama на /v1 сам включает thinking у think-моделей (qwen3.5 и т.п.):
        # +500 токенов рассуждений на ответ, минутные задержки и таймауты → выключаем
        self._extra_body = (
            {"reasoning_effort": "none"} if cfg.provider == "ollama" else None
        )
        # часть провайдеров (старые версии Ollama) отвергает json_schema — деградируем до json_object
        self._schema_rejected = False

    async def _create(self, *, system: str, user: str, response_format: dict | None):
        if (
            response_format is not None
            and response_format.get("type") == "json_schema"
            and self._schema_rejected
        ):
            # провайдер уже отверг json_schema — сразу просим просто JSON
            response_format = {"type": "json_object"}
        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self._extra_body:
            payload["extra_body"] = self._extra_body
        if response_format is not None:
            payload["response_format"] = response_format
        attempt = 0
        while attempt < _MAX_ATTEMPTS:
            try:
                # внешний wait_for: SDK-таймаут провайдеры подвешивают
                resp = await asyncio.wait_for(
                    self._client.chat.completions.create(**payload),
                    timeout=90.0,
                )
            except BadRequestError:
                if (
                    payload.get("response_format", {}).get("type") != "json_schema"
                    or self._schema_rejected
                ):
                    raise
                log.warning("llm.json_schema_rejected", model=self._model)
                self._schema_rejected = True
                payload["response_format"] = {"type": "json_object"}
                continue  # деградация не тратит попытку
            attempt += 1
            content = (resp.choices[0].message.content or "").strip()
            if content:
                return resp, content
            log.warning("llm.empty_content", attempt=attempt, model=self._model)
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(_EMPTY_PAUSE_SECONDS)
        raise RuntimeError(f"пустой ответ LLM после {_MAX_ATTEMPTS} попыток ({self._model})")

    async def complete_json(self, *, system: str, user: str, schema: dict) -> dict:
        with monitoring.generation(
            "llm.complete_json",
            input={"system": system, "user": user},
            model=self._model,
        ) as gen:
            resp, content = await self._create(
                system=system,
                user=user,
                response_format={"type": "json_schema", "json_schema": schema},
            )
            data = json.loads(content)
            gen.update(output=data, usage_details=_usage_details(resp))
            return data
