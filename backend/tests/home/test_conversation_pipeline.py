"""Home voice conversation: tagged spoken lines, streamed speech, reasoning effort and redo."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.home import conversation as home_conversation
from app.home.conversation import HomeConversationPipeline, build_pipeline
from app.services.llm_adapter import LLMStreamReset
from tests.test_conversation_pipeline_service import FakeWS, _make_chunk


def _make_pipeline(**kwargs) -> HomeConversationPipeline:
    defaults = {"max_duration": 1800, "inactivity_timeout": 180}
    defaults.update(kwargs)
    return HomeConversationPipeline(
        llm=AsyncMock(),
        tts=AsyncMock(),
        stt=AsyncMock(),
        cefr_level="B1",
        **defaults,
    )


# ---------------------------------------------------------------------------
# build_pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_pipeline_returns_home_pipeline(monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "ollama")
    monkeypatch.setattr(home_conversation, "live_llm_is_small", AsyncMock(return_value=True))

    pipeline = await build_pipeline(
        llm=AsyncMock(),
        tts=AsyncMock(),
        stt=AsyncMock(),
        cefr_level="B1",
        target_language="en-GB",
    )

    assert isinstance(pipeline, HomeConversationPipeline)
    assert pipeline._small_llm is True
    assert pipeline._generated_opener is False


# ---------------------------------------------------------------------------
# Tagged spoken lines (Swedish native, A1/A2)
# ---------------------------------------------------------------------------


def _tagged_pipeline() -> HomeConversationPipeline:
    return HomeConversationPipeline(
        llm=AsyncMock(),
        tts=AsyncMock(),
        stt=AsyncMock(),
        cefr_level="A1",
        native_language="sv",
        target_language="en-GB",
        max_duration=1800,
        inactivity_timeout=180,
    )


def _stream_of(text: str):
    async def gen():
        yield _make_chunk(text)

    return gen()


def _assistant_updates(ws: FakeWS) -> list[dict]:
    """Every assistant transcript message, partial (final false) and final."""
    return [
        m
        for m in ws.json_messages()
        if m.get("type") == "transcript" and m.get("role") == "assistant"
    ]


def _assistant_transcripts(ws: FakeWS) -> list[dict]:
    return [m for m in _assistant_updates(ws) if m["final"]]


@pytest.mark.asyncio
async def test_pipeline_speaks_each_line_in_its_language() -> None:
    pipeline = _tagged_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hej")
    calls: list[tuple[str, str | None]] = []

    async def synth(text, voice, lang):
        calls.append((text, lang))
        return b"audio"

    pipeline.tts.synthesize = synth
    pipeline.llm.chat = AsyncMock(
        return_value=_stream_of("[sv] Säg så här.\n[en] Good morning.\n[screen] God morgon")
    )
    ws = FakeWS()
    await pipeline._process(b"audio", ws)

    assert calls == [("Säg så här.", "sv"), ("Good morning.", "en")]
    assert _assistant_transcripts(ws)[0]["text"] == "Säg så här. Good morning. God morgon"
    assert pipeline.history[-1]["content"] == (
        "[sv] Säg så här.\n[en] Good morning.\n[screen] God morgon"
    )
    assert "turn_complete" in ws.types()


@pytest.mark.asyncio
async def test_pipeline_rewrites_once_then_moves_to_screen() -> None:
    pipeline = _tagged_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hej")
    calls: list[tuple[str, str | None]] = []

    async def synth(text, voice, lang):
        calls.append((text, lang))
        return b"audio"

    pipeline.tts.synthesize = synth
    pipeline.llm.chat = AsyncMock(
        side_effect=[
            _stream_of('[sv] Ordet "apple" betyder äpple.\n[sv] Bra!'),
            _stream_of('[sv] Säg "apple" nu.\n[sv] Bra!'),
        ]
    )
    ws = FakeWS()
    await pipeline._process(b"audio", ws)

    assert pipeline.llm.chat.await_count == 2
    rewrite_messages = pipeline.llm.chat.await_args_list[1].args[0]
    assert rewrite_messages[-2]["role"] == "assistant"
    assert rewrite_messages[-1]["role"] == "user"
    assert calls == [("Bra!", "sv")]
    assert _assistant_transcripts(ws)[0]["text"] == 'Säg "apple" nu. Bra!'


@pytest.mark.asyncio
async def test_pipeline_rewrite_that_fixes_the_line_is_spoken() -> None:
    pipeline = _tagged_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hej")
    calls: list[tuple[str, str | None]] = []

    async def synth(text, voice, lang):
        calls.append((text, lang))
        return b"audio"

    pipeline.tts.synthesize = synth
    pipeline.llm.chat = AsyncMock(
        side_effect=[
            _stream_of('[sv] Ordet "apple" betyder äpple.'),
            _stream_of("[sv] Nu ska du säga ordet.\n[en] Apple."),
        ]
    )
    ws = FakeWS()
    await pipeline._process(b"audio", ws)

    assert calls == [("Nu ska du säga ordet.", "sv"), ("Apple.", "en")]


@pytest.mark.asyncio
async def test_pipeline_all_screen_reply_completes_without_audio() -> None:
    pipeline = _tagged_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hej")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")
    pipeline.llm.chat = AsyncMock(return_value=_stream_of("[screen] Rätt: I am"))
    ws = FakeWS()
    await pipeline._process(b"audio", ws)

    pipeline.tts.synthesize.assert_not_awaited()
    assert [kind for kind, _ in ws.sent].count("bytes") == 0
    assert _assistant_transcripts(ws)[0]["text"] == "Rätt: I am"
    assert "turn_complete" in ws.types()
    assert not [m for m in ws.json_messages() if m.get("type") == "error"]


@pytest.mark.asyncio
async def test_tts_failure_on_one_line_still_sends_transcript() -> None:
    pipeline = _tagged_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hej")

    async def synth(text, voice, lang):
        if lang == "en":
            raise RuntimeError("TTS unavailable")
        return b"audio"

    pipeline.tts.synthesize = synth
    pipeline.llm.chat = AsyncMock(return_value=_stream_of("[en] Hello.\n[sv] Bra!"))
    ws = FakeWS()
    await pipeline._process(b"audio", ws)

    assert [kind for kind, _ in ws.sent].count("bytes") == 1
    assert _assistant_transcripts(ws)[0]["text"] == "Hello. Bra!"
    assert "turn_complete" in ws.types()


@pytest.mark.asyncio
@pytest.mark.parametrize(("level", "native"), [("B1", "sv"), ("A1", "es")])
async def test_tagging_not_applied_at_b1_or_for_other_native_language(level, native) -> None:
    pipeline = HomeConversationPipeline(
        llm=AsyncMock(),
        tts=AsyncMock(),
        stt=AsyncMock(),
        cefr_level=level,
        native_language=native,
        target_language="en-GB",
    )
    pipeline.stt.transcribe = AsyncMock(return_value="Hej")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")
    pipeline.llm.chat = AsyncMock(return_value=_stream_of("[sv] Hello there."))
    ws = FakeWS()
    await pipeline._process(b"audio", ws)
    pipeline.tts.synthesize.assert_awaited_once_with("[sv] Hello there.", None, "en-GB")
    assert pipeline.llm.chat.await_count == 1


@pytest.mark.asyncio
async def test_empty_reply_retried_once() -> None:
    pipeline = _tagged_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hej")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")
    pipeline.llm.chat = AsyncMock(side_effect=[_stream_of("  "), _stream_of("[sv] Hej!")])
    ws = FakeWS()
    await pipeline._process(b"audio", ws)

    assert pipeline.llm.chat.await_count == 2
    assert (
        pipeline.llm.chat.await_args_list[1].args[0] == pipeline.llm.chat.await_args_list[0].args[0]
    )
    assert _assistant_transcripts(ws)[0]["text"] == "Hej!"
    assert "turn_complete" in ws.types()


@pytest.mark.asyncio
async def test_empty_reply_twice_shows_nothing() -> None:
    pipeline = _tagged_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hej")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")
    pipeline.llm.chat = AsyncMock(side_effect=[_stream_of(""), _stream_of("[sv]")])
    ws = FakeWS()
    await pipeline._process(b"audio", ws)

    assert pipeline.llm.chat.await_count == 2
    assert _assistant_transcripts(ws) == []
    assert [m["code"] for m in ws.json_messages() if m.get("type") == "error"] == ["llm_failed"]
    assert "turn_complete" not in ws.types()
    assert not [kind for kind, _ in ws.sent if kind == "bytes"]
    assert all(m["role"] != "assistant" for m in pipeline.history)


@pytest.mark.asyncio
async def test_history_keeps_tags_for_next_turn() -> None:
    pipeline = _tagged_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hej")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")
    pipeline.llm.chat = AsyncMock(
        side_effect=[_stream_of("[sv] Säg så här.\n[en] Good morning."), _stream_of("[sv] Bra!")]
    )
    ws = FakeWS()
    await pipeline._process(b"audio", ws)
    await pipeline._process(b"audio", ws)

    second_messages = pipeline.llm.chat.await_args_list[1].args[0]
    assert {
        "role": "assistant",
        "content": "[sv] Säg så här.\n[en] Good morning.",
    } in second_messages
    assert _assistant_transcripts(ws)[0]["text"] == "Säg så här. Good morning."


# ---------------------------------------------------------------------------
# Streamed speech
# ---------------------------------------------------------------------------


def _audio_count(ws: FakeWS) -> int:
    return [kind for kind, _ in ws.sent].count("bytes")


@pytest.mark.asyncio
async def test_first_line_audio_before_stream_ends() -> None:
    pipeline = _tagged_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hej")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")
    ws = FakeWS()
    audio_when_second_line_requested: list[int] = []

    async def gen():
        yield _make_chunk("[sv] Hej där.\n[en] Hel")
        audio_when_second_line_requested.append(_audio_count(ws))
        yield _make_chunk("lo.\n[sv] Bra!")

    pipeline.llm.chat = AsyncMock(return_value=gen())
    await pipeline._process(b"audio", ws)

    assert audio_when_second_line_requested == [1]
    assert [c.args for c in pipeline.tts.synthesize.await_args_list] == [
        ("Hej där.", None, "sv"),
        ("Hello.", None, "en"),
        ("Bra!", None, "sv"),
    ]
    assert _assistant_transcripts(ws)[0]["text"] == "Hej där. Hello. Bra!"
    assert pipeline.history[-1]["content"] == "[sv] Hej där.\n[en] Hello.\n[sv] Bra!"
    assert "turn_complete" in ws.types()


@pytest.mark.asyncio
async def test_transcript_visible_after_first_audio_before_stream_ends() -> None:
    pipeline = _make_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hi")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")
    ws = FakeWS()
    seen: list[list[dict]] = []

    async def gen():
        yield _make_chunk("First sentence. Seco")
        seen.append(_assistant_updates(ws))
        yield _make_chunk("nd one.")

    pipeline.llm.chat = AsyncMock(return_value=gen())
    await pipeline._process(b"audio", ws)

    assert [(m["text"], m["final"]) for m in seen[0]] == [("First sentence.", False)]
    kinds = [(m["text"], m["final"]) for m in _assistant_updates(ws)]
    assert kinds[-1] == ("First sentence. Second one.", True)
    first_audio = next(i for i, (k, _) in enumerate(ws.sent) if k == "bytes")
    first_text = next(
        i for i, (k, d) in enumerate(ws.sent) if k == "json" and d.get("role") == "assistant"
    )
    assert first_audio < first_text


@pytest.mark.asyncio
async def test_untagged_sentence_audio_before_stream_ends() -> None:
    pipeline = _make_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hi")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")
    ws = FakeWS()
    seen: list[int] = []

    async def gen():
        yield _make_chunk("First sentence. Seco")
        seen.append(_audio_count(ws))
        yield _make_chunk("nd one")
        seen.append(_audio_count(ws))
        yield _make_chunk(".")

    pipeline.llm.chat = AsyncMock(return_value=gen())
    await pipeline._process(b"audio", ws)

    assert seen == [1, 1]
    assert [c.args[0] for c in pipeline.tts.synthesize.await_args_list] == [
        "First sentence.",
        "Second one.",
    ]
    assert _assistant_transcripts(ws)[0]["text"] == "First sentence. Second one."


@pytest.mark.asyncio
async def test_stream_splits_long_sentence() -> None:
    pipeline = _make_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hi")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")
    ws = FakeWS()
    first = "word " * 20 + "one, "
    second = "word " * 10 + "two, "
    third = "word " * 8 + "end."
    seen: list[int] = []

    async def gen():
        yield _make_chunk(first)
        yield _make_chunk(second)
        seen.append(_audio_count(ws))
        yield _make_chunk(third)

    pipeline.llm.chat = AsyncMock(return_value=gen())
    await pipeline._process(b"audio", ws)

    texts = [c.args[0] for c in pipeline.tts.synthesize.await_args_list]
    assert seen == [1]
    assert len(texts) >= 2
    assert texts[0].endswith("one,")
    assert all(len(text) <= 140 + 30 for text in texts)
    assert " ".join(texts) == (first + second + third).strip()


@pytest.mark.asyncio
async def test_invalid_line_after_audio_goes_to_screen_without_rewrite() -> None:
    pipeline = _tagged_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hej")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")
    pipeline.llm.chat = AsyncMock(
        return_value=_stream_of('[sv] Hej!\n[sv] Ordet "apple" betyder äpple.\n[sv] Bra!')
    )
    ws = FakeWS()
    await pipeline._process(b"audio", ws)

    assert pipeline.llm.chat.await_count == 1
    assert [c.args[0] for c in pipeline.tts.synthesize.await_args_list] == ["Hej!", "Bra!"]
    assert _assistant_transcripts(ws)[0]["text"] == 'Hej! Ordet "apple" betyder äpple. Bra!'
    assert pipeline.history[-1]["content"] == (
        '[sv] Hej!\n[screen] Ordet "apple" betyder äpple.\n[sv] Bra!'
    )


@pytest.mark.asyncio
async def test_reset_after_audio_keeps_played_text_and_speaks_new_reply() -> None:
    pipeline = _make_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hi")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")

    async def gen():
        yield "Old played sentence. Old unspoken tail"
        yield LLMStreamReset()
        yield "New reply."

    pipeline.llm.chat = AsyncMock(return_value=gen())
    ws = FakeWS()
    await pipeline._process(b"audio", ws)

    assert [c.args[0] for c in pipeline.tts.synthesize.await_args_list] == [
        "Old played sentence.",
        "New reply.",
    ]
    assert _assistant_transcripts(ws)[0]["text"] == "Old played sentence. New reply."
    assert "turn_complete" in ws.types()


@pytest.mark.asyncio
async def test_reset_before_audio_discards_everything_old() -> None:
    pipeline = _make_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hi")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")

    async def gen():
        yield "Old unfinished"
        yield LLMStreamReset()
        yield "New reply."

    pipeline.llm.chat = AsyncMock(return_value=gen())
    ws = FakeWS()
    await pipeline._process(b"audio", ws)

    assert [c.args[0] for c in pipeline.tts.synthesize.await_args_list] == ["New reply."]
    assert _assistant_transcripts(ws)[0]["text"] == "New reply."


@pytest.mark.asyncio
async def test_voice_reply_requests_configured_reasoning_effort(monkeypatch) -> None:
    monkeypatch.setattr("app.home.settings.home_settings.VOICE_REASONING_EFFORT", "low")
    pipeline = _make_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hi")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")
    pipeline.llm.chat = AsyncMock(return_value=_stream_of("Hello."))
    await pipeline._process(b"audio", FakeWS())
    assert pipeline.llm.chat.call_args.kwargs["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_voice_reply_sends_no_reasoning_effort_when_unset(monkeypatch) -> None:
    monkeypatch.setattr("app.home.settings.home_settings.VOICE_REASONING_EFFORT", "")
    pipeline = _make_pipeline()
    pipeline.stt.transcribe = AsyncMock(return_value="Hi")
    pipeline.tts.synthesize = AsyncMock(return_value=b"audio")
    pipeline.llm.chat = AsyncMock(return_value=_stream_of("Hello."))
    await pipeline._process(b"audio", FakeWS())
    assert "reasoning_effort" not in pipeline.llm.chat.call_args.kwargs


# ---------------------------------------------------------------------------
# discard_last_turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discard_last_turn_removes_history_and_rows(db_session, test_engine) -> None:
    from contextlib import asynccontextmanager

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.security import hash_password
    from app.models.chat_history import ChatHistory
    from app.models.conversation import Conversation
    from app.models.user import User

    user = User(
        username="discardtest",
        email="discard@test.com",
        display_name="Discard Test",
        hashed_password=hash_password("test"),
        role="user",
        native_language="es",
        target_language="en-US",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    conv = Conversation(user_id=user.id, title="Test Conv", study_plan_id=None)
    db_session.add(conv)
    await db_session.commit()

    pipeline = _make_pipeline(user_id=user.id, conversation_id=conv.id)
    pipeline.history = [
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "earlier reply"},
        {"role": "user", "content": "misheard"},
        {"role": "assistant", "content": "wrong answer"},
    ]
    pipeline._has_finished_turn = True

    @asynccontextmanager
    async def test_db():
        async with async_sessionmaker(test_engine, expire_on_commit=False)() as session:
            yield session

    with (
        patch("app.services.conversation_pipeline.db_session", test_db),
        patch("app.services.conversation_pipeline.record_lingu_practice", AsyncMock()),
    ):
        pipeline._last_turn_save = asyncio.create_task(
            pipeline._save_turn(
                "misheard",
                "wrong answer",
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await pipeline._last_turn_save
        rows = (await db_session.scalars(select(ChatHistory))).all()
        assert len(rows) == 2

        await pipeline.discard_last_turn()

    assert pipeline.history == [
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "earlier reply"},
    ]
    db_session.expire_all()
    assert (await db_session.scalars(select(ChatHistory))).all() == []


@pytest.mark.asyncio
async def test_discard_with_no_turn_is_noop() -> None:
    pipeline = _make_pipeline()
    pipeline.history = [{"role": "assistant", "content": "greeting"}]

    await pipeline.discard_last_turn()

    assert pipeline.history == [{"role": "assistant", "content": "greeting"}]


@pytest.mark.asyncio
async def test_run_routes_discard_client_event() -> None:
    pipeline = _make_pipeline()
    pipeline._greet = AsyncMock(return_value=None)
    pipeline.discard_last_turn = AsyncMock(return_value=None)
    ws = FakeWS()
    ws.receive = AsyncMock(
        side_effect=[
            {"text": '{"type": "client_event", "event": "discard_last_turn"}'},
            {"type": "websocket.disconnect"},
        ]
    )

    await pipeline.run(ws)

    pipeline.discard_last_turn.assert_awaited_once()


@pytest.mark.asyncio
async def test_discard_during_running_turn_keeps_previous_turn() -> None:
    pipeline = _make_pipeline()
    previous = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "first reply"},
    ]
    pipeline.history = list(previous)
    pipeline._has_finished_turn = True

    async def slow_turn(audio_bytes, ws) -> None:
        pipeline.history.append({"role": "user", "content": "second"})
        await asyncio.sleep(10)

    pipeline._process_turn = slow_turn
    await pipeline.handle_audio(b"audio", FakeWS())
    await asyncio.sleep(0.01)

    await pipeline.discard_last_turn()

    assert pipeline.history == previous
