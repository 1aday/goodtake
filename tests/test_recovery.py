import copy
import hashlib

import pytest

from goodtake.bundle import make_bundle
from goodtake.cli import wait_for_job
from goodtake.store import new_id
from goodtake.worker import execute


def test_a_cli_worker_does_not_claim_or_cancel_another_queued_project(store, project, monkeypatch):
    unrelated = store.enqueue(project["id"], "transcribe")
    other = copy.deepcopy(project)
    other["id"] = new_id()
    store.put(other)
    called = []
    monkeypatch.setattr(
        "goodtake.worker.transcribe", lambda store, project_id, *args: called.append(project_id)
    )
    result = wait_for_job(store, other["id"], "transcribe", None, lambda *args: None)
    assert result["status"] == "completed"
    assert called == [other["id"]]
    assert store.job(unrelated["id"])["status"] == "queued"


def test_later_clip_failure_does_not_erase_a_completed_export(store, project, clip, monkeypatch):
    second = {**copy.deepcopy(clip), "id": new_id(), "title": "A second moment"}
    store.change(project["id"], lambda p: p["clips"].append(second))
    job = store.enqueue(project["id"], "render")
    job = store.claim("test-worker")

    def renderer(store, project_id, clip_id, *args):
        if clip_id == second["id"]:
            raise RuntimeError("The second render failed")
        store.change(project_id, lambda p: p["clips"][0].update(status="checked", report={"pass": True}))

    monkeypatch.setattr("goodtake.worker.render_clip", renderer)
    execute(store, job)
    assert store.job(job["id"])["status"] == "failed"
    assert store.get(project["id"])["clips"][0]["status"] == "checked"


def test_expired_jobs_cannot_publish_from_late_worker_work(store, project, monkeypatch):
    job = store.enqueue(project["id"], "analyze")
    job = store.claim("expired-worker")
    with store.connect() as db:
        db.execute("UPDATE jobs SET status='interrupted' WHERE id=?", (job["id"],))

    def transcription(store, project_id, checkpoint, progress):
        checkpoint()
        raise AssertionError("An expired worker must stop before transcribing")

    monkeypatch.setattr("goodtake.worker.transcribe", transcription)
    execute(store, job)
    assert store.job(job["id"])["status"] == "cancelled"
    assert not store.get(project["id"])["clips"]


def test_guest_handoff_rejects_files_modified_after_approval(store, project, clip):
    work = store.directory(project["id"]) / "renders/test"
    work.mkdir(parents=True)
    (work / "clip.mp4").write_bytes(b"changed file")
    store.change(
        project["id"],
        lambda p: p["clips"][0].update(
            status="ready",
            render_directory="renders/test",
            report={"pass": True, "output_sha256": hashlib.sha256(b"approved file").hexdigest()},
        ),
    )
    with pytest.raises(ValueError, match="changed"):
        make_bundle(store, project["id"])
