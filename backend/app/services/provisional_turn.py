"""A voice turn that stays invisible until the child's pause is confirmed.

A provisional turn runs the whole pipeline early, but its output is held here:
socket frames are buffered, memory writes and usage are queued. ``confirm``
releases them in order; an aborted turn is simply dropped.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.services.llm_adapter import LLMToolCall, LLMToolResult

if TYPE_CHECKING:
    from fastapi import WebSocket

OPENER_MAX_TOKENS = 24
OPENER_INSTRUCTION = (
    "[First say only the opening of your reply: 2-5 words reacting to the topic of what I just "
    "said. No judgement, no praise, no correction, no teaching. Use the language your reply "
    "starts in. Send only those words.]"
)
TAGGED_OPENER_INSTRUCTION = (
    "[First say only the opening of your reply: 2-5 words in Swedish reacting to the topic of "
    "what I just said. No judgement, no praise, no correction, no teaching. Send only one line "
    "tagged [sv].]"
)


def build_opener_messages(messages: list[dict], *, tagged: bool) -> list[dict]:
    """The reply's message list, with the opener request added to the student's last turn."""
    instruction = TAGGED_OPENER_INSTRUCTION if tagged else OPENER_INSTRUCTION
    last = messages[-1]
    return [*messages[:-1], {**last, "content": f"{last['content']}\n\n{instruction}"}]


class ProvisionalTurn:
    """Stands in for the WebSocket during a provisional turn and holds its side effects."""

    def __init__(self, ws: WebSocket, send_lock: asyncio.Lock) -> None:
        self._ws = ws
        self._send_lock = send_lock
        self._frames: list[tuple[bool, object]] = []
        self._memory_calls: list[LLMToolCall] = []
        self._usage_streams: list[object] = []
        self._confirmed = asyncio.Event()
        self.turn_id = 0

    @property
    def confirmed(self) -> bool:
        return self._confirmed.is_set()

    # The pipeline already holds ``send_lock`` around these two.
    async def send_json(self, data: dict) -> None:
        if self.confirmed:
            await self._ws.send_json(data)
        else:
            self._frames.append((False, data))

    async def send_bytes(self, data: bytes) -> None:
        if self.confirmed:
            await self._ws.send_bytes(data)
        else:
            self._frames.append((True, data))

    def hold_memory_call(self, call: LLMToolCall) -> LLMToolResult:
        """Queue a memory write. The model is told it is queued, not saved."""
        self._memory_calls.append(call)
        return LLMToolResult(call=call, content={"queued": True})

    def hold_usage(self, stream: object) -> None:
        self._usage_streams.append(stream)

    async def confirm(self) -> tuple[list[LLMToolCall], list[object]]:
        """Send every held frame in order and return the held memory calls and usage."""
        async with self._send_lock:
            for is_bytes, frame in self._frames:
                await (self._ws.send_bytes(frame) if is_bytes else self._ws.send_json(frame))
            self._frames = []
            self._confirmed.set()
        return self._memory_calls, self._usage_streams

    async def wait_confirmed(self) -> None:
        await self._confirmed.wait()
