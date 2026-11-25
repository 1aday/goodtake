import time

import pytest

from goodtake.models import Brand, ClipInput
from goodtake.store import Store, new_id


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    return Store(tmp_path / "data")


@pytest.fixture
def project(store):
    project = {
        "id": new_id(),
        "title": "A real conversation",
        "duration": 300,
        "width": 1280,
        "height": 720,
        "source_name": "conversation.mp4",
        "source_file": "source.mp4",
        "source_sha256": "a" * 64,
        "created": time.time(),
        "updated": time.time(),
        "brand": Brand().model_dump(),
        "words": [{"text": f"word{i}.", "start": i, "end": i + 0.6, "speaker": "0"} for i in range(290)],
        "transcript": {"method": "fixture", "timing": "word", "source_sha256": "a" * 64},
        "clips": [],
    }
    store.put(project)
    return project


@pytest.fixture
def clip(store, project):
    clip = {
        **ClipInput(title="An actual complete thought", start=0, end=30.6).model_dump(),
        "id": new_id(),
        "status": "draft",
    }
    store.change(project["id"], lambda p: p["clips"].append(clip))
    return clip
