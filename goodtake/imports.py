"""Persistent import stages and cancellable source verification, independent of browser lifetime."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from .media import MAX_BYTES, create_project, download, youtube_id
from .process import Cancelled
from .store import new_id
from .worker import safe_error

EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
ACTIVE = {"uploading", "queued", "running", "cancelling"}


class Imports:
    def __init__(self, store):
        self.store = store
        self.threads = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def recover(self):
        for entry in self.store.imports():
            if entry["status"] in ACTIVE:
                self.store.update_import(
                    entry["id"],
                    status="interrupted",
                    stage="Import interrupted",
                    error="The app stopped during this import.",
                    finished=time.time(),
                )

    def close(self):
        self.stop.set()
        with self.lock:
            threads = list(self.threads.values())
        for thread in threads:
            thread.join(timeout=2)

    def create(self, *, filename=None, total_bytes=None, url=None):
        if url:
            video_id = youtube_id(url)
            filename = f"YouTube · {video_id}"
        elif not filename or Path(filename).suffix.lower() not in EXTENSIONS:
            raise ValueError("Choose an MP4, MOV, MKV, M4V or WebM video.")
        if total_bytes is not None and not 0 < total_bytes <= MAX_BYTES:
            raise ValueError("Videos must be smaller than 3 GB.")
        now = time.time()
        name = Path(filename)
        filename = name.name if url else name.stem[:160] + name.suffix.lower()
        entry = {
            "id": new_id(),
            "filename": filename,
            "url": url,
            "status": "queued" if url else "uploading",
            "phase": "connect" if url else "upload",
            "stage": "Connecting to YouTube" if url else "Uploading video",
            "phase_progress": None,
            "bytes_done": 0,
            "bytes_total": total_bytes,
            "created": now,
            "started": now,
            "updated": now,
            "phase_started": now,
            "source_ready": False,
            "project_id": None,
            "error": None,
            "finished": None,
        }
        self.store.add_import(entry)
        return entry

    def source_path(self, entry):
        directory = self.store.root / "imports" / entry["id"]
        directory.mkdir(parents=True, exist_ok=True)
        name = "source" + Path(entry["filename"]).suffix.lower()
        path = directory / name
        if not path.exists():
            recovered = self.store.root / "projects" / entry["id"] / name
            if recovered.exists():
                return recovered
        return path

    def checkpoint(self, import_id):
        if self.stop.is_set() or self.store.import_record(import_id)["status"] not in ACTIVE:
            raise Cancelled("Import stopped")
        if self.store.import_record(import_id)["status"] == "cancelling":
            raise Cancelled("Import stopped")

    def launch(self, import_id):
        with self.lock:
            if import_id in self.threads and self.threads[import_id].is_alive():
                return
            entry = self.store.import_record(import_id)
            if entry["status"] in {"completed", "cancelled", "cancelling"}:
                return
            thread = threading.Thread(
                target=self.process, args=(import_id,), name="goodtake-import", daemon=True
            )
            self.threads[import_id] = thread
            thread.start()

    def process(self, import_id):
        try:
            entry = self.store.import_record(import_id)
            self.checkpoint(import_id)
            self.store.update_import(import_id, status="running")
            try:
                project = self.store.get(import_id)
            except KeyError:

                def checkpoint():
                    self.checkpoint(import_id)

                def progress(**detail):
                    self.store.update_import(import_id, **detail)

                if entry["url"]:
                    project = download(self.store, entry["url"], checkpoint, progress, project_id=import_id)
                else:
                    if not entry["source_ready"]:
                        raise ValueError("Choose the video again to finish this upload.") from None
                    project = create_project(
                        self.store,
                        self.source_path(entry),
                        title=Path(entry["filename"]).stem,
                        move=True,
                        project_id=import_id,
                        checkpoint=checkpoint,
                        progress=progress,
                    )
            self.checkpoint(import_id)
            self.store.update_import(
                import_id,
                status="completed",
                phase="complete",
                stage="Imported",
                phase_progress=1,
                project_id=project["id"],
                finished=time.time(),
                error=None,
            )
        except Cancelled:
            interrupted = self.stop.is_set()
            self.store.update_import(
                import_id,
                status="interrupted" if interrupted else "cancelled",
                stage="Import interrupted" if interrupted else "Stopped",
                finished=time.time(),
            )
        except Exception as error:
            self.store.update_import(
                import_id,
                status="failed",
                stage="Import failed",
                error=safe_error(self.store, error),
                finished=time.time(),
            )

    def retry(self, import_id):
        entry = self.store.import_record(import_id)
        if entry["status"] in ACTIVE or entry["status"] == "completed":
            return entry
        status = "queued" if entry["url"] or entry["source_ready"] else "uploading"
        self.store.update_import(
            import_id,
            status=status,
            phase="connect" if entry["url"] else "inspect" if entry["source_ready"] else "upload",
            stage="Retrying import" if status == "queued" else "Uploading video",
            phase_progress=None,
            started=time.time(),
            finished=None,
            error=None,
        )
        if status == "queued":
            self.launch(import_id)
        return self.store.import_record(import_id)

    def cancel(self, import_id):
        entry = self.store.import_record(import_id)
        if entry["status"] in ACTIVE:
            status = "cancelling" if entry["status"] == "running" else "cancelled"
            self.store.update_import(
                import_id,
                status=status,
                stage="Stopping" if status == "cancelling" else "Stopped",
                finished=None if status == "cancelling" else time.time(),
            )
        return self.store.import_record(import_id)
