from collections import Counter
from unittest.mock import AsyncMock, patch

import pytest

from app.lalapp.personas import registry
from app.lalapp.personas.compose import compose_system_prompt
from app.lalapp.scenarios import service
from app.lalapp.scenarios.service import JudgeResult, MissionVerdict

UI_LANGUAGES = {"en", "sv", "es"}


@pytest.mark.parametrize("scenario", list(service.SCENARIOS.values()), ids=lambda s: s.id)
def test_catalog_entries_are_complete(scenario):
    assert len(scenario.id) <= 50
    assert scenario.npc.role == "npc" and scenario.npc.language == scenario.language
    assert set(scenario.npc.voices) == {"openai", "local"}
    assert set(scenario.summary) == UI_LANGUAGES
    assert scenario.opener and scenario.title
    assert 2 <= len(scenario.missions) <= 3
    assert len({m.id for m in scenario.missions}) == len(scenario.missions)
    for mission in scenario.missions:
        assert set(mission.goal) == UI_LANGUAGES and mission.rubric


def test_arcs_are_numbered_from_one_and_npcs_are_not_selectable():
    arcs = Counter((s.language, s.arc) for s in service.SCENARIOS.values())
    for (language, arc), count in arcs.items():
        orders = sorted(
            s.order for s in service.SCENARIOS.values() if (s.language, s.arc) == (language, arc)
        )
        assert orders == list(range(1, count + 1))
    npc_ids = {s.npc.id for s in service.SCENARIOS.values()}
    assert not npc_ids & set(registry.PERSONAS)
    for language in ("en-US", "es-ES"):
        assert all(p.role != "npc" for p in registry.selectable_for(language))


@pytest.mark.parametrize(
    "quote,expected",
    [
        ("¿cuánto cuesta?", True),
        ("CUANTO cuesta", True),  # case and accents are folded
        ("cuánto  cuesta", True),
        ("ok", False),
        ("¿cuánto vale el café?", False),
    ],
)
def test_quotes_must_come_from_learner_messages(quote, expected):
    learner = ["Hola, quiero un café con leche. ¿Cuánto cuesta?"]
    assert service.quote_is_from_learner(quote, learner) is expected


def test_scene_prompt_lists_only_open_goals_and_keeps_the_persona_lock():
    scenario = service.get("en-leeds-1-cafe")
    prompt = service.scene_prompt(scenario, {"order"})
    assert "Order something" not in prompt
    assert "Ask how much it costs" in prompt
    assert "persona lock still" in prompt
    composed = compose_system_prompt(
        "You are an encouraging and patient English conversation partner named Lingu.",
        scenario.npc,
        target_language="en-GB",
        cefr_level="A1",
        native_language_name="Swedish",
        scene=prompt,
    )
    assert composed.startswith("You are Sandra, a character in a role-play scene")
    assert "Setting:" in composed


def _stream():
    class Chunk:
        class Choice:
            class Delta:
                content = "Lovely."

            delta = Delta()

        choices = [Choice()]

    async def gen():
        yield Chunk()

    return gen()


async def _say(client, headers, conversation_id, message):
    with patch(
        "app.routers.chat.llm_adapter.chat", new_callable=AsyncMock, return_value=_stream()
    ) as chat:
        response = await client.post(
            "/api/chat",
            headers=headers,
            json={"message": message, "conversation_id": conversation_id},
        )
        assert response.status_code == 200
        _ = response.text
    return chat.await_args.args[0]


def _judge(*verdicts):
    return patch(
        "app.lalapp.scenarios.service.llm_adapter.structured_output",
        new_callable=AsyncMock,
        return_value=JudgeResult(missions=[MissionVerdict(**v) for v in verdicts]),
    )


def _by_id(listing):
    return {s["id"]: s for s in listing["scenarios"]}


async def test_scene_flow_from_start_to_unlocking_the_next_scene(client, test_user):
    _, headers = test_user

    listing = (await client.get("/api/lalapp/scenarios", headers=headers)).json()
    scenes = _by_id(listing)
    assert listing["target_language"] == "en-US"
    assert scenes["en-leeds-1-cafe"]["status"] == "available"
    assert scenes["en-leeds-2-flat"]["status"] == "locked"
    assert not any(s["id"].startswith("es-") for s in listing["scenarios"])
    locked = await client.post("/api/lalapp/scenarios/en-leeds-2-flat/start", headers=headers)
    assert locked.status_code == 409
    foreign = await client.post("/api/lalapp/scenarios/es-valencia-1-cafe/start", headers=headers)
    assert foreign.status_code == 404

    started = (
        await client.post("/api/lalapp/scenarios/en-leeds-1-cafe/start", headers=headers)
    ).json()
    conversation_id = started["conversation_id"]
    assert started["scenario"]["status"] == "active"

    # The conversation is an ordinary upstream one, opened by the NPC.
    conversations = (await client.get("/api/chat/conversations", headers=headers)).json()
    assert conversations[0]["id"] == conversation_id
    assert conversations[0]["title"] == "Breakfast at Sandra's"
    messages = (
        await client.get(f"/api/chat/conversations/{conversation_id}/messages", headers=headers)
    ).json()["messages"]
    assert [(m["role"], m["content"]) for m in messages] == [
        ("assistant", "Morning! You must be new round here. What can I get you?")
    ]

    persona = await client.get(
        f"/api/lalapp/conversations/{conversation_id}/persona", headers=headers
    )
    assert persona.json()["name"] == "Sandra"
    switch = await client.put(
        f"/api/lalapp/conversations/{conversation_id}/persona",
        headers=headers,
        json={"persona_id": "en-peer-dan"},
    )
    assert switch.status_code == 404

    sent = await _say(client, headers, conversation_id, "Hi! A tea and a scone, please.")
    assert sent[0]["content"].startswith("You are Sandra")
    assert "Order something to eat and drink" in sent[0]["content"]
    assert sent[1]["role"] == "assistant"  # The opener is part of the history.

    check_url = f"/api/lalapp/scenarios/runs/{conversation_id}/check"
    with _judge(
        {"id": "order", "achieved": True, "quote": "a tea and a scone"},
        {"id": "price", "achieved": True, "quote": "how much is it"},  # never said
    ) as judge:
        checked = (await client.post(check_url, headers=headers)).json()
        again = (await client.post(check_url, headers=headers)).json()
    assert judge.await_count == 1  # No new learner message, no second judgement.
    assert checked["newly_done"] == ["order"]
    assert again["newly_done"] == []
    missions = {m["id"]: m for m in checked["scenario"]["missions"]}
    assert missions["order"]["done"] and missions["order"]["evidence"] == "a tea and a scone"
    assert not missions["price"]["done"]

    await _say(client, headers, conversation_id, "How much is it? I'm Ana, from Malmö.")
    with _judge(
        {"id": "price", "achieved": True, "quote": "How much is it?"},
        {"id": "introduce", "achieved": True, "quote": "I'm Ana, from Malmö"},
    ):
        done = (await client.post(check_url, headers=headers)).json()
    assert done["newly_done"] == ["price", "introduce"]
    assert done["scenario"]["status"] == "done"

    scenes = _by_id((await client.get("/api/lalapp/scenarios", headers=headers)).json())
    assert scenes["en-leeds-1-cafe"]["status"] == "done"
    assert scenes["en-leeds-2-flat"]["status"] == "available"
    milestones = (await client.get("/api/lalapp/rhythm", headers=headers)).json()["milestones"]
    assert {"key": "scene_done:en-leeds-1-cafe", "title": "Breakfast at Sandra's"} == {
        "key": milestones[0]["key"],
        "title": milestones[0]["data"]["title"],
    }

    # A finished scene is not judged again.
    await _say(client, headers, conversation_id, "Thanks, bye!")
    with _judge() as judge:
        await client.post(check_url, headers=headers)
    judge.assert_not_awaited()


async def test_check_reports_judge_failure_and_foreign_conversations(client, test_user):
    _, headers = test_user
    started = (
        await client.post("/api/lalapp/scenarios/en-leeds-1-cafe/start", headers=headers)
    ).json()
    conversation_id = started["conversation_id"]
    await _say(client, headers, conversation_id, "A coffee please")
    with patch(
        "app.lalapp.scenarios.service.llm_adapter.structured_output",
        new_callable=AsyncMock,
        side_effect=RuntimeError("model down"),
    ):
        failed = await client.post(
            f"/api/lalapp/scenarios/runs/{conversation_id}/check", headers=headers
        )
    assert failed.status_code == 503
    assert (
        await client.get(f"/api/lalapp/scenarios/runs/{conversation_id + 999}", headers=headers)
    ).status_code == 404


async def test_scenarios_can_be_switched_off(client, test_user, monkeypatch):
    _, headers = test_user
    started = (
        await client.post("/api/lalapp/scenarios/en-leeds-1-cafe/start", headers=headers)
    ).json()
    monkeypatch.setattr("app.lalapp.config.lalapp_settings.SCENARIOS_ENABLED", False)
    assert (await client.get("/api/lalapp/scenarios", headers=headers)).status_code == 404
    # The conversation falls back to an ordinary partner.
    sent = await _say(client, headers, started["conversation_id"], "Hello")
    assert "Setting:" not in sent[0]["content"]
