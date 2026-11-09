"""Stable chat-completions address in front of whichever LLM backend is live."""

import json
import logging
from pathlib import Path

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

log = logging.getLogger(__name__)

NINFER_URL = "http://127.0.0.1:8080"
OLLAMA_URL = "http://127.0.0.1:11434"
NINFER_MODEL = "qwen3.8-27b"
OLLAMA_MODEL = "gemma4:e4b-it-qat"
DEFAULT_TIER_FILE = "/run/llm-tier"


def read_tier(path: Path) -> str:
    """`full` (ninfer) or `shared` (Ollama); a missing or odd file means `full`."""
    try:
        tier = path.read_text().strip()
    except OSError:
        return "full"
    return tier if tier == "shared" else "full"


def backend_for(tier: str) -> tuple[str, str]:
    return (OLLAMA_URL, OLLAMA_MODEL) if tier == "shared" else (NINFER_URL, NINFER_MODEL)


def make_handler(tier_file: Path, transport: httpx.AsyncBaseTransport | None):
    async def chat_completions(request: Request):
        try:
            payload = json.loads(await request.body())
            if not isinstance(payload, dict):
                raise ValueError
        except ValueError as exc:
            raise HTTPException(400, "body must be a JSON object") from exc

        base, model = backend_for(read_tier(tier_file))
        payload["model"] = model
        client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(None, connect=5.0))
        try:
            upstream = await client.send(
                client.build_request("POST", f"{base}/v1/chat/completions", json=payload),
                stream=True,
            )
        except httpx.HTTPError as exc:
            log.error("LLM backend %s unavailable: %r", base, exc)
            await client.aclose()
            return JSONResponse({"detail": "LLM backend unavailable"}, status_code=503)

        async def body():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            except httpx.HTTPError as exc:
                # Headers are already sent: all that is left is to log and end the stream.
                log.error("LLM stream from %s failed mid-response: %r", base, exc)
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(
            body(),
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type"),
        )

    return chat_completions
