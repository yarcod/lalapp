"""Provisional voice turns: nothing is visible or saved until the child's pause is confirmed."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers import speech_session
from app.routers.speech_session import SpeechSessionState, live_llm_is_small
from app.services.conversation_pipeline import ConversationPipeline
from app.services.llm_adapter import (
    LLMAdapter,
    LLMToolCall,
    LLMToolResult,
    LLMToolResultEvent,
)


def _chunk(text: str) -> MagicMock:
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = text
    return chunk


class Stream:
    def __init__(self, *parts: str) -> None:
        self.parts = parts
        self.tool_results: list = []
        self.closed = False

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for part in self.parts:
            yield _chunk(part)


class HangingStream(Stream):
    """A reply that never finishes, to observe a cancel mid-generation."""

    def __init__(self) -> None:
        super().__init__()
        self.cancelled = False

    async def _iterate(self):
        try:
            yield _chunk("Hello there. ")
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []

    async def send_json(self, data: object) -> None:
        self.sent.append(("json", data))

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(("bytes", data))

    def jsons(self, kind: str) -> list[dict]:
        return [d for t, d in self.sent if t == "json" and d.get("type") == kind]

    def audio(self) -> list[bytes]:
        return [d for t, d in self.sent if t == "bytes"]


def _pipeline(**kwargs) -> ConversationPipeline:
    kwargs.setdefault("generated_opener", True)
    pipeline = ConversationPipeline(
        llm=AsyncMock(),
        tts=AsyncMock(),
        stt=AsyncMock(),
        cefr_level="B1",
        max_duration=1800,
        inactivity_timeout=180,
        **kwargs,
    )
    pipeline.stt.transcribe = AsyncMock(return_value="I have a cat")
    pipeline.tts.synthesize = AsyncMock(side_effect=lambda text, *_: text.encode())
    pipeline.llm.chat = AsyncMock(
        side_effect=[Stream("Oh, a cat!"), Stream(" What colour is it?")]
    )
    pipeline._save_turn = AsyncMock()
    pipeline._save_usage = AsyncMock()
    return pipeline


async def _settle() -> None:
    for _ in range(40):
        await asyncio.sleep(0)


def _memory_call() -> LLMToolCall:
    return LLMToolCall(id="c1", name="save_user_memory", arguments={"content": "Has a cat"}, raw_arguments="")


def _scripted_tool_chat(pipeline: ConversationPipeline, reply: str) -> list[dict]:
    """A chat fake that, on the reply call, runs the tool executor like LLMToolStream does."""
    calls: list[dict] = []

    async def chat(messages, stream=False, **kwargs):
        calls.append({"messages": messages, **kwargs})
        if "tool_executor" not in kwargs:
            return Stream("Oh, a cat!")
        stream_obj = Stream()
        executor = kwargs["tool_executor"]

        async def iterate():
            result = await executor(_memory_call())
            yield LLMToolResultEvent(result=result)
            yield _chunk(reply)

        stream_obj._iterate = iterate
        return stream_obj

    pipeline.llm.chat = AsyncMock(side_effect=chat)
    return calls


@pytest.fixture
def memory():
    @asynccontextmanager
    async def fake_session():
        yield MagicMock()

    async def execute(db, user_id, call, source, *, study_plan_id=None):
        return LLMToolResult(call=call, content={"saved": True})

    with (
        patch("app.services.conversation_pipeline.db_session", fake_session),
        patch(
            "app.services.conversation_pipeline.execute_save_user_memory",
            AsyncMock(side_effect=execute),
        ) as mock,
    ):
        yield mock


@pytest.mark.asyncio
async def test_provisional_has_no_side_effects_until_confirmed() -> None:
    pipeline = _pipeline()
    ws = FakeWS()
    await pipeline.handle_audio(b"utterance", ws, provisional=True)
    await _settle()

    assert ws.sent == []
    assert pipeline.history == []
    pipeline._save_turn.assert_not_awaited()
    pipeline._save_usage.assert_not_awaited()
    assert not pipeline.current_task.done()  # generation done, holding at the commit point

    await pipeline._confirm_provisional(ws)
    await pipeline.current_task

    assert [m["role"] for m in pipeline.history] == ["user", "assistant"]
    pipeline._save_turn.assert_awaited_once()
    assert pipeline._save_usage.await_count == 2  # opener and reply
    assert ws.jsons("transcript")[0]["text"] == "I have a cat"
    assert ws.jsons("turn_complete")


@pytest.mark.asyncio
async def test_memory_calls_held_until_confirm(memory) -> None:
    pipeline = _pipeline(user_id=7)
    calls = _scripted_tool_chat(pipeline, "Nice.")
    ws = FakeWS()
    await pipeline.handle_audio(b"utterance", ws, provisional=True)
    await _settle()

    memory.assert_not_awaited()
    assert ws.jsons("memory_updated") == []

    await pipeline._confirm_provisional(ws)
    await pipeline.current_task
    await asyncio.gather(*pipeline._pending_saves)

    memory.assert_awaited_once()
    assert memory.await_args.args[2] == _memory_call()
    assert len(ws.jsons("memory_updated")) == 1
    assert calls[1]["tool_executor"] is not None


@pytest.mark.asyncio
async def test_abort_drops_held_memory_calls(memory) -> None:
    pipeline = _pipeline(user_id=7)
    _scripted_tool_chat(pipeline, "Nice.")
    ws = FakeWS()
    await pipeline.handle_audio(b"utterance", ws, provisional=True)
    await _settle()

    await pipeline._abort_provisional()
    await _settle()

    memory.assert_not_awaited()
    assert ws.sent == []


@pytest.mark.asyncio
async def test_abort_cancels_llm_and_tts() -> None:
    pipeline = _pipeline()
    stream = HangingStream()
    pipeline.llm.chat = AsyncMock(side_effect=[Stream("Oh, a cat!"), stream])
    ws = FakeWS()
    await pipeline.handle_audio(b"utterance", ws, provisional=True)
    await _settle()
    task = pipeline.current_task

    await pipeline._abort_provisional()

    assert task.cancelled()
    assert stream.cancelled
    assert ws.sent == []
    assert pipeline.history == []
    pipeline._save_turn.assert_not_awaited()
    pipeline._save_usage.assert_not_awaited()
    assert pipeline._provisional is None


@pytest.mark.asyncio
async def test_confirm_plays_opener_first() -> None:
    pipeline = _pipeline()
    ws = FakeWS()
    await pipeline.handle_audio(b"utterance", ws, provisional=True)
    await _settle()

    await pipeline._confirm_provisional(ws)
    await pipeline.current_task

    assert ws.audio() == [b"Oh, a cat!", b"What colour is it?"]
    # Before any tutor audio: the child's transcript and the status it came with.
    assert ws.sent[0] == ("json", {"type": "status", "value": "transcribing", "turn_id": 1})
    transcripts = ws.jsons("transcript")
    assert transcripts[-1]["text"] == "Oh, a cat! What colour is it?"
    assert pipeline.history[-1] == {
        "role": "assistant",
        "content": "Oh, a cat! What colour is it?",
    }


@pytest.mark.asyncio
async def test_confirm_mid_generation_streams_the_rest() -> None:
    pipeline = _pipeline()
    gate = asyncio.Event()

    async def iterate():
        yield _chunk("Part one. ")
        await gate.wait()
        yield _chunk("Part two.")

    reply = Stream()
    reply._iterate = iterate
    pipeline.llm.chat = AsyncMock(side_effect=[Stream("Oh, a cat!"), reply])
    ws = FakeWS()
    await pipeline.handle_audio(b"utterance", ws, provisional=True)
    await _settle()
    assert ws.audio() == []

    await pipeline._confirm_provisional(ws)
    assert ws.audio() == [b"Oh, a cat!", b"Part one."]

    gate.set()
    await pipeline.current_task
    assert ws.audio() == [b"Oh, a cat!", b"Part one.", b"Part two."]


@pytest.mark.asyncio
async def test_confirm_without_a_provisional_turn_is_a_no_op() -> None:
    pipeline = _pipeline()
    ws = FakeWS()
    await pipeline._confirm_provisional(ws)
    assert ws.sent == []


@pytest.mark.asyncio
async def test_provisional_after_empty_transcription_flushes_listening_on_confirm() -> None:
    pipeline = _pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="   ")
    ws = FakeWS()
    await pipeline.handle_audio(b"utterance", ws, provisional=True)
    await _settle()
    assert ws.sent == []
    await pipeline._confirm_provisional(ws)
    assert ws.jsons("status")[-1]["value"] == "listening"
    assert pipeline.history == []


@pytest.mark.asyncio
async def test_opener_uses_no_reasoning_and_reply_continues_it_at_low(monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.VOICE_REASONING_EFFORT", "low")
    pipeline = _pipeline()
    calls: list[tuple[list[dict], dict]] = []
    streams = iter([Stream("Oh, a cat!"), Stream(" What colour?")])

    async def chat(messages, stream=False, **kwargs):
        calls.append((messages, kwargs))
        return next(streams)

    pipeline.llm.chat = AsyncMock(side_effect=chat)
    ws = FakeWS()
    await pipeline.handle_audio(b"utterance", ws, provisional=True)
    await _settle()

    opener_messages, opener_kwargs = calls[0]
    assert opener_kwargs["reasoning_effort"] == "none"
    assert opener_kwargs["max_tokens"] <= 32
    assert "tools" not in opener_kwargs
    assert "2-5 words" in opener_messages[-1]["content"]
    assert "I have a cat" in opener_messages[-1]["content"]

    reply_messages, reply_kwargs = calls[1]
    assert reply_kwargs["reasoning_effort"] == "low"
    assert reply_messages[-2:] == [
        {"role": "user", "content": "I have a cat"},
        {"role": "assistant", "content": "Oh, a cat!"},
    ]
    assert reply_kwargs["fallback_messages"][-1] == reply_messages[-1]


@pytest.mark.asyncio
async def test_tagged_opener_is_swedish_and_prefilled_with_its_tag() -> None:
    pipeline = _pipeline(
        native_language="sv",
        target_language="en-GB",
    )
    pipeline._tagged_lines = True
    calls: list[list[dict]] = []
    streams = iter([Stream("[sv] Åh, en katt!"), Stream("[sv] Vilken färg?")])

    async def chat(messages, stream=False, **kwargs):
        calls.append(messages)
        return next(streams)

    pipeline.llm.chat = AsyncMock(side_effect=chat)
    ws = FakeWS()
    await pipeline.handle_audio(b"utterance", ws, provisional=True)
    await _settle()
    await pipeline._confirm_provisional(ws)
    await pipeline.current_task

    assert calls[1][-1] == {"role": "assistant", "content": "[sv] Åh, en katt!"}
    assert ws.audio() == [b"\xc3\x85h, en katt!", "Vilken färg?".encode()]
    assert pipeline.history[-1]["content"] == "[sv] Åh, en katt!\n[sv] Vilken färg?"


@pytest.mark.asyncio
async def test_opener_failure_falls_back_to_a_plain_reply() -> None:
    from app.services.llm_adapter import LLMError

    pipeline = _pipeline()
    calls: list[list[dict]] = []

    async def chat(messages, stream=False, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            raise LLMError("no opener")
        return Stream("Hello there.")

    pipeline.llm.chat = AsyncMock(side_effect=chat)
    ws = FakeWS()
    await pipeline.handle_audio(b"utterance", ws, provisional=True)
    await _settle()
    await pipeline._confirm_provisional(ws)
    await pipeline.current_task

    assert calls[1][-1]["role"] == "user"
    assert ws.audio() == [b"Hello there."]


@pytest.mark.asyncio
async def test_opener_without_audio_is_not_prefilled() -> None:
    pipeline = _pipeline()
    pipeline.tts.synthesize = AsyncMock(
        side_effect=lambda text, *_: (_ for _ in ()).throw(RuntimeError("tts"))
        if text.startswith("Oh")
        else text.encode()
    )
    calls: list[list[dict]] = []
    streams = iter([Stream("Oh, a cat!"), Stream("Reply one.")])

    async def chat(messages, stream=False, **kwargs):
        calls.append(messages)
        return next(streams)

    pipeline.llm.chat = AsyncMock(side_effect=chat)
    ws = FakeWS()
    with patch("app.services.conversation_pipeline.TTS_RETRY_DELAY_SECONDS", 0):
        await pipeline.handle_audio(b"utterance", ws, provisional=True)
        await _settle()
        await pipeline._confirm_provisional(ws)
        await pipeline.current_task

    assert calls[1][-1]["role"] == "user"
    assert ws.audio() == [b"Reply one."]
    assert pipeline.history[-1]["content"] == "Reply one."


@pytest.mark.asyncio
async def test_e4b_tier_skips_opener(monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.VOICE_REASONING_EFFORT", "low")
    pipeline = _pipeline(generated_opener=False, small_llm=True)
    pipeline.llm.chat = AsyncMock(return_value=Stream("Hello there."))
    ws = FakeWS()
    await pipeline.handle_audio(b"utterance", ws, provisional=True)
    await _settle()
    await pipeline._confirm_provisional(ws)
    await pipeline.current_task

    pipeline.llm.chat.assert_awaited_once()
    assert "reasoning_effort" not in pipeline.llm.chat.await_args.kwargs
    assert ws.audio() == [b"Hello there."]


@pytest.mark.asyncio
async def test_opener_runs_without_a_provisional_step() -> None:
    """A short user pause skips the provisional step, not the opener."""
    pipeline = _pipeline()
    ws = FakeWS()
    await pipeline.handle_audio(b"utterance", ws)
    await pipeline.current_task
    assert ws.audio() == [b"Oh, a cat!", b"What colour is it?"]


@pytest.mark.asyncio
async def test_provisional_cancels_a_running_turn_without_barge_in() -> None:
    pipeline = _pipeline()
    pipeline.current_task = asyncio.create_task(asyncio.Event().wait())
    pipeline.llm.chat = AsyncMock(side_effect=[Stream("Oh, a cat!"), Stream("Reply.")])
    ws = FakeWS()
    await pipeline.handle_audio(b"utterance", ws, provisional=True)
    await _settle()
    assert ws.jsons("barge_in") == []


@pytest.mark.asyncio
async def test_new_provisional_replaces_the_pending_one() -> None:
    pipeline = _pipeline()
    pipeline.llm.chat = AsyncMock(
        side_effect=[
            Stream("Oh, a cat!"),
            HangingStream(),
            Stream("Oh, two cats!"),
            Stream(" Lovely."),
        ]
    )
    ws = FakeWS()
    await pipeline.handle_audio(b"first", ws, provisional=True)
    await _settle()
    first = pipeline._provisional
    await pipeline.handle_audio(b"first and second", ws, provisional=True)
    await _settle()

    assert pipeline._provisional is not first
    await pipeline._confirm_provisional(ws)
    await pipeline.current_task
    assert ws.audio() == [b"Oh, two cats!", b"Lovely."]
    assert ws.jsons("barge_in") == []


@pytest.mark.asyncio
async def test_run_dispatches_provisional_confirm_and_abort() -> None:
    pipeline = _pipeline()
    pipeline._greet = AsyncMock()
    pipeline.llm.chat = AsyncMock(side_effect=[Stream("Oh, a cat!"), Stream(" Colour?")])
    messages: asyncio.Queue[dict] = asyncio.Queue()
    ws = FakeWS()
    ws.receive = messages.get  # type: ignore[attr-defined]
    runner = asyncio.create_task(pipeline.run(ws))

    await messages.put({"text": '{"type": "provisional"}'})
    await messages.put({"bytes": b"utterance"})
    await _settle()
    assert ws.sent == []

    await messages.put({"text": '{"type": "confirm"}'})
    await _settle()
    await pipeline.current_task
    assert ws.audio()

    await messages.put({"type": "websocket.disconnect"})
    await runner


@pytest.mark.asyncio
async def test_live_llm_is_small_only_when_shared() -> None:
    for state, expected in [("shared", True), ("ready", False), ("away", False), ("off", False)]:
        with patch.object(
            speech_session, "_gateway", AsyncMock(return_value=SpeechSessionState(state=state))
        ) as gateway:
            assert await live_llm_is_small() is expected
            gateway.assert_awaited_once_with("GET", "/session/status")


@pytest.mark.asyncio
async def test_adapter_passes_max_tokens_for_the_local_provider() -> None:
    adapter = LLMAdapter.__new__(LLMAdapter)
    adapter.provider = "ollama"
    adapter.model = "gemma"
    adapter.client = MagicMock()
    adapter.client.chat.completions.create = AsyncMock(return_value=MagicMock())
    await adapter._do_chat([{"role": "user", "content": "hi"}], True, None, max_tokens=24)
    assert adapter.client.chat.completions.create.await_args.kwargs["max_tokens"] == 24


def test_tool_continuation_merges_a_prefilled_assistant_message() -> None:
    adapter = LLMAdapter.__new__(LLMAdapter)
    adapter.provider = "ollama"
    call = _memory_call()
    result = LLMToolResult(call=call, content={"saved": True})

    continuation = adapter._build_tool_continuation(
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Oh, a cat!"}],
        " Great.",
        [call],
        [result],
    )

    assert [m["role"] for m in continuation] == ["user", "assistant", "tool"]
    assert continuation[1]["content"] == "Oh, a cat! Great."
    assert continuation[1]["tool_calls"][0]["id"] == "c1"
