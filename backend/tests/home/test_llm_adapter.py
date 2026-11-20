"""Home patches to the LLM adapter: reasoning effort, and a 503 meaning unavailable."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_llm_adapter import FakeOpenAIChunk, _make_ollama_settings


class TestReasoningEffort:
    @pytest.mark.asyncio
    async def test_reasoning_effort_sent_for_local(self, monkeypatch):
        _make_ollama_settings(monkeypatch)

        from app.services.llm_adapter import LLMAdapter

        msg = MagicMock()
        msg.content = "ok"
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message = msg

        adapter = LLMAdapter()
        with patch.object(
            adapter.client.chat.completions,
            "create",
            new_callable=AsyncMock,
            return_value=response,
        ) as create:
            await adapter.chat([{"role": "user", "content": "Hi"}], reasoning_effort="low")
            assert create.await_args.kwargs["reasoning_effort"] == "low"

    @pytest.mark.asyncio
    async def test_reasoning_effort_absent_by_default(self, monkeypatch):
        _make_ollama_settings(monkeypatch)

        from app.services.llm_adapter import LLMAdapter

        msg = MagicMock()
        msg.content = "ok"
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message = msg

        adapter = LLMAdapter()
        with patch.object(
            adapter.client.chat.completions,
            "create",
            new_callable=AsyncMock,
            return_value=response,
        ) as create:
            await adapter.chat([{"role": "user", "content": "Hi"}])
            assert "reasoning_effort" not in create.await_args.kwargs

    @pytest.mark.asyncio
    async def test_reasoning_effort_not_sent_to_deepseek(self, monkeypatch):
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
            adapter.client.chat.completions,
            "create",
            new_callable=AsyncMock,
            return_value=response,
        ) as create:
            await adapter.chat([{"role": "user", "content": "Hi"}], reasoning_effort="low")
            assert "reasoning_effort" not in create.await_args.kwargs


class TestServiceUnavailable:
    @pytest.mark.asyncio
    async def test_service_unavailable_status_means_unavailable(self, monkeypatch):
        """The speech gateway answers 503 while the local LLM is down."""
        from app.services.llm_adapter import LLMAdapter, LLMUnavailableError

        class ServiceUnavailable(Exception):
            status_code = 503

        monkeypatch.setattr("app.services.llm_adapter.asyncio.sleep", AsyncMock())
        adapter = LLMAdapter()
        call = AsyncMock(side_effect=ServiceUnavailable("Error code: 503"))
        with pytest.raises(LLMUnavailableError):
            await adapter._call_with_retry(call)


class TestToolFallbackEffort:
    @pytest.mark.asyncio
    async def test_reasoning_effort_reaches_fallback_call(self, monkeypatch):
        _make_ollama_settings(monkeypatch)
        from app.services.llm_adapter import LLMAdapter, LLMTool, LLMToolResult

        async def fallback_stream():
            yield FakeOpenAIChunk("Normal response.")

        adapter = LLMAdapter()
        tool = LLMTool("save_user_memory", "Save memory", {"type": "object"})
        messages = [{"role": "user", "content": "Hi"}]

        async def executor(call):
            return LLMToolResult(call=call, content={"saved": True})

        with patch.object(
            adapter.client.chat.completions,
            "create",
            new_callable=AsyncMock,
            side_effect=[
                RuntimeError("This model does not support function calling"),
                fallback_stream(),
            ],
        ) as create:
            stream = await adapter.chat(
                messages,
                stream=True,
                tools=[tool],
                tool_executor=executor,
                reasoning_effort="low",
            )
            assert [part async for part in stream] == ["Normal response."]

        assert [call.kwargs["reasoning_effort"] for call in create.call_args_list] == [
            "low",
            "low",
        ]
