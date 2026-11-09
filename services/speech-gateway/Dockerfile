FROM python:3.12

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV HF_HOME=/models/hf \
    TORCHDYNAMO_DISABLE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt requirements-whisper.txt ./
RUN python -m venv /opt/whisper-env \
    && /opt/whisper-env/bin/pip install --no-cache-dir -r requirements-whisper.txt \
    && pip install --no-cache-dir -r requirements.txt pytest

COPY gateway ./gateway
COPY tests ./tests
COPY pytest.ini ./
RUN python -m pytest -q tests/test_app.py tests/test_routing.py tests/test_polish.py tests/test_session.py tests/test_llm_proxy.py

EXPOSE 8090
CMD ["uvicorn", "gateway.app:build", "--factory", "--host", "0.0.0.0", "--port", "8090"]
