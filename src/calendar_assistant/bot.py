from __future__ import annotations

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from calendar_assistant import monitoring
from calendar_assistant.logs import get_logger

log = get_logger(__name__)

TEMPLATE_START = (
    "Я создаю события календаря и напоминаю о них. "
    "Напиши, например: «Встреча с Иваном завтра в 15:00, напомни за полчаса»"
)
TEMPLATE_INTERNAL_ERROR = "Что-то пошло не так. Попробуй ещё раз."


def build_dispatcher(graph) -> Dispatcher:
    """Диспетчер поверх уже собранного графа — сообщение → graph.ainvoke → reply."""
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        await message.answer(TEMPLATE_START)

    @dp.message(F.text)
    async def on_text(message: Message) -> None:
        text = message.text or ""
        with monitoring.span(
            "handle_message", input={"chat_id": message.chat.id, "text": text}
        ) as trace:
            try:
                result = await graph.ainvoke({"message": text, "chat_id": message.chat.id})
            except Exception as e:
                log.error("bot.graph_error", error=str(e), message=text)
                trace.update(output=TEMPLATE_INTERNAL_ERROR, level="ERROR")
                await message.answer(TEMPLATE_INTERNAL_ERROR)
                return
            reply = str(result.get("reply") or TEMPLATE_INTERNAL_ERROR)
            trace.update(output=reply)
        log.info("bot.reply", chat_id=message.chat.id, node=result.get("node"), reply=reply)
        await message.answer(reply)

    return dp
