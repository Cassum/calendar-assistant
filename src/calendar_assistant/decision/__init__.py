from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

NODE_CREATE_EVENT = "create_event"
NODE_UNRECOGNIZED = "unrecognized"
KNOWN_NODES = frozenset({NODE_CREATE_EVENT, NODE_UNRECOGNIZED})


@dataclass(frozen=True)
class Decision:
    """Контракт Сменного слоя (единственный шов принятия решений)."""

    node: str
    confidence: float | None
    reason: str
    layer: Literal["laya", "llm"]


class DecisionLayer(Protocol):
    async def route(self, message: str) -> Decision: ...


class JsonCompleter(Protocol):
    """Минимальный шов к LLM: JSON по схеме. Реализуется в llm.py."""

    async def complete_json(self, *, system: str, user: str, schema: dict) -> dict: ...


def apply_policy(decision: Decision, threshold: float) -> Decision:
    """Политика приложения (порог в конфиге), единая для обоих слоёв: fail-open."""
    if decision.node not in KNOWN_NODES:
        return Decision(
            node=NODE_UNRECOGNIZED,
            confidence=decision.confidence,
            reason=f"неизвестная метка {decision.node!r}; {decision.reason}",
            layer=decision.layer,
        )
    if decision.confidence is not None and decision.confidence < threshold:
        return Decision(
            node=NODE_UNRECOGNIZED,
            confidence=decision.confidence,
            reason=f"confidence {decision.confidence} < порога {threshold}; {decision.reason}",
            layer=decision.layer,
        )
    return decision


def make_decision_layer(cfg, completer: JsonCompleter) -> DecisionLayer:
    """Зависимость от Config только ради выбора реализации; граф слой не знает."""
    if cfg.decision.layer == "laya":
        from calendar_assistant.decision.laya_layer import LayaDecisionLayer

        return LayaDecisionLayer()
    from calendar_assistant.decision.llm_layer import LLMDecisionLayer

    return LLMDecisionLayer(completer)
