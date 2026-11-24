"""Local chat templates need one leading system message and at least one user message."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.home.llm_messages import local_chat_messages
from app.services.prompts.common import ANTHROPIC_SYSTEM_ONLY_TRIGGER, JSON_ONLY_INSTRUCTION
from tests.test_llm_adapter import _make_ollama_settings


def test_valid_messages_are_unchanged() -> None:
    messages = [
        {"role": "system", "content": "Be brief"},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "Again"},
    ]
    assert local_chat_messages(messages) == messages


def test_system_only_gets_a_user_trigger() -> None:
    assert local_chat_messages([{"role": "system", "content": "Make a game"}]) == [
        {"role": "system", "content": "Make a game"},
        {"role": "user", "content": ANTHROPIC_SYSTEM_ONLY_TRIGGER},
    ]


def test_trailing_system_messages_join_the_leading_one() -> None:
    messages = [
        {"role": "system", "content": "Make a game"},
        {"role": "user", "content": "Go"},
        {"role": "system", "content": "JSON only"},
        {"role": "user", "content": "Fix it"},
    ]
    assert local_chat_messages(messages) == [
        {"role": "system", "content": "Make a game\n\nJSON only"},
        {"role": "user", "content": "Go"},
        {"role": "user", "content": "Fix it"},
    ]


def test_trigger_goes_before_a_prefilled_assistant_message() -> None:
    messages = [
        {"role": "system", "content": "Greet"},
        {"role": "assistant", "content": "Hej"},
    ]
    assert local_chat_messages(messages) == [
        {"role": "system", "content": "Greet"},
        {"role": "user", "content": ANTHROPIC_SYSTEM_ONLY_TRIGGER},
        {"role": "assistant", "content": "Hej"},
    ]


def test_input_list_is_not_mutated() -> None:
    messages = [{"role": "system", "content": "A"}, {"role": "system", "content": "B"}]
    local_chat_messages(messages)
    assert messages == [{"role": "system", "content": "A"}, {"role": "system", "content": "B"}]


@pytest.mark.asyncio
async def test_structured_output_sends_a_valid_order_to_ollama(monkeypatch) -> None:
    _make_ollama_settings(monkeypatch)

    from app.services.llm_adapter import LLMAdapter

    msg = MagicMock()
    msg.content = '{"ok": true}'
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = msg

    from pydantic import BaseModel

    class Out(BaseModel):
        ok: bool

    adapter = LLMAdapter()
    with patch.object(
        adapter.client.chat.completions, "create", new_callable=AsyncMock, return_value=response
    ) as create:
        await adapter.structured_output([{"role": "system", "content": "Make it"}], Out)
    sent = create.await_args.kwargs["messages"]
    assert [m["role"] for m in sent] == ["system", "user"]
    assert sent[0]["content"] == f"Make it\n\n{JSON_ONLY_INSTRUCTION}"


@pytest.mark.asyncio
async def test_deepseek_messages_are_left_alone(monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "deepseek")
    monkeypatch.setattr("app.core.config.settings.DEEPSEEK_API_KEY", "sk-test")

    from app.services.llm_adapter import LLMAdapter

    msg = MagicMock()
    msg.content = "ok"
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = msg

    adapter = LLMAdapter()
    with patch.object(
        adapter.client.chat.completions, "create", new_callable=AsyncMock, return_value=response
    ) as create:
        await adapter.chat([{"role": "system", "content": "Only system"}])
    assert create.await_args.kwargs["messages"] == [{"role": "system", "content": "Only system"}]
