from app.main import app


def test_install_home_registers_speech_routes() -> None:
    paths = set(app.openapi()["paths"])
    assert {
        "/api/speech-session/open",
        "/api/speech-session/keepalive",
        "/api/speech-session/status",
    } <= paths
