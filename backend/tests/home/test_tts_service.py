"""Home patch to the Kokoro TTS service: the speech gateway receives a language."""

from unittest.mock import AsyncMock


async def test_kokoro_tts_sends_language():
    from unittest.mock import MagicMock, patch

    from app.services.tts_service import KokoroTTSService

    client = MagicMock()
    client.post = AsyncMock(return_value=MagicMock(content=b"mp3"))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    with patch("app.services.tts_service.httpx.AsyncClient", return_value=client):
        service = KokoroTTSService("http://kokoro", "af_heart")
        assert await service.synthesize("Hej.", language="sv") == b"mp3"
        assert client.post.await_args.kwargs["json"]["language"] == "sv"
        await service.synthesize("Hi.")
        assert client.post.await_args.kwargs["json"]["language"] == "en"
