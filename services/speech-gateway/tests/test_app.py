import io
import json
import sys

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway import engines as engines_module
from gateway.engines import EngineError, EngineOOM, WhisperEngine, worker_env
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
        self.preloaded = []
        self.loaded = False

    def load(self):
        self.loaded = True

    def preload(self, model, device):
        self.preloaded.append((model, device))
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
    reconcile(eng, session, vram)
    assert eng.tts.loaded and eng.whisper.loaded
    session.state = SessionState.BUSY
    reconcile(eng, session, vram)
    assert not eng.tts.loaded and not eng.whisper.loaded
    session.state = SessionState.SHARED
    reconcile(eng, session, vram)
    assert eng.tts.loaded


@pytest.mark.parametrize(
    "vram, expected", [(24.0, ("kbmedium", "cuda")), (8.0, ("kbsmall", "cpu"))]
)
def test_reconcile_preloads_whisper_for_the_english_plan_model(vram, expected):
    from gateway.app import reconcile

    eng = Engines()
    reconcile(eng, FakeSession(SessionState.READY), vram)
    assert eng.whisper.preloaded == [expected]


def test_single_sentence_ends_with_room_tone(refs):
    client = make(refs)
    r = client.post("/v1/audio/speech", json={"input": "Hello there.", "language": "en"})
    assert r.status_code == 200
    from gateway.polish import polish, room_tone

    audio, sr = FakeTts().synth("x", "en", "x", "x")
    assert r.content == b"MP3" + str(len(polish(audio, sr)) + len(room_tone(sr))).encode()


def test_asr_engine_error_is_503(refs):
    eng = Engines(text="hej hej")

    def broken(*_args):
        raise EngineError("worker hung")

    eng.whisper.transcribe = broken
    client = make(refs, engines=eng)
    assert asr(client, "en-GB").status_code == 503


def test_worker_env_puts_venv_cuda_libs_on_the_loader_path(tmp_path, monkeypatch):
    python = tmp_path / "venv" / "bin" / "python"
    libs = [
        tmp_path / "venv/lib/python3.12/site-packages/nvidia" / name / "lib"
        for name in ("cublas", "cudnn")
    ]
    for lib in libs:
        lib.mkdir(parents=True)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/existing")
    env = worker_env(str(python))
    assert env["LD_LIBRARY_PATH"].split(":") == [str(libs[0]), str(libs[1]), "/existing"]


def test_worker_env_is_given_to_the_worker_only(tmp_path, monkeypatch):
    seen = {}

    class FakePopen:
        def __init__(self, cmd, **kw):
            seen.update(kw)

        def poll(self):
            return None

    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    monkeypatch.setattr(engines_module.subprocess, "Popen", FakePopen)
    WhisperEngine(str(tmp_path / "bin" / "python")).load()
    assert "LD_LIBRARY_PATH" in seen["env"]
    assert "LD_LIBRARY_PATH" not in engines_module.os.environ


HUNG_WORKER = "import sys, time\nfor line in sys.stdin:\n    time.sleep(60)\n"
ANSWERING_WORKER = (
    "import sys\n"
    "for line in sys.stdin:\n"
    "    print('{\"text\": \"ok\", \"ok\": true}', flush=True)\n"
)


def worker(script):
    engine = WhisperEngine(sys.executable)
    engine._cmd = [sys.executable, "-u", "-c", script]
    return engine


def test_hung_worker_is_killed_and_raises(monkeypatch):
    monkeypatch.setattr(engines_module, "WORKER_REQUEST_TIMEOUT", 0.2)
    monkeypatch.setattr(engines_module, "WORKER_LOAD_TIMEOUT", 0.2)
    engine = worker(HUNG_WORKER)
    with pytest.raises(EngineError, match="timed out"):
        engine.transcribe(np.zeros(160, dtype=np.float32), "sv", "medium", "cuda")
    assert engine._proc is None


def test_transcribe_uses_load_timeout_until_the_model_is_loaded(monkeypatch):
    monkeypatch.setattr(engines_module, "WORKER_LOAD_TIMEOUT", 11.0)
    monkeypatch.setattr(engines_module, "WORKER_REQUEST_TIMEOUT", 7.0)
    engine = worker(ANSWERING_WORKER)
    timeouts = []
    real = engine._readline
    monkeypatch.setattr(engine, "_readline", lambda p, t: (timeouts.append(t), real(p, t))[1])
    audio = np.zeros(160, dtype=np.float32)
    try:
        engine.preload("kbmedium", "cuda")
        engine.preload("kbmedium", "cuda")  # already loaded: no second request
        assert timeouts == [11.0]
        assert engine.transcribe(audio, "sv", "kbmedium", "cuda") == "ok"
        assert engine.transcribe(audio, "sv", "medium", "cuda") == "ok"  # model swap
        assert engine.transcribe(audio, "sv", "medium", "cuda") == "ok"
        assert timeouts == [11.0, 7.0, 11.0, 7.0]
    finally:
        engine.unload()


def test_worker_load_op_loads_the_model():
    from gateway.whisper_worker import handle

    loads, state = [], {}

    def loader(model, device):
        loads.append((model, device))
        return object()

    req = {"op": "load", "model": "kbmedium", "device": "cuda"}
    assert handle(req, state, loader) == {"ok": True}
    assert loads == [("kbmedium", "cuda")]
    assert state["key"] == ("kbmedium", "cuda")


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
