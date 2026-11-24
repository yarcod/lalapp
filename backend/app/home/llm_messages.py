"""Message order and per-job options for requests to the local LLM.

The local model (Qwen behind ninfer) rejects a system message that is not first ("system message
must be at the beginning") and a request without a user message ("no user query found"). Upstream
sends both shapes: generators pass a single system prompt, and structured output appends its JSON
instruction as a trailing system message. Like upstream's Anthropic path, all system text is merged
into one leading system message and a short user trigger is added when no user message exists.

Background jobs can also set request options for every local call inside a block, for example the
game stock job's thinking budget: without it ninfer stops at its default output limit while the
model is still thinking.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.services.prompts.common import ANTHROPIC_SYSTEM_ONLY_TRIGGER

_options: ContextVar[dict | None] = ContextVar("home_local_llm_options", default=None)


@contextmanager
def generation_options(*, reasoning_effort: str = "", max_tokens: int = 0) -> Iterator[None]:
    """Send these options with every local LLM call in the block; empty values are not sent."""
    options = {"reasoning_effort": reasoning_effort, "max_tokens": max_tokens}
    token = _options.set({k: v for k, v in options.items() if v})
    try:
        yield
    finally:
        _options.reset(token)


def local_generation_options() -> dict:
    """The options set by the innermost `generation_options` block, or none."""
    return dict(_options.get() or {})


def local_chat_request(messages: list[dict], extra: dict) -> tuple[list[dict], dict]:
    """Messages in an accepted order, plus job options that the call did not set itself."""
    return local_chat_messages(messages), {**local_generation_options(), **extra}


def local_chat_messages(messages: list[dict]) -> list[dict]:
    """Return messages with one leading system message and at least one user message."""
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    if not any(m.get("role") == "user" for m in rest):
        rest = [{"role": "user", "content": ANTHROPIC_SYSTEM_ONLY_TRIGGER}, *rest]
    if not system_parts:
        return rest
    return [{"role": "system", "content": "\n\n".join(system_parts)}, *rest]
