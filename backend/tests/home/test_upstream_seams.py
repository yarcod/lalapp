"""Pins on the upstream code home features build on.

After merging upstream, a failure here names the seam that changed and the home module that
depends on it. Fix the home module (or the hook), never the assertion alone.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.core import deps
from app.home.conversation import HomeConversationPipeline
from app.home.provisional_turn import ProvisionalTurn
from app.routers import conversation as conversation_router
from app.services import conversation_pipeline, games
from app.services.conversation_pipeline import ConversationPipeline
from app.services.prompts import lesson, tutor

# Parameters only the home subclass adds on top of the upstream signature.
HOME_ONLY_PARAMS = {"small_llm", "generated_opener", "provisional"}

# Seams added to the upstream pipeline for home: name -> required parameters.
PIPELINE_SEAMS: dict[str, list[str]] = {
    "_chat": ["messages", "kwargs"],
    "_reply_text": ["raw_text"],
    "_add_reply": ["text"],
    "_record_usage": ["stream"],
    "_tts_items": ["text"],
    "_synthesize_chunk": ["text", "language"],
    "handle_control": ["msg", "ws"],
    "_build_conversation_system_prompt": ["target_code"],
}


def _params(func: Callable) -> list[str]:
    return [name for name in inspect.signature(func).parameters if name != "self"]


def _source(module: object) -> str:
    return inspect.getsource(module)


@pytest.mark.parametrize("name", sorted(PIPELINE_SEAMS))
def test_pipeline_seam_exists_with_expected_parameters(name: str) -> None:
    owner = conversation_pipeline if name.startswith("_build") else ConversationPipeline
    assert hasattr(
        owner, name
    ), f"upstream ConversationPipeline.{name} is gone; HomeConversationPipeline relies on it"
    params = _params(getattr(owner, name))
    for expected in PIPELINE_SEAMS[name]:
        assert expected in params, (
            f"upstream ConversationPipeline.{name} changed (now {params}); "
            f"HomeConversationPipeline expects parameter {expected!r}"
        )


# Methods the home class defines that upstream does not have (new behaviour, not overrides).
HOME_ONLY_METHODS = {
    "_confirm_provisional",
    "_abort_provisional",
    "_run_held_memory_calls",
    "_current_turn",
    "_effort_kwargs",
    "_holding_executor",
    "_generate_opener",
    "_collect_reply",
    "_tagged_text",
    "_build_spoken_lines",
    "discard_last_turn",
}


def test_pipeline_overridden_methods_exist() -> None:
    defined = [
        name
        for name, member in vars(HomeConversationPipeline).items()
        if callable(member) and not name.startswith("__")
    ]
    for name in defined:
        if name in HOME_ONLY_METHODS:
            continue
        assert hasattr(ConversationPipeline, name), (
            f"upstream ConversationPipeline.{name} is gone (or {name} is a new home-only "
            "method missing from HOME_ONLY_METHODS); HomeConversationPipeline overrides it"
        )
        base = _params(getattr(ConversationPipeline, name))
        home = [
            p for p in _params(getattr(HomeConversationPipeline, name)) if p not in HOME_ONLY_PARAMS
        ]
        assert base == home, (
            f"upstream ConversationPipeline.{name} changed (now {base}); "
            f"HomeConversationPipeline overrides it with {home}"
        )


def test_pipeline_constructor_accepts_router_kwargs() -> None:
    tree = ast.parse(Path(inspect.getsourcefile(conversation_router)).read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_pipeline"
    ]
    assert calls, "routers/conversation.py no longer calls build_pipeline("
    accepted = set(inspect.signature(ConversationPipeline.__init__).parameters)
    passed = {kw.arg for kw in calls[0].keywords if kw.arg}
    assert passed <= accepted, (
        f"upstream ConversationPipeline.__init__ no longer accepts {sorted(passed - accepted)}; "
        "build_pipeline passes them through to HomeConversationPipeline"
    )
    home_accepted = set(inspect.signature(HomeConversationPipeline.__init__).parameters)
    assert {"small_llm", "generated_opener"} <= home_accepted


def test_prompt_builders_accept_target_code() -> None:
    for builder in (tutor.build_tutor_system_prompt, tutor.build_conversation_system_prompt):
        assert "target_code" in _params(
            builder
        ), f"upstream {builder.__name__} lost target_code; home tutor_suffix needs it"
        assert "tutor_suffix(" in inspect.getsource(builder), (
            f"upstream {builder.__name__} no longer calls tutor_suffix(; "
            "app.home.prompts adds the child rules there"
        )
    assert hasattr(
        lesson, "build_lesson_generation_prompt"
    ), "upstream build_lesson_generation_prompt is gone; home child_suffix hooks into it"
    assert "child_suffix(" in inspect.getsource(
        lesson.build_lesson_generation_prompt
    ), "upstream build_lesson_generation_prompt no longer calls child_suffix("


def test_create_game_hook_inputs() -> None:
    params = _params(games.create_game)
    assert params[:5] == ["db", "user", "plan", "body", "game_type"], (
        f"upstream create_game changed (now {params}); "
        "app.home.games.start_from_stock is called with these inputs"
    )


def test_get_current_user_hook_present() -> None:
    assert "enter_user(" in inspect.getsource(deps.get_current_user), (
        "upstream get_current_user lost its enter_user( call; "
        "home child mode would never be set for requests"
    )


@pytest.mark.parametrize(
    ("module_name", "call"),
    [
        ("app.main", "install_home("),
        ("app.routers.conversation", "enter_user("),
        ("app.routers.conversation", "build_pipeline("),
        ("app.routers.chat", "TaggedChatStream("),
        ("app.routers.games", "stock_empty_response("),
        ("app.services.games", "start_from_stock("),
        ("app.services.games", "stock_mode()"),
        ("app.services.llm_adapter", "local_chat_request("),
    ],
)
def test_hook_lines_present(module_name: str, call: str) -> None:
    import importlib  # noqa: PLC0415

    source = _source(importlib.import_module(module_name))
    assert call in source, (
        f"hook {call} is missing from {module_name}; the app.home feature behind it is "
        "disconnected (lost in a merge?)"
    )


def test_chat_page_hook_present() -> None:
    page = Path(__file__).resolve().parents[3] / "frontend/src/app/(app)/chat/page.tsx"
    if not page.exists():
        pytest.skip("frontend sources are not available")
    assert "useTaggedReplies(" in page.read_text(), (
        "hook useTaggedReplies( is missing from the chat page; "
        "tagged replies would show their language tags (lost in a merge?)"
    )


@pytest.mark.asyncio
async def test_provisional_chat_fails_loudly_when_user_message_is_not_in_history() -> None:
    pipeline = HomeConversationPipeline(
        llm=AsyncMock(), tts=AsyncMock(), stt=AsyncMock(), cefr_level="B1"
    )
    pipeline.history = [{"role": "assistant", "content": "earlier"}]
    pipeline._turn_ws = ProvisionalTurn(AsyncMock(), pipeline._send_lock)

    with pytest.raises(RuntimeError, match=r"ConversationPipeline\._process_turn changed"):
        await pipeline._chat([{"role": "user", "content": "hi"}])


def test_home_only_methods_are_not_upstream_methods() -> None:
    shadowed = sorted(n for n in HOME_ONLY_METHODS if hasattr(ConversationPipeline, n))
    assert not shadowed, (
        f"upstream ConversationPipeline now defines {shadowed}; HomeConversationPipeline "
        "overrides them: move them out of HOME_ONLY_METHODS so their signatures are checked"
    )
