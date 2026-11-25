import copy
import sys
import threading
import time

from fastapi.testclient import TestClient

from goodtake.imports import Imports
from goodtake.process import run
from goodtake.server import create_app
from goodtake.store import Store, new_id
from goodtake.worker import execute

HEADERS = {"X-Goodtake": "1"}


def test_stage_progress_is_persisted_monotonic_and_fenced_after_stop(store, project):
    job = store.enqueue(project["id"], "render")
    store.claim("worker")
    store.progress(
        job["id"],
        "Rendering",
        0.6,
        phase="render",
        phase_progress=0.5,
        units_done=30,
        units_total=60,
        unit="frames",
    )
    store.progress(job["id"], "Checking", 0.4, phase="verify", phase_progress=None)
    fresh = Store(store.root).job(job["id"])
    assert fresh["progress"] == 0.6
    assert fresh["detail"]["phase"] == "verify"
    assert fresh["detail"]["phase_progress"] is None
    store.cancel(job["id"])
    store.progress(job["id"], "Late renderer callback", 1, phase="render")
    assert store.job(job["id"])["stage"] == "Checking"
    store.finish(job["id"], "cancelled")
    assert store.job(job["id"])["progress"] == 0.6
    assert store.job(job["id"])["detail"]["finished"] >= fresh["detail"]["started"]


def test_multiple_exports_keep_overall_progress_and_saved_counts(store, project, clip, monkeypatch):
    second = {**copy.deepcopy(clip), "id": new_id()}
    store.change(project["id"], lambda p: p["clips"].append(second))
    store.enqueue(project["id"], "render")
    job = store.claim("worker")
    seen = []

    def renderer(store, project_id, clip_id, checkpoint, progress):
        progress("Rendering", 0.5, phase="render", phase_progress=0.5)
        seen.append(store.job(job["id"]))
        store.change(
            project_id, lambda p: next(c for c in p["clips"] if c["id"] == clip_id).update(status="checked")
        )

    monkeypatch.setattr("goodtake.worker.render_clip", renderer)
    execute(store, job)
    assert [item["progress"] for item in seen] == [0.25, 0.75]
    assert seen[1]["detail"]["completed_clips"] == 1
    final = store.job(job["id"])
    assert final["detail"]["completed_clips"] == final["detail"]["checked_clips"] == 2
    assert final["progress"] == 1


def test_process_streams_lines_while_work_is_running():
    lines = []
    text = run(
        [sys.executable, "-u", "-c", "import time;print('first');time.sleep(.5);print('last')"],
        on_line=lines.append,
    )
    assert lines == ["first", "last"]
    assert "first\nlast" in text


def test_import_activity_is_saved_before_processing_and_file_is_verified(store, monkeypatch):
    waiting = threading.Event()
    release = threading.Event()

    def create(store, source, *, project_id, progress, **kwargs):
        assert source.read_bytes() == b"complete video"
        progress(phase="hash", stage="Verifying source", phase_progress=0.5, bytes_done=7, bytes_total=14)
        waiting.set()
        assert release.wait(3)
        value = {"id": project_id}
        store.put(value)
        return value

    monkeypatch.setattr("goodtake.imports.create_project", create)
    with TestClient(create_app(store, testing=True, run_worker=False)) as client:
        entry = client.post(
            "/api/imports", headers=HEADERS, json={"filename": "talk.mp4", "total_bytes": 14}
        ).json()
        # Mismatched length is retained as a retryable failure, not an imported project.
        response = client.post(
            f"/api/imports/{entry['id']}/file", headers=HEADERS, files={"file": ("talk.mp4", b"partial")}
        )
        assert response.status_code == 422
        failed = client.get("/api/activity").json()["imports"][0]
        assert failed["status"] == "failed" and not failed["source_ready"]
        client.post(f"/api/imports/{entry['id']}/retry", headers=HEADERS)
        client.post(
            f"/api/imports/{entry['id']}/file",
            headers=HEADERS,
            files={"file": ("talk.mp4", b"complete video")},
        )
        assert waiting.wait(3)
        active = client.get("/api/activity").json()["imports"][0]
        assert active["phase"] == "hash" and active["phase_progress"] == 0.5
        assert active["source_ready"] and active["project_id"] is None
        release.set()
        deadline = time.monotonic() + 3
        while store.import_record(entry["id"])["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.01)
    completed = Store(store.root).import_record(entry["id"])
    assert completed["status"] == "completed" and completed["project_id"] == entry["id"]


def test_cancelled_upload_can_retry_but_late_progress_cannot_restart_it(store):
    imports = Imports(store)
    entry = imports.create(filename="talk.mp4", total_bytes=10)
    imports.cancel(entry["id"])
    store.update_import(entry["id"], phase="hash", stage="Late progress")
    assert store.import_record(entry["id"])["stage"] == "Stopped"
    retried = imports.retry(entry["id"])
    assert retried["status"] == "uploading" and not retried["source_ready"]


def test_recover_import_after_project_commit_does_not_duplicate_source(store, monkeypatch):
    imports = Imports(store)
    entry = imports.create(filename="talk.mp4", total_bytes=10)
    store.update_import(entry["id"], source_ready=True, status="queued")
    store.put({"id": entry["id"], "created": time.time()})
    imports.recover()
    assert store.import_record(entry["id"])["status"] == "interrupted"
    monkeypatch.setattr(
        "goodtake.imports.create_project", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Duplicate"))
    )
    imports.retry(entry["id"])
    imports.threads[entry["id"]].join(3)
    assert store.import_record(entry["id"])["status"] == "completed"
    assert len(store.projects()) == 1


def test_youtube_reports_only_measured_bytes_and_separate_tracks(store, project, monkeypatch):
    import json
    from pathlib import Path

    from goodtake.media import download

    # The downloader process is stubbed; this parser test needs no optional installation.
    monkeypatch.setitem(sys.modules, "yt_dlp", object())

    def downloader(args, *, on_line, **kwargs):
        assert args[args.index("--progress-template") + 1] == "download:goodtake:%(progress)j"
        on_line(
            "goodtake:" + json.dumps({"filename": "video.mp4", "downloaded_bytes": 50, "total_bytes": 100})
        )
        on_line(
            "goodtake:"
            + json.dumps({"filename": "audio.m4a", "downloaded_bytes": 20, "total_bytes_estimate": 90})
        )
        Path(args[args.index("-o") + 1]).write_bytes(b"video")

    monkeypatch.setattr("goodtake.media.run", downloader)
    monkeypatch.setattr("goodtake.media.create_project", lambda *args, **kwargs: project)
    events = []
    download(
        store, "https://www.youtube.com/watch?v=abcdefghijk", progress=lambda **data: events.append(data)
    )
    measured, unknown = [event for event in events if event["phase"] == "download"]
    assert measured["phase_progress"] == 0.5 and measured["stage"] == "Downloading track 1"
    assert unknown["phase_progress"] is None and unknown["bytes_total"] is None
    assert unknown["stage"] == "Downloading track 2"
