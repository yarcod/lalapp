"""Message order for the local LLM's chat template.

The local model (Qwen behind ninfer) rejects a system message that is not first ("system message
must be at the beginning") and a request without a user message ("no user query found"). Upstream
sends both shapes: generators pass a single system prompt, and structured output appends its JSON
instruction as a trailing system message. Like upstream's Anthropic path, all system text is merged
into one leading system message and a short user trigger is added when no user message exists.
"""

from __future__ import annotations

from app.services.prompts.common import ANTHROPIC_SYSTEM_ONLY_TRIGGER


def local_chat_messages(messages: list[dict]) -> list[dict]:
    """Return messages with one leading system message and at least one user message."""
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    if not any(m.get("role") == "user" for m in rest):
        rest = [{"role": "user", "content": ANTHROPIC_SYSTEM_ONLY_TRIGGER}, *rest]
    if not system_parts:
        return rest
    return [{"role": "system", "content": "\n\n".join(system_parts)}, *rest]
