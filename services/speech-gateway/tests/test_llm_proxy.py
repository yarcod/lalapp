import json

import httpx
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.llm_proxy import NINFER_MODEL, OLLAMA_MODEL


class FakeSession:
    state = None

    async def tick(self):
        pass


class FakeEngines:
    pass


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def reply(status=200, data=None):
    """A response that streams like a real one (json= would be read eagerly)."""
    return httpx.Response(
        status,
        headers={"content-type": "application/json"},
        stream=Chunks([json.dumps(data or {}).encode()]),
    )


def make_client(tmp_path, tier, handler):
    tier_file = tmp_path / "llm-tier"
    if tier is not None:
        tier_file.write_text(tier + "\n")
    app = create_app(
        engines=FakeEngines(),
        session=FakeSession(),
        vram_gb=24,
        background=False,
        llm_tier_file=tier_file,
        llm_transport=httpx.MockTransport(handler),
    )
    return TestClient(app)


BODY = {"model": "whatever", "messages": [{"role": "user", "content": "hi"}], "stream": True}


def test_rewrites_model_for_ninfer(tmp_path):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return reply(200, {"ok": True})

    r = make_client(tmp_path, "full", handler).post("/v1/chat/completions", json=BODY)
    assert r.status_code == 200
    assert seen["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    assert seen["body"]["model"] == NINFER_MODEL == "qwen3.8-27b"
    assert seen["body"]["messages"] == BODY["messages"]


def test_rewrites_model_for_ollama(tmp_path):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return reply(200, {"ok": True})

    r = make_client(tmp_path, "shared", handler).post("/v1/chat/completions", json=BODY)
    assert r.status_code == 200
    assert seen["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert seen["body"]["model"] == OLLAMA_MODEL == "gemma4:e4b-it-qat"


def test_missing_tier_file_means_full(tmp_path):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return reply()

    make_client(tmp_path, None, handler).post("/v1/chat/completions", json=BODY)
    assert ":8080" in seen["url"]


def test_tier_is_reread_per_request(tmp_path):
    urls = []

    def handler(request):
        urls.append(request.url.port)
        return reply()

    client = make_client(tmp_path, "full", handler)
    client.post("/v1/chat/completions", json=BODY)
    (tmp_path / "llm-tier").write_text("shared\n")
    client.post("/v1/chat/completions", json=BODY)
    assert urls == [8080, 11434]


def test_streams_chunks_unchanged(tmp_path):
    chunks = [b'data: {"a":1}\n\n', b'data: {"b":', b"2}\n\n", b"data: [DONE]\n\n"]

    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Chunks(chunks)
        )

    r = make_client(tmp_path, "full", handler).post("/v1/chat/completions", json=BODY)
    assert r.content == b"".join(chunks)
    assert r.headers["content-type"].startswith("text/event-stream")


def test_upstream_status_is_passed_through(tmp_path):
    def handler(request):
        return reply(400, {"error": "bad"})

    r = make_client(tmp_path, "full", handler).post("/v1/chat/completions", json=BODY)
    assert r.status_code == 400
    assert r.json() == {"error": "bad"}


def test_backend_down_is_503(tmp_path):
    def handler(request):
        raise httpx.ConnectError("refused")

    r = make_client(tmp_path, "full", handler).post("/v1/chat/completions", json=BODY)
    assert r.status_code == 503


def test_invalid_body_is_400(tmp_path):
    r = make_client(tmp_path, "full", lambda request: httpx.Response(200)).post(
        "/v1/chat/completions", content=b"not json"
    )
    assert r.status_code == 400
