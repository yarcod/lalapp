import httpx
import pytest

from app.core.config import settings


def _use_gateway(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr("app.routers.speech_session.httpx.AsyncClient", factory)
    monkeypatch.setattr(settings, "STT_PROVIDER", "local")
    monkeypatch.setattr(settings, "STT_BASE_URL", "http://gateway:9000")


@pytest.mark.asyncio
async def test_open_proxies_state(client, test_user, monkeypatch) -> None:
    _, headers = test_user
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        return httpx.Response(200, json={"state": "switching"})

    _use_gateway(monkeypatch, handler)

    response = await client.post("/api/speech-session/open", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"state": "switching"}
    assert seen == [("POST", "http://gateway:9000/session/open")]


@pytest.mark.asyncio
async def test_keepalive_and_status_proxy_state(client, test_user, monkeypatch) -> None:
    _, headers = test_user
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"state": "busy"})

    _use_gateway(monkeypatch, handler)

    keepalive = await client.post("/api/speech-session/keepalive", headers=headers)
    status = await client.get("/api/speech-session/status", headers=headers)

    assert keepalive.json() == {"state": "busy"}
    assert status.json() == {"state": "busy"}
    assert seen == [("POST", "/session/keepalive"), ("GET", "/session/status")]


@pytest.mark.parametrize("failure", [httpx.ConnectError("down"), httpx.ReadTimeout("slow")])
@pytest.mark.asyncio
async def test_gateway_unreachable_is_away_not_error(
    client, test_user, monkeypatch, failure
) -> None:
    _, headers = test_user

    def handler(request: httpx.Request) -> httpx.Response:
        raise failure

    _use_gateway(monkeypatch, handler)

    response = await client.post("/api/speech-session/open", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"state": "away"}


@pytest.mark.asyncio
async def test_unexpected_gateway_answer_is_away(client, test_user, monkeypatch) -> None:
    _, headers = test_user
    _use_gateway(monkeypatch, lambda request: httpx.Response(500, text="boom"))

    response = await client.get("/api/speech-session/status", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"state": "away"}


@pytest.mark.asyncio
async def test_non_local_provider_is_ready_without_calling_gateway(
    client, test_user, monkeypatch
) -> None:
    _, headers = test_user

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("gateway must not be called")

    _use_gateway(monkeypatch, handler)
    monkeypatch.setattr(settings, "STT_PROVIDER", "openai")

    response = await client.post("/api/speech-session/open", headers=headers)

    assert response.json() == {"state": "ready"}


@pytest.mark.asyncio
async def test_requires_authentication(client) -> None:
    assert (await client.post("/api/speech-session/open")).status_code == 401
