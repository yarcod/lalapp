"""Home voice conversation: the upstream pipeline plus everything the home deployment adds.

``HomeConversationPipeline`` speaks a reply while it streams, runs provisional turns that stay
invisible until the child's pause is confirmed, opens with a few generated words, speaks tagged
Swedish/target-language lines in their own voices, splits long sentences, asks for a reasoning
effort, and can forget the last turn. It plugs into the small extension points of
``ConversationPipeline`` (``_chat``, ``_reply_text``, ``_add_reply``, ``_record_usage``,
``_tts_items``, ``handle_control`` and the ``language`` of ``_synthesize_chunk``).
"""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.core.app_logger import get_logger
from app.core.config import settings
from app.home.provisional_turn import (
    OPENER_MAX_TOKENS,
    ProvisionalTurn,
    build_opener_messages,
)
from app.home.settings import home_settings
from app.home.speech_session import live_llm_is_small
from app.home.spoken_lines import (
    SCREEN,
    SWEDISH,
    SpokenLine,
    display_text,
    invalid_swedish_lines,
    parse_reply,
    tagged_replies_enabled,
)
from app.services import conversation_pipeline as upstream
from app.services.conversation_pipeline import (
    ConversationPipeline,
    _build_conversation_system_prompt,
)
from app.services.language_helpers import get_iso639
from app.services.llm_adapter import (
    LLMError,
    LLMStreamReset,
    LLMToolCall,
    LLMToolResult,
    LLMToolResultEvent,
)

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = get_logger(__name__)

REWRITE_REQUEST = (
    "Rewrite your last reply. Every [sv] line must be plain Swedish with no English or Spanish "
    "words and no quoted words. Put target-language words on their own [en] or [es] line, or on a "
    "[screen] line. Keep the same tags and send only the rewritten reply."
)

# A sentence longer than this is spoken in fragments cut at clause punctuation.
LONG_SENTENCE_CHARS = 140
_CLAUSE_RE = re.compile(r"[,;:–—](?=\s)")

MemoryExecutor = Callable[[LLMToolCall], Awaitable[LLMToolResult]]


def _pop_sentences(text: str, *, final: bool) -> tuple[list[str], str]:
    """Split complete sentences off ``text`` on full stops.

    Decimals and ellipses stay inside a sentence. While the text may still
    grow (``final`` false), a full stop at its very end is held back, since
    the next character decides whether it ends the sentence.
    """
    chunks: list[str] = []
    start = 0
    for idx, char in enumerate(text):
        if char != ".":
            continue
        if idx + 1 >= len(text) and not final:
            break
        if (idx > 0 and text[idx - 1] == ".") or (idx + 1 < len(text) and text[idx + 1] == "."):
            continue
        if (
            idx > 0
            and idx + 1 < len(text)
            and text[idx - 1].isdecimal()
            and text[idx + 1].isdecimal()
        ):
            continue
        sentence = text[start : idx + 1].strip()
        if sentence:
            chunks.append(sentence)
        start = idx + 1
    return chunks, text[start:]


def _clause_cut(text: str) -> int | None:
    """Where to cut an over-long sentence: after the last clause mark within the limit,
    else after the first one beyond it."""
    marks = [match.end() for match in _CLAUSE_RE.finditer(text)]
    within = [end for end in marks if end <= LONG_SENTENCE_CHARS]
    if within:
        return within[-1]
    return marks[0] if marks else None


def _split_long(text: str) -> list[str]:
    """Break a sentence longer than the limit at clause punctuation."""
    pieces: list[str] = []
    rest = text.strip()
    while len(rest) > LONG_SENTENCE_CHARS:
        cut = _clause_cut(rest)
        if cut is None or not rest[:cut].strip() or not rest[cut:].strip():
            break
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    pieces.append(rest)
    return pieces


class _StreamedSpeech:
    """Speaks a reply while it streams: each finished sentence, or tagged line, in order.

    A line that fails validation after audio has started goes to ``[screen]``.
    Before any audio, the tagged path instead stops speaking (``buffered``) so the
    caller can rewrite the whole reply as it always did.
    """

    def __init__(
        self,
        pipeline: HomeConversationPipeline,
        ws: WebSocket,
        *,
        tagged: bool,
        target_code: str,
        turn_id: int,
    ) -> None:
        self._turn_id = turn_id
        self._heard: list[str] = []
        self._pipeline = pipeline
        self._ws = ws
        self._tagged = tagged
        self._target_code = target_code
        self.full_response = ""
        self.lines: list[SpokenLine] = []
        self.buffered = False
        self.chunks_sent = 0
        self.audio_bytes = 0
        self.send_aborted = False
        self._buffer = ""
        self._trim_next_token = False

    async def speak_opener(self, text: str) -> str | None:
        """Speak the generated opener. Returns the assistant prefill, or None if it wasn't heard."""
        if self._tagged:
            lines = parse_reply(text, self._target_code)
            line = next((item for item in lines if item.spoken), None)
            if line is None or line.language != SWEDISH or invalid_swedish_lines([line]):
                return None
            self.lines.append(line)
            spoken, prefill = line.text, f"[{SWEDISH}] {line.text}"
        else:
            spoken = text.strip()
            prefill = spoken
        if not spoken:
            return None
        await self._speak_sentence(spoken, SWEDISH if self._tagged else None)
        if self.chunks_sent == 0:
            self.reset()
            return None
        self.full_response = f"{prefill}\n" if self._tagged else prefill
        self._trim_next_token = not self._tagged
        return prefill

    def reset(self) -> None:
        """The model restarted its reply. Audio that already played is kept."""
        if self.chunks_sent == 0:
            self.full_response = ""
            self.lines = []
            self._heard = []
            self.buffered = False
        else:
            self.full_response = self.full_response[: len(self.full_response) - len(self._buffer)]
            if self.full_response and not self.full_response[-1].isspace():
                self.full_response += " "
        self._buffer = ""

    async def feed(self, token: str) -> None:
        if self._trim_next_token and token:
            # The reply carries on from the opener after one space.
            token = f" {token.lstrip()}" if token.strip() else ""
            self._trim_next_token = not token
        self.full_response += token
        if self.buffered or self.send_aborted:
            return
        self._buffer += token
        await self._drain(final=False)

    async def finish(self) -> None:
        if not (self.buffered or self.send_aborted):
            await self._drain(final=True)

    async def _drain(self, *, final: bool) -> None:
        if self._tagged:
            while "\n" in self._buffer and not (self.buffered or self.send_aborted):
                line, self._buffer = self._buffer.split("\n", 1)
                await self._line(line)
            if final and self._buffer.strip() and not (self.buffered or self.send_aborted):
                line, self._buffer = self._buffer, ""
                await self._line(line)
            return
        sentences, self._buffer = _pop_sentences(self._buffer, final=final)
        if final and self._buffer.strip():
            sentences.append(self._buffer.strip())
            self._buffer = ""
        for sentence in sentences:
            await self._speak_sentence(sentence, None)
        while not final and len(self._buffer.strip()) > LONG_SENTENCE_CHARS:
            cut = _clause_cut(self._buffer.lstrip())
            if cut is None:
                break
            text = self._buffer.lstrip()
            self._buffer = text[cut:]
            await self._speak_sentence(text[:cut], None)

    async def _line(self, raw: str) -> None:
        for line in parse_reply(raw, self._target_code):
            if line.spoken and invalid_swedish_lines([line]):
                if self.chunks_sent == 0:
                    self.buffered = True
                    return
                line.language = SCREEN
                line.spoken = False
            self.lines.append(line)
            if line.spoken:
                await self._speak_sentence(line.text, line.language)

    async def _speak_sentence(self, text: str, language: str | None) -> None:
        for sentence in ConversationPipeline._split_tts_sentences(text):
            self._heard.append(sentence)
            for piece in _split_long(sentence):
                await self._speak(piece, language)

    async def _speak(self, text: str, language: str | None) -> None:
        if self.send_aborted or not any(char.isalnum() for char in text):
            return
        try:
            audio = await self._pipeline._synthesize_chunk(text, language)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[pipeline] TTS sentence failed after retry: error=%s", self._pipeline._fmt_exc(exc)
            )
            return
        if not await self._pipeline._safe_send_bytes(self._ws, audio):
            logger.warning("[pipeline] Audio send failed and remaining chunks are being aborted")
            self.send_aborted = True
            return
        self.chunks_sent += 1
        self.audio_bytes += len(audio)
        shown = display_text(self.lines) if self._tagged else " ".join(self._heard)
        await self._pipeline._send_json(
            self._ws,
            {
                "type": "transcript",
                "role": "assistant",
                "text": shown,
                "final": False,
                "turn_id": self._turn_id,
            },
        )


class _SpokenStream:
    """The reply stream as the base pipeline reads it, feeding each token to the speech first.

    Attribute reads (``tool_results``, ``tools_unsupported``, usage) go to the provider stream.
    """

    def __init__(self, stream: object, speech: _StreamedSpeech) -> None:
        self.stream = stream
        self._speech = speech

    def __getattr__(self, name: str) -> object:
        if name == "stream":
            raise AttributeError(name)
        return getattr(self.stream, name)

    def __aiter__(self) -> AsyncIterator[object]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[object]:
        chunks = aiter(self.stream)
        try:
            async for chunk in chunks:
                if isinstance(chunk, LLMStreamReset):
                    self._speech.reset()
                elif not isinstance(chunk, LLMToolResultEvent):
                    await self._speech.feed(ConversationPipeline._stream_text(chunk))
                yield chunk
                if self._speech.send_aborted:
                    return
            await self._speech.finish()
        finally:
            aclose = getattr(chunks, "aclose", None)
            if aclose is not None:
                await aclose()


@dataclass
class _Reply:
    """What one reply, the greeting or a turn's, has decided so far."""

    messages: list[dict]
    speech: _StreamedSpeech | None = None
    user_message: dict | None = None  # a provisional turn's message, out of history until confirm
    lines: list[SpokenLine] | None = None
    history_text: str | None = None
    # Speak the final text afterwards: nothing was streamed, or the streamed lines were set aside.
    replay: bool = False


class HomeConversationPipeline(ConversationPipeline):
    """The upstream voice pipeline with the home deployment's speech behaviour."""

    def __init__(
        self,
        *args: Any,
        small_llm: bool = False,
        generated_opener: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        bound = inspect.signature(ConversationPipeline.__init__).bind(self, *args, **kwargs)
        bound.apply_defaults()
        self._tagged_lines = tagged_replies_enabled(
            bound.arguments["native_language"],
            bound.arguments["cefr_level"],
            self._target_language,
        )
        self._small_llm = small_llm
        self._generated_opener = generated_opener
        self._prompt_args["target_code"] = self._target_language
        self.system_prompt = _build_conversation_system_prompt(
            **self._prompt_args,
            memory_context=self._memory_context,
        )
        self._last_turn_save: asyncio.Task | None = None
        self._has_finished_turn = False
        self._last_turn_response_id: int | None = None
        self._provisional: ProvisionalTurn | None = None
        self._next_audio_provisional = False
        # The socket of the turn being processed (a ProvisionalTurn while it is held); None
        # during the greeting. Turns are serialized, so one slot is enough.
        self._turn_ws: WebSocket | ProvisionalTurn | None = None
        self._reply: _Reply | None = None
        self._commit_index: int | None = None
        self._memory_executor: MemoryExecutor | None = None

    def _current_turn(self) -> ProvisionalTurn | None:
        return self._turn_ws if isinstance(self._turn_ws, ProvisionalTurn) else None

    # --- Control frames and turns ---

    async def handle_control(self, msg: dict, ws: WebSocket) -> bool:
        kind = msg.get("type")
        if kind == "provisional":
            self._next_audio_provisional = True
            return True
        if kind == "confirm":
            await self._confirm_provisional(ws)
            return True
        if kind == "abort":
            await self._abort_provisional()
            return True
        if kind == "client_event" and msg.get("event") == "discard_last_turn":
            await self.discard_last_turn()
            return True
        return False

    async def handle_audio(
        self, audio_bytes: bytes, ws: WebSocket, *, provisional: bool = False
    ) -> None:
        provisional = provisional or self._next_audio_provisional
        self._next_audio_provisional = False
        if not provisional:
            self._provisional = None
            await super().handle_audio(audio_bytes, ws)
            return
        # A provisional turn must stay invisible until it is confirmed: no barge-in frame.
        await self.cancel_current()
        self._provisional = ProvisionalTurn(ws, self._send_lock)
        # Everything this turn sends is held by the ProvisionalTurn until it is confirmed.
        await super().handle_audio(audio_bytes, self._provisional)

    async def _process(self, audio_bytes: bytes, ws: WebSocket) -> None:
        # An interrupted or failed turn must never discard the one before it.
        if not isinstance(ws, ProvisionalTurn):
            self._has_finished_turn = False
        self._turn_ws = ws
        self._reply = None
        self._commit_index = None
        try:
            await super()._process(audio_bytes, ws)
        finally:
            index, self._commit_index = self._commit_index, None
            if index is not None and index < len(self._pending_saves):
                self._last_turn_save = self._pending_saves[index]
            self._turn_ws = None

    async def _confirm_provisional(self, ws: WebSocket) -> None:
        """The child's pause reached the end of the turn: release everything held."""
        turn, self._provisional = self._provisional, None
        if turn is None:
            logger.debug("[pipeline] Confirm with no provisional turn pending")
            return
        # The confirmed turn is now the last turn; discarding must not reach an earlier one.
        self._has_finished_turn = False
        try:
            memory_calls, usage_streams = await turn.confirm()
        except Exception as exc:
            logger.warning("[pipeline] Provisional flush failed: %s", self._fmt_exc(exc))
            return
        for stream in usage_streams:
            self._pending_saves.append(asyncio.create_task(self._save_usage(stream)))
        if memory_calls:
            self._pending_saves.append(
                asyncio.create_task(self._run_held_memory_calls(memory_calls, ws, turn.turn_id))
            )

    async def _abort_provisional(self) -> None:
        """The child kept talking: drop the provisional turn entirely."""
        if self._provisional is None:
            return
        await self.cancel_current()

    async def _run_held_memory_calls(
        self, calls: list[LLMToolCall], ws: WebSocket, turn_id: int
    ) -> None:
        executor = self._memory_executor
        if executor is None:
            return
        saved = False
        for call in calls:
            try:
                result = await executor(call)
            except Exception as exc:
                logger.warning("[pipeline] Held memory call failed: %s", self._fmt_exc(exc))
                continue
            saved = saved or result.content.get("saved") is True
        if saved:
            await self._send_memory_updated(ws, turn_id)

    async def cancel_current(self) -> None:
        self._provisional = None
        self._next_audio_provisional = False
        await super().cancel_current()

    # --- The reply ---

    def _effort_kwargs(self) -> dict:
        effort = home_settings.VOICE_REASONING_EFFORT
        return {"reasoning_effort": effort} if effort and not self._small_llm else {}

    async def _chat(self, messages: list[dict], **kwargs: object) -> object:
        kwargs.update(self._effort_kwargs())
        ws = self._turn_ws
        if ws is None:  # the greeting: no streamed speech
            self._reply = _Reply(messages=messages, replay=True)
            return await super()._chat(messages, **kwargs)
        turn = self._current_turn()
        user_message = None
        if turn is not None:
            turn.turn_id = self._turn_id
            # A provisional turn joins the history only when it is confirmed.
            user_message = self.history.pop()
        speech = _StreamedSpeech(
            self,
            ws,
            tagged=self._tagged_lines,
            target_code=get_iso639(self._target_language),
            turn_id=self._turn_id,
        )
        if self._generated_opener:
            opener = await self._generate_opener(messages)
            prefilled = await speech.speak_opener(opener) if opener else None
            if prefilled:
                prefill = {"role": "assistant", "content": prefilled}
                messages = [*messages, prefill]
                if "fallback_messages" in kwargs:
                    kwargs["fallback_messages"] = [*kwargs["fallback_messages"], prefill]
        executor = kwargs.get("tool_executor")
        if executor is not None:
            self._memory_executor = executor
            if turn is not None:
                kwargs["tool_executor"] = self._holding_executor(turn, executor)
        self._reply = _Reply(messages=messages, speech=speech, user_message=user_message)
        return _SpokenStream(await super()._chat(messages, **kwargs), speech)

    @staticmethod
    def _holding_executor(turn: ProvisionalTurn, executor: MemoryExecutor) -> MemoryExecutor:
        async def execute(call: LLMToolCall) -> LLMToolResult:
            if not turn.confirmed:
                return turn.hold_memory_call(call)
            return await executor(call)

        return execute

    async def _generate_opener(self, messages: list[dict]) -> str:
        """A few reacting words ahead of the reply. Empty when they can't be had."""
        try:
            stream = await self.llm.chat(
                build_opener_messages(messages, tagged=self._tagged_lines),
                stream=True,
                reasoning_effort="none",
                max_tokens=OPENER_MAX_TOKENS,
            )
            text = ""
            async for chunk in stream:
                text += self._stream_text(chunk)
        except LLMError as exc:
            logger.warning("[pipeline] Opener generation failed: %s", self._fmt_exc(exc))
            return ""
        self._record_usage(stream)
        return text.strip()

    def _record_usage(self, stream: object) -> None:
        if isinstance(stream, _SpokenStream):
            stream = stream.stream
        turn = self._current_turn()
        if turn is not None and not turn.confirmed:
            turn.hold_usage(stream)
            return
        super()._record_usage(stream)

    async def _collect_reply(self, messages: list[dict]) -> str:
        stream = await self.llm.chat(messages, stream=True, **self._effort_kwargs())
        text = ""
        async for chunk in stream:
            text += self._stream_text(chunk)
        return text.strip()

    @staticmethod
    def _tagged_text(lines: list[SpokenLine]) -> str:
        """Tagged reply kept in history so the model keeps tagging later turns."""
        return "\n".join(f"[{line.language}] {line.text}" for line in lines)

    async def _build_spoken_lines(self, messages: list[dict], reply: str) -> list[SpokenLine]:
        """Parse a tagged reply; ask for one rewrite of invalid Swedish, then move the rest."""
        target_code = get_iso639(self._target_language)
        lines = parse_reply(reply, target_code)
        if not lines:
            reply = await self._collect_reply(messages)
            lines = parse_reply(reply, target_code)
            if not lines:
                raise LLMError("The model returned an empty reply")
        invalid = invalid_swedish_lines(lines)
        if not invalid:
            return lines
        rewritten = ""
        try:
            rewritten = await self._collect_reply(
                [
                    *messages,
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content": REWRITE_REQUEST},
                ]
            )
        except LLMError as exc:
            logger.warning("[pipeline] Swedish rewrite failed: %s", self._fmt_exc(exc))
        if rewritten.strip():
            lines = parse_reply(rewritten.strip(), target_code)
        for line in invalid_swedish_lines(lines):
            line.language = SCREEN
            line.spoken = False
        return lines

    async def _reply_text(self, raw_text: str) -> str:
        reply = self._reply
        if reply is None:
            return await super()._reply_text(raw_text)
        speech = reply.speech
        clean = self._extract_speech_text(speech.full_response if speech else raw_text)
        if not self._tagged_lines:
            return clean
        if speech is None or speech.buffered or not speech.lines:
            # Nothing was heard yet: validate, rewrite or retry the whole reply.
            reply.lines = await self._build_spoken_lines(reply.messages, clean)
            reply.replay = True
        else:
            reply.lines = speech.lines
        reply.history_text = self._tagged_text(reply.lines)
        return display_text(reply.lines)

    def _tts_items(self, text: str) -> list[tuple[str, str | None]]:
        lines = self._reply.lines if self._reply else None
        if lines is None:
            return super()._tts_items(text)
        return [
            (sentence, line.language)
            for line in lines
            if line.spoken
            for sentence in self._split_tts_sentences(line.text)
        ]

    async def _synthesize_and_send_response(
        self,
        ws: WebSocket,
        *,
        text: str,
        turn_id: int,
        transcript_payload: dict,
    ) -> tuple[int, int, bool, bool]:
        reply = self._reply
        if reply is None or reply.replay:
            return await super()._synthesize_and_send_response(
                ws, text=text, turn_id=turn_id, transcript_payload=transcript_payload
            )
        # The reply was spoken while it streamed: only the final transcript is left.
        speech = reply.speech
        if speech.send_aborted:
            return speech.chunks_sent, speech.audio_bytes, False, True
        if speech.chunks_sent == 0:
            logger.warning(
                "[pipeline] No TTS audio produced; publishing text-only transcript: turn_id=%s",
                turn_id,
            )
        await self._send_json(ws, transcript_payload)
        return speech.chunks_sent, speech.audio_bytes, True, False

    async def _add_reply(self, text: str) -> None:
        reply = self._reply
        history_text = reply.history_text if reply and reply.history_text is not None else text
        if self._turn_ws is not None:
            turn = self._current_turn()
            if turn is not None:
                await turn.wait_confirmed()
                if reply is not None and reply.user_message is not None:
                    self.history.append(reply.user_message)
            self._has_finished_turn = True
            self._last_turn_response_id = None
            # The turn's save task is appended next; _process keeps it for discard_last_turn.
            self._commit_index = len(self._pending_saves)
        await super()._add_reply(history_text)

    # --- Redo ---

    async def _save_message(
        self,
        role: str,
        content: str,
        *,
        user_text: str | None = None,
        completed_at: datetime | None = None,
    ) -> int | None:
        response_id = await super()._save_message(
            role, content, user_text=user_text, completed_at=completed_at
        )
        if user_text is not None:
            self._last_turn_response_id = response_id
        return response_id

    async def discard_last_turn(self) -> None:
        """Forget the last finished turn: history entries and saved rows. XP is kept."""
        await self.cancel_current()
        if (
            not self._has_finished_turn
            or len(self.history) < 2
            or self.history[-1]["role"] != "assistant"
            or self.history[-2]["role"] != "user"
        ):
            return
        del self.history[-2:]
        self._has_finished_turn = False
        save, self._last_turn_save = self._last_turn_save, None
        if save is not None:
            await asyncio.gather(save, return_exceptions=True)
        response_id, self._last_turn_response_id = self._last_turn_response_id, None
        if response_id is None:
            return
        try:
            from sqlalchemy import delete, select  # noqa: PLC0415

            from app.models.chat_history import ChatHistory  # noqa: PLC0415

            async with upstream.db_session() as db:
                reply_to_id = await db.scalar(
                    select(ChatHistory.reply_to_id).where(ChatHistory.id == response_id)
                )
                ids = [response_id] if reply_to_id is None else [response_id, reply_to_id]
                for row_id in ids:  # assistant first: it references the user row
                    await db.execute(delete(ChatHistory).where(ChatHistory.id == row_id))
                await db.commit()
        except Exception:
            logger.debug("[pipeline] Failed to remove discarded turn rows — ignored")


async def build_pipeline(**kwargs: Any) -> ConversationPipeline:
    """Build the voice pipeline for one connection.

    The opener and reasoning effort depend on the live LLM tier, decided once per connection.
    """
    small_llm = await live_llm_is_small()
    return HomeConversationPipeline(
        **kwargs,
        small_llm=small_llm,
        generated_opener=settings.LLM_PROVIDER == "ollama" and not small_llm,
    )
