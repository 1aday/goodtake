"""One persisted job at a time. Completed clips remain saved if later work fails."""

from __future__ import annotations

import re
import threading

from .editorial import select
from .process import Cancelled
from .providers import transcribe
from .render import render_clip
from .store import new_id


def safe_error(store, error):
    text = str(error).replace(str(store.root), "<local data>")
    for name in ("OPENAI_API_KEY", "ELEVENLABS_API_KEY"):
        key = store.key(name)
        if key:
            text = text.replace(key, "<redacted>")
    return re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "<redacted>", text)[:1600]


def execute(store, job, stop=None):
    def checkpoint():
        if (stop and stop.is_set()) or store.job(job["id"])["status"] != "running":
            raise Cancelled("Stopped. Completed exports and checkpoints are retained.")

    def progress(stage, value=0):
        store.progress(job["id"], stage, value)

    try:
        if job["kind"] in {"transcribe", "analyze"}:
            transcribe(store, job["project_id"], checkpoint, progress)
        if job["kind"] == "analyze":
            select(store, job["project_id"], checkpoint, progress)
        if job["kind"] == "render":
            project = store.get(job["project_id"])
            clips = (
                [c for c in project["clips"] if c["id"] == job["clip_id"]]
                if job["clip_id"]
                else [c for c in project["clips"] if c["status"] not in {"checked", "ready"}]
            )
            if not clips:
                raise ValueError("No clips need an export. Add a moment first.")
            for clip in clips:
                checkpoint()
                render_clip(store, job["project_id"], clip["id"], checkpoint, progress)
        checkpoint()
        store.finish(job["id"], "completed")
    except Cancelled as error:
        store.finish(job["id"], "cancelled", safe_error(store, error))
    except Exception as error:
        store.finish(job["id"], "failed", safe_error(store, error))


class Worker:
    def __init__(self, store, only_job=None):
        self.store = store
        self.only_job = only_job
        self.owner = new_id()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, name="goodtake-editor", daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=4)

    def loop(self):
        while not self.stop.is_set():
            if self.only_job and self.store.job(self.only_job)["status"] not in {
                "queued",
                "running",
                "cancelling",
            }:
                return
            job = self.store.claim(self.owner, self.only_job)
            if not job:
                self.stop.wait(0.5)
                continue
            done = threading.Event()

            def heartbeat(done=done, job_id=job["id"]):
                while not done.wait(5):
                    self.store.heartbeat(job_id, self.owner)

            beat = threading.Thread(target=heartbeat, daemon=True)
            beat.start()
            try:
                execute(self.store, job, self.stop)
            finally:
                done.set()
                beat.join(timeout=1)
