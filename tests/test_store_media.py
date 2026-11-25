import json
import time
import zipfile

import pytest
from pydantic import ValidationError

from goodtake.bundle import make_bundle
from goodtake.media import digest, import_transcript, validate_words, youtube_id
from goodtake.models import ClipInput, Word, caption_groups
from goodtake.quality import title_readability


def test_queue_enforces_one_active_job_and_recovers_an_expired_lease(store, project):
    first = store.enqueue(project["id"], "transcribe")
    with pytest.raises(ValueError, match="already"):
        store.enqueue(project["id"], "render")
    assert store.claim("worker-a")["id"] == first["id"]
    assert store.claim("worker-b") is None
    with store.connect() as db:
        db.execute("UPDATE jobs SET lease=? WHERE id=?", (time.time() - 1, first["id"]))
    assert store.claim("worker-b") is None
    assert store.job(first["id"])["status"] == "interrupted"
    second = store.enqueue(project["id"], "transcribe")
    assert store.claim("worker-b")["id"] == second["id"]


def test_cancel_does_not_reactivate_a_job_from_late_progress(store, project):
    job = store.enqueue(project["id"], "render")
    store.cancel(job["id"])
    store.progress(job["id"], "Late update", 0.9)
    assert store.job(job["id"])["status"] == "cancelled"
    assert store.claim("worker") is None


def test_usage_delivery_is_idempotent_but_real_retries_count(store, project):
    for request_id in ["request-a", "request-a", "request-b"]:
        store.record_usage(project["id"], request_id, {"tokens": 100})
    assert len(store.usage(project["id"])) == 2


def test_srt_import_labels_estimated_word_timing(store, project):
    result = import_transcript(
        store, project["id"], "1\n00:00:01,000 --> 00:00:06,000\nA complete thought.\n", "srt"
    )
    assert result["transcript"]["timing"] == "estimated"
    assert result["words"][0]["start"] == 1 and result["words"][-1]["end"] == pytest.approx(6)


@pytest.mark.parametrize(
    "words",
    [
        [{"text": "later", "start": 2, "end": 3}, {"text": "earlier", "start": 1, "end": 2}],
        [{"text": "outside", "start": 400, "end": 401}],
        [{"text": "invalid", "start": 1, "end": 1}],
    ],
)
def test_transcript_rejects_invalid_source_times(words):
    with pytest.raises((ValueError, ValidationError)):
        validate_words(words, 300)


@pytest.mark.parametrize(
    "url",
    [
        "http://youtube.com/watch?v=abcdefghijk",
        "https://youtube.com.evil.test/watch?v=abcdefghijk",
        "https://127.0.0.1/private",
        "https://youtube.com/shorts/abcdefghijk",
        "https://user:password@youtube.com/watch?v=abcdefghijk",
    ],
)
def test_source_urls_cannot_be_arbitrary_fetch_requests(url):
    with pytest.raises(ValueError):
        youtube_id(url)


def test_valid_youtube_links_are_canonicalized():
    assert youtube_id("https://youtu.be/abcdefghijk?t=20") == "abcdefghijk"
    assert youtube_id("https://www.youtube.com/watch?v=abcdefghijk&list=anything") == "abcdefghijk"


def test_caption_pages_follow_words_speakers_and_pauses():
    words = [
        Word(text=text, start=i, end=i + 0.85, speaker="1" if i == 3 else "0").model_dump()
        for i, text in enumerate(["Keep", "the", "idea.", "Intact."])
    ]
    assert [[w["text"] for w in group] for group in caption_groups(words)] == [
        ["Keep", "the", "idea."],
        ["Intact."],
    ]


def test_headline_check_allows_ai_glyph_ambiguity_but_not_altered_money():
    assert title_readability("AI can help", "Al can help")["pass"]
    assert not title_readability("A $25,000 first customer", "A $250,000 first customer")["pass"]
    assert not title_readability("Keep the whole thought intact", "Keep the thought")["pass"]


def test_contract_rejects_nan_and_overlong_selections():
    with pytest.raises(ValidationError):
        ClipInput(title="A full thought", start=0, end=float("nan"))
    with pytest.raises(ValidationError):
        ClipInput(title="A full thought", start=0, end=181)


def test_guest_bundle_contains_only_approved_assets_and_escapes_copy(store, project, clip):
    work = store.directory(project["id"]) / "renders/test"
    work.mkdir(parents=True)
    (work / "clip.mp4").write_bytes(b"approved video")
    (work / "cover.jpg").write_bytes(b"approved cover")
    store.change(
        project["id"],
        lambda p: p["clips"][0].update(
            status="ready",
            render_directory="renders/test",
            title="<script>alert(1)</script>",
            report={"pass": True, "output_sha256": digest(work / "clip.mp4")},
        ),
    )
    target = make_bundle(store, project["id"])
    with zipfile.ZipFile(target) as archive:
        assert not any(
            "transcript" in name or "keys" in name or "source" in name for name in archive.namelist()
        )
        assert "<script>" not in archive.read("index.html").decode()
        assert len(json.loads(archive.read("manifest.json"))["clips"]) == 1
