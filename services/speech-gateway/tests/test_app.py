import io
import json

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.engines import EngineOOM
from gateway.session import SessionState


class FakeSession:
    def __init__(self, state=SessionState.READY):
        self.state = state
        self.calls = []

    async def open(self):
        self.calls.append("open")
        return self.state

    async def keepalive(self):
        self.calls.append("keepalive")
        return self.state

    async def tick(self):
        self.calls.append("tick")


class FakeParakeet:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def transcribe(self, audio):
        self.calls += 1
        return self.text


class FakeWhisper:
    def __init__(self, text="hola"):
        self.text = text
        self.calls = []
        self.loaded = False

    def load(self):
        self.loaded = True

    def unload(self):
        self.loaded = False

    def transcribe(self, audio, language, model, device):
        self.calls.append((language, model, device))
        return self.text


class FakeTts:
    def __init__(self, fail=0):
        self.fail = fail
        self.calls = []
        self.loaded = False

    def load(self):
        self.loaded = True

    def unload(self):
        self.loaded = False

    def synth(self, text, language, ref_audio, ref_text):
        self.calls.append((text, language, ref_audio, ref_text))
        if self.fail:
            self.fail -= 1
            raise EngineOOM()
        return np.sin(np.linspace(0, 200, 24000)).astype(np.float32) * 0.3, 24000


class Engines:
    def __init__(self, text="hello", whisper_text="hola", tts_fail=0):
        self.parakeet = FakeParakeet(text)
        self.whisper = FakeWhisper(whisper_text)
        self.tts = FakeTts(tts_fail)


def wav(level=0.2, rate=16000, seconds=1.0):
    t = np.arange(int(rate * seconds)) / rate
    buf = io.BytesIO()
    sf.write(buf, (np.sin(2 * np.pi * 220 * t) * level).astype(np.float32), rate, format="WAV")
    return buf.getvalue()


@pytest.fixture
def refs(tmp_path):
    for lang in ("sv", "en", "es"):
        (tmp_path / f"{lang}.wav").write_bytes(b"x")
    (tmp_path / "refs.json").write_text(json.dumps({"sv": "svt", "en": "ent", "es": "est"}))
    return tmp_path


def make(refs, engines=None, state=SessionState.READY, vram=24.0, **kw):
    engines = engines or Engines()
    session = FakeSession(state)
    app = create_app(
        engines=engines,
        session=session,
        refs_dir=refs,
        vram_gb=vram,
        encoder=lambda audio, sr: b"MP3" + str(len(audio)).encode(),
        background=False,
        **kw,
    )
    return TestClient(app), engines, session


def asr(client, language, data=None):
    return client.post(
        f"/asr?language={language}&output=json&task=transcribe",
        files={"audio_file": ("a.wav", data or wav(), "audio/wav")},
    )


def test_asr_silence_returns_empty_without_routing(refs):
    client, eng, _ = make(refs)
    r = asr(client, "es", wav(level=0.001))
    assert r.json() == {"text": "", "spoken_language": "es"}
    assert eng.parakeet.calls == 0 and eng.whisper.calls == []


def test_asr_english_uses_parakeet_text(refs):
    client, eng, _ = make(refs, Engines(text="I like the red apple very much"))
    r = asr(client, "en", wav(rate=44100))
    assert r.json() == {"text": "I like the red apple very much", "spoken_language": "en"}
    assert eng.whisper.calls == []


def test_asr_english_works_when_session_not_ready(refs):
    client, _, _ = make(refs, Engines(text="I like the red apple very much"), SessionState.OFF)
    assert asr(client, "en").status_code == 200


def test_asr_swedish_uses_whisper_sv(refs):
    eng = Engines(text="jag tycker om att äta ett rött äpple", whisper_text="Jag gillar äpplen")
    client, eng, _ = make(refs, eng)
    r = asr(client, "en")
    assert r.json() == {"text": "Jag gillar äpplen", "spoken_language": "sv"}
    assert eng.whisper.calls == [("sv", "kbmedium", "cuda")]


def test_asr_swedish_not_ready_is_503(refs):
    eng = Engines(text="jag tycker om att äta ett rött äpple")
    client, _, _ = make(refs, eng, SessionState.OFF)
    assert asr(client, "en").status_code == 503


def test_asr_spanish_target_uses_whisper_es(refs):
    eng = Engines(text="me gusta la manzana roja", whisper_text="Me gusta la manzana roja.")
    client, eng, _ = make(refs, eng)
    r = asr(client, "es")
    assert r.json() == {"text": "Me gusta la manzana roja.", "spoken_language": "es"}
    assert eng.whisper.calls == [("es", "medium", "cuda")]


def test_asr_swedish_on_spanish_plan_uses_medium(refs):
    eng = Engines(text="jag tycker om att äta ett rött äpple")
    client, eng, _ = make(refs, eng)
    asr(client, "es")
    assert eng.whisper.calls == [("sv", "medium", "cuda")]


def test_asr_small_card_uses_cpu_models(refs):
    eng = Engines(text="jag tycker om att äta ett rött äpple")
    client, eng, _ = make(refs, eng, SessionState.OFF, vram=8.0)
    assert asr(client, "en").status_code == 200
    assert eng.whisper.calls == [("sv", "kbsmall", "cpu")]


def test_speech_uses_reference_for_language(refs):
    client, eng, _ = make(refs)
    r = client.post(
        "/v1/audio/speech",
        json={"input": "Hola. Qué tal?", "language": "es", "response_format": "mp3", "voice": "x"},
    )
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content.startswith(b"MP3")
    assert [c[0] for c in eng.tts.calls] == ["Hola.", "Qué tal?"]
    assert eng.tts.calls[0][1:] == ("es", str(refs / "es.wav"), "est")


def test_speech_unknown_language_is_400(refs):
    client, _, _ = make(refs)
    r = client.post("/v1/audio/speech", json={"input": "hi", "language": "de"})
    assert r.status_code == 400


def test_speech_oom_retries_once_then_503(refs):
    client, eng, _ = make(refs, Engines(tts_fail=1))
    body = {"input": "Hello there.", "language": "en"}
    assert client.post("/v1/audio/speech", json=body).status_code == 200
    client, eng, _ = make(refs, Engines(tts_fail=2))
    assert client.post("/v1/audio/speech", json=body).status_code == 503
    assert len(eng.tts.calls) == 2


def test_speech_when_session_not_ready_is_503(refs):
    client, eng, _ = make(refs, state=SessionState.SWITCHING)
    r = client.post("/v1/audio/speech", json={"input": "hi", "language": "en"})
    assert r.status_code == 503 and eng.tts.calls == []


def test_session_endpoints_and_health(refs):
    client, _, session = make(refs)
    assert client.post("/session/open").json() == {"state": "ready"}
    assert client.post("/session/keepalive").json() == {"state": "ready"}
    assert client.get("/session/status").json() == {"state": "ready"}
    assert client.get("/").status_code == 200
    assert client.get("/v1/models").status_code == 200
    assert session.calls == ["open", "keepalive"]


@pytest.mark.parametrize("vram", [24.0, 8.0])
def test_reconcile_loads_gpu_engines_only_while_usable(refs, vram):
    from gateway.app import reconcile

    eng, session = Engines(), FakeSession(SessionState.READY)
    reconcile(eng, session)
    assert eng.tts.loaded and eng.whisper.loaded
    session.state = SessionState.BUSY
    reconcile(eng, session)
    assert not eng.tts.loaded and not eng.whisper.loaded
    session.state = SessionState.SHARED
    reconcile(eng, session)
    assert eng.tts.loaded


def test_whisper_worker_protocol():
    from gateway.whisper_worker import handle

    loads = []

    class M:
        def transcribe(self, audio, **kw):
            return iter([type("S", (), {"text": " hej "})(), type("S", (), {"text": "du"})()]), None

    state = {}

    def loader(model, device):
        loads.append((model, device))
        return M()

    audio = np.zeros(1600, dtype=np.float32)
    import base64

    b64 = base64.b64encode(audio.tobytes()).decode()
    req = {"op": "transcribe", "model": "medium", "device": "cuda", "language": "sv", "audio": b64}
    assert handle(req, state, loader) == {"text": "hej du"}
    handle(req, state, loader)
    assert loads == [("medium", "cuda")]
    handle({**req, "model": "kbmedium"}, state, loader)
    assert loads[-1] == ("kbmedium", "cuda")
    assert handle({"op": "unload"}, state, loader) == {"ok": True}
    assert state == {}
