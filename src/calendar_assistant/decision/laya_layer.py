from __future__ import annotations

import asyncio

from calendar_assistant.decision import (
    KNOWN_NODES,
    NODE_UNRECOGNIZED,
    Decision,
)
from calendar_assistant.logs import get_logger

log = get_logger(__name__)

QUESTION_ID = "intent"
INSTRUCTIONS = (
    "Какую задачу выполняет сообщение пользователя Telegram-бота календаря "
    "и напоминаний?"
)
CRITERIA = {
    "create_event": "Пользователь хочет создать событие, встречу или напоминание. "
                    "Это поведение по-умолчанию, поэтому формулировки \"Покормить котов завтра\", "
                    "\"Сделай курсовую через месяц\" и похожие подходят",
    "unrecognized": "всё остальное: вопрос, разговор, мусор, неопределённое намерение",
}


class LayaDecisionLayer:
    """Роутер на laya (System 1, CPU, вне VRAM).

    Грузится только multilingual-чекпоинт (~0.6 ГБ, качается при первом запуске).
    predict — синхронный и CPU-bound, поэтому в asyncio.to_thread.
    """

    def __init__(self, agent=None, model_id: str = "convaiinnovations/laya"):
        if agent is None:
            import laya

            log.info("laya.loading_model", model_id=model_id)
            agent = laya.load(model_id, subfolder="multilingual")
        self._agent = agent

    async def route(self, message: str) -> Decision:
        return await asyncio.to_thread(self._route_sync, message)

    def _route_sync(self, message: str) -> Decision:
        try:
            result = self._agent.predict(
                message,
                {QUESTION_ID: {"type": "choice", "instructions": INSTRUCTIONS, "criteria": CRITERIA}},
            )
            answer = result["answers"][QUESTION_ID]
            node = answer["choice"]
            confidence = answer.get("answer_confidence")
        except Exception as e:
            log.warning("route.laya_error", error=str(e))
            return Decision(NODE_UNRECOGNIZED, None, f"ошибка laya-роутера: {e}", "laya")
        if node not in KNOWN_NODES:
            return Decision(NODE_UNRECOGNIZED, confidence, f"метка вне enum: {node!r}", "laya")
        return Decision(str(node), confidence, f"laya choice={node}", "laya")
