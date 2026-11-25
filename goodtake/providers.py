"""Explicit cloud requests and optional local speech recognition. Secrets never enter project data."""

from __future__ import annotations

import json
import threading
import time
import uuid

import httpx

from .media import validate_words
from .process import run

_models = {}
_model_lock = threading.Lock()


def local_model(name="base.en"):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ValueError('Local transcription needs pip install "goodtake-studio[local]".') from None
    with _model_lock:
        if name not in _models:
            _models[name] = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=4)
        return _models[name]


def structured(store, project_id, instructions, payload, schema, stage="editorial"):
    key = store.key("OPENAI_API_KEY")
    if not key:
        raise ValueError(
            "Add an OpenAI key in Settings for automatic selection. Manual selection is available offline."
        )
    model = store.settings().editor_model
    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            timeout=240,
            headers={"Authorization": "Bearer " + key},
            json={
                "model": model,
                "store": False,
                "instructions": instructions,
                "input": json.dumps(payload, ensure_ascii=False),
                "max_output_tokens": 8000,
                "text": {"format": {"type": "json_schema", "name": stage, "strict": True, "schema": schema}},
            },
        )
    except httpx.HTTPError:
        raise RuntimeError(
            "The editorial provider did not respond. Your saved selections are retained."
        ) from None
    if not response.is_success:
        raise RuntimeError(
            f"Editorial provider returned HTTP {response.status_code}. Check your key, model and quota."
        )
    data = response.json()
    if data.get("usage"):
        store.record_usage(
            project_id,
            data.get("id", uuid.uuid4().hex),
            {
                "provider": "openai",
                "stage": stage,
                "model": data.get("model", model),
                "usage": data["usage"],
                "time": time.time(),
                "pricing": "Not priced; see your provider bill",
            },
        )
    text = "".join(
        content.get("text", "")
        for item in data.get("output", [])
        if item.get("type") == "message"
        for content in item.get("content", [])
        if content.get("type") == "output_text"
    )
    if data.get("status") != "completed" or not text:
        raise RuntimeError(
            "The editorial provider returned an incomplete result. Retry after checking your model."
        )
    return json.loads(text)


def transcribe(store, project_id, checkpoint=lambda: None, progress=lambda *args, **kwargs: None):
    project = store.get(project_id)
    if project["words"] and project["transcript"]["source_sha256"] == project["source_sha256"]:
        return project["words"]
    directory = store.directory(project_id)
    audio = directory / "transcription.wav"
    progress("Preparing audio", 0.05, phase="prepare", phase_progress=None)
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            directory / project["source_file"],
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            audio,
        ],
        checkpoint=checkpoint,
    )
    settings = store.settings()
    if settings.transcription == "local":
        progress("Loading speech model", 0.08, phase="transcribe", phase_progress=None)
        model = local_model(settings.whisper_model)
        segments, _ = model.transcribe(
            str(audio),
            language=settings.language,
            word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        words = []
        for segment in segments:
            checkpoint()
            words.extend(
                {"text": w.word.strip(), "start": w.start, "end": w.end, "speaker": "0"}
                for w in (segment.words or [])
                if w.word.strip() and w.end > w.start
            )
            fraction = min(1, segment.end / project["duration"])
            progress(
                "Transcribing",
                0.1 + 0.35 * fraction,
                phase="transcribe",
                phase_progress=fraction,
                units_done=min(segment.end, project["duration"]),
                units_total=project["duration"],
                unit="seconds",
            )
        method = "Local Whisper · " + settings.whisper_model
    else:
        key = store.key("ELEVENLABS_API_KEY")
        if not key:
            raise ValueError("Add an ElevenLabs key in Settings, or select local Whisper.")
        progress("Transcribing with ElevenLabs", 0.1, phase="transcribe", phase_progress=None)
        with audio.open("rb") as file:
            try:
                response = httpx.post(
                    "https://api.elevenlabs.io/v1/speech-to-text",
                    timeout=1200,
                    headers={"xi-api-key": key},
                    files={"file": ("audio.wav", file, "audio/wav")},
                    data={
                        "model_id": "scribe_v1",
                        "diarize": "true",
                        "language_code": settings.language,
                        "timestamps_granularity": "word",
                        "tag_audio_events": "false",
                    },
                )
            except httpx.HTTPError:
                raise RuntimeError(
                    "Transcription did not finish. You can retry or import timed words."
                ) from None
        if not response.is_success:
            raise RuntimeError(
                f"Transcription provider returned HTTP {response.status_code}. Check key and quota."
            )
        data = response.json()
        words = [
            {
                "text": w["text"],
                "start": w["start"],
                "end": w["end"],
                "speaker": str(w.get("speaker_id", "0")),
            }
            for w in data["words"]
            if w.get("type") == "word"
        ]
        method = "ElevenLabs Scribe"
        store.record_usage(
            project_id,
            "asr-" + uuid.uuid4().hex,
            {
                "provider": "elevenlabs",
                "stage": "transcription",
                "duration_seconds": project["duration"],
                "time": time.time(),
                "pricing": "Not priced; see your provider bill",
            },
        )
    words = validate_words(words, project["duration"])
    checkpoint()
    store.change(
        project_id,
        lambda p: p.update(
            words=words,
            transcript={"method": method, "timing": "word", "source_sha256": project["source_sha256"]},
        ),
    )
    audio.unlink(missing_ok=True)
    return words
