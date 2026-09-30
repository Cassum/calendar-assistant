from __future__ import annotations

import pytest

from calendar_assistant.decision import (
    NODE_CREATE_EVENT,
    NODE_UNRECOGNIZED,
    Decision,
    apply_policy,
)
from calendar_assistant.decision.laya_layer import LayaDecisionLayer
from calendar_assistant.decision.llm_layer import LLMDecisionLayer


class TestApplyPolicy:
    def test_unknown_label_fails_open(self):
        d = Decision("banana", 0.9, "метка вне enum", "laya")
        out = apply_policy(d, threshold=0.5)
        assert out.node == NODE_UNRECOGNIZED
        assert out.confidence == 0.9
        assert out.layer == "laya"
        assert "banana" in out.reason

    def test_low_confidence_rejected(self):
        d = Decision(NODE_CREATE_EVENT, 0.3, "", "laya")
        out = apply_policy(d, threshold=0.5)
        assert out.node == NODE_UNRECOGNIZED
        assert out.confidence == 0.3

    def test_confidence_at_threshold_passes(self):
        d = Decision(NODE_CREATE_EVENT, 0.5, "", "laya")
        assert apply_policy(d, threshold=0.5).node == NODE_CREATE_EVENT

    def test_none_confidence_not_gated(self):
        """Облачная LLM: честное None — порог не применяется."""
        d = Decision(NODE_CREATE_EVENT, None, "", "llm")
        out = apply_policy(d, threshold=0.9)
        assert out.node == NODE_CREATE_EVENT
        assert out.confidence is None


class FakeCompleter:
    def __init__(self, result=None, raise_exc=None):
        self.result = result
        self.raise_exc = raise_exc

    async def complete_json(self, *, system, user, schema):
        if self.raise_exc:
            raise self.raise_exc
        return self.result


class TestLLMDecisionLayer:
    async def test_valid_route(self):
        layer = LLMDecisionLayer(
            FakeCompleter({"node": NODE_CREATE_EVENT, "reason": "просьба создать встречу"})
        )
        d = await layer.route("Встреча с Иваном завтра в 15:00")
        assert d.node == NODE_CREATE_EVENT
        assert d.confidence is None
        assert d.layer == "llm"

    async def test_llm_error_fails_open(self):
        layer = LLMDecisionLayer(FakeCompleter(raise_exc=RuntimeError("boom")))
        d = await layer.route("что-то")
        assert d.node == NODE_UNRECOGNIZED
        assert d.confidence is None
        assert "boom" in d.reason

    async def test_label_out_of_enum(self):
        layer = LLMDecisionLayer(FakeCompleter({"node": "delete_all", "reason": "?"}))
        d = await layer.route("отмени всё")
        assert d.node == NODE_UNRECOGNIZED

    async def test_not_a_dict(self):
        layer = LLMDecisionLayer(FakeCompleter("мусор вместо JSON"))
        d = await layer.route("привет")
        assert d.node == NODE_UNRECOGNIZED


class FakeAgent:
    def __init__(self, answer=None, raise_exc=None):
        self.answer = answer
        self.raise_exc = raise_exc

    def predict(self, state, questions, **kwargs):
        if self.raise_exc:
            raise self.raise_exc
        return {"model": "fake", "answers": {"intent": self.answer}, "usage": {}}


class TestLayaDecisionLayer:
    def test_valid_route_with_confidence(self):
        agent = FakeAgent(
            {"type": "choice", "choice": NODE_CREATE_EVENT, "answer_confidence": 0.87}
        )
        layer = LayaDecisionLayer(agent=agent)
        d = layer._route_sync("Встреча с Иваном")
        assert d.node == NODE_CREATE_EVENT
        assert d.confidence == 0.87
        assert d.layer == "laya"

    def test_low_confidence_passes_through_policy(self):
        agent = FakeAgent(
            {"type": "choice", "choice": NODE_CREATE_EVENT, "answer_confidence": 0.2}
        )
        layer = LayaDecisionLayer(agent=agent)
        out = apply_policy(layer._route_sync("смайл :)"), threshold=0.5)
        assert out.node == NODE_UNRECOGNIZED

    def test_unknown_choice_fails_open(self):
        agent = FakeAgent({"type": "choice", "choice": "cancel", "answer_confidence": 0.99})
        layer = LayaDecisionLayer(agent=agent)
        d = layer._route_sync("отмени всё")
        assert d.node == NODE_UNRECOGNIZED

    def test_agent_error_fails_open(self):
        layer = LayaDecisionLayer(agent=FakeAgent(raise_exc=RuntimeError("no weights")))
        d = layer._route_sync("привет")
        assert d.node == NODE_UNRECOGNIZED
        assert "no weights" in d.reason

    @pytest.mark.skipif(True, reason="качает веса; включается вручную для прогона на живой laya")
    async def test_live_laya(self):
        layer = LayaDecisionLayer()
        d = await layer.route("Встреча с Иваном завтра в 15:00")
        assert d.node in {NODE_CREATE_EVENT, NODE_UNRECOGNIZED}
