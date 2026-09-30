from calendar_assistant import monitoring
from calendar_assistant.config import LangfuseConfig


def test_setup_disabled_without_keys():
    assert monitoring.setup_langfuse(LangfuseConfig()) is False
    assert monitoring._client is None


def test_span_noop_without_client():
    with monitoring.span("handle_message", input={"text": "hi"}) as obs:
        obs.update(output="reply")
        obs.end()


def test_generation_noop_without_client():
    with monitoring.generation("llm.complete_json", input={"x": 1}, model="m") as gen:
        gen.update(output={"node": "create_event"}, usage_details={"input": 1, "output": 2})


def test_flush_without_client_is_noop():
    monitoring.flush_langfuse()
