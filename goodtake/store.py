"""Local SQLite metadata, atomic updates and a durable single-worker job queue."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .models import Settings

ID = re.compile(r"^[a-f0-9]{16}$")


def new_id() -> str:
    return uuid.uuid4().hex[:16]


class Store:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(
            root or os.environ.get("GOODTAKE_HOME", Path.home() / ".local/share/goodtake")
        ).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.root / "studio.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, clip_id TEXT, kind TEXT NOT NULL,
                    status TEXT NOT NULL, stage TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
                    created REAL NOT NULL, updated REAL NOT NULL, lease REAL NOT NULL DEFAULT 0,
                    error TEXT, owner TEXT
                );
                CREATE TABLE IF NOT EXISTS usage(id TEXT PRIMARY KEY, project_id TEXT, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS job_progress(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def directory(self, project_id: str) -> Path:
        if not ID.fullmatch(project_id):
            raise ValueError("Invalid project ID.")
        path = self.root / "projects" / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get(self, project_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise KeyError("Project not found.")
        return json.loads(row[0])

    def put(self, project: dict):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO projects VALUES (?,?)", (project["id"], json.dumps(project)))

    def change(self, project_id: str, mutate):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise KeyError("Project not found.")
            project = json.loads(row[0])
            mutate(project)
            project["updated"] = time.time()
            db.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(project), project_id))
        return project

    def projects(self):
        with self.connect() as db:
            rows = db.execute("SELECT data FROM projects").fetchall()
        return sorted((json.loads(row[0]) for row in rows), key=lambda p: p["created"], reverse=True)

    def enqueue(self, project_id: str, kind: str, clip_id: str | None = None):
        self.get(project_id)
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute(
                "SELECT * FROM jobs WHERE project_id=? AND status IN ('queued','running','cancelling')",
                (project_id,),
            ).fetchall()
            if active:
                raise ValueError("This project already has work in the queue. Wait or stop it first.")
            job_id = new_id()
            db.execute(
                "INSERT INTO jobs(id,project_id,clip_id,kind,status,stage,created,updated) "
                "VALUES (?,?,?,?,'queued','Waiting for the editor',?,?)",
                (job_id, project_id, clip_id, kind, now, now),
            )
        return self.job(job_id)

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            detail = db.execute("SELECT data FROM job_progress WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError("Job not found.")
        return {**dict(row), "detail": json.loads(detail[0]) if detail else {}}

    def jobs(self, project_id=None):
        with self.connect() as db:
            rows = db.execute(
                "SELECT jobs.*,job_progress.data AS detail_json FROM jobs LEFT JOIN job_progress USING(id) "
                + ("WHERE project_id=? " if project_id else "")
                + "ORDER BY created DESC LIMIT 50",
                (project_id,) if project_id else (),
            ).fetchall()
        result = []
        for row in rows:
            value = dict(row)
            value["detail"] = json.loads(value.pop("detail_json") or "{}")
            result.append(value)
        return result

    def claim(self, owner: str, only_job=None):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE jobs SET status='interrupted',stage='Editor stopped; retry to resume', "
                "error='The editor stopped before this job finished.' WHERE "
                "status IN ('running','cancelling') AND lease<?",
                (now,),
            )
            if db.execute("SELECT 1 FROM jobs WHERE status IN ('running','cancelling')").fetchone():
                return None
            row = db.execute(
                "SELECT id FROM jobs WHERE status='queued' "
                + ("AND id=? " if only_job else "")
                + "ORDER BY created LIMIT 1",
                (only_job,) if only_job else (),
            ).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE jobs SET status='running',owner=?,lease=?,updated=? WHERE id=?",
                (owner, now + 30, now, row[0]),
            )
            db.execute(
                "INSERT OR REPLACE INTO job_progress VALUES (?,?)",
                (row[0], json.dumps({"started": now, "phase": "prepare", "phase_started": now})),
            )
        return self.job(row[0])

    def progress(self, job_id: str, stage: str, progress: float | None = None, **detail):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job or job[0] != "running":
                return
            row = db.execute("SELECT data FROM job_progress WHERE id=?", (job_id,)).fetchone()
            data = json.loads(row[0]) if row else {}
            if detail.get("phase") and detail["phase"] != data.get("phase"):
                data["phase_started"] = time.time()
            data.update(detail)
            db.execute("INSERT OR REPLACE INTO job_progress VALUES (?,?)", (job_id, json.dumps(data)))
            db.execute(
                "UPDATE jobs SET stage=?,progress=MAX(COALESCE(?,progress),progress),updated=? "
                "WHERE id=? AND status='running'",
                (stage, progress, time.time(), job_id),
            )

    def finish(self, job_id, status, error=None):
        with self.connect() as db:
            row = db.execute("SELECT data FROM job_progress WHERE id=?", (job_id,)).fetchone()
            data = json.loads(row[0]) if row else {}
            data["finished"] = time.time()
            if status == "completed":
                data.update(phase="complete", phase_progress=1)
            db.execute("INSERT OR REPLACE INTO job_progress VALUES (?,?)", (job_id, json.dumps(data)))
            db.execute(
                "UPDATE jobs SET status=?,error=?,updated=?,stage=?,progress=CASE WHEN ?='completed' THEN 1 ELSE progress END WHERE id=?",
                (
                    status,
                    error,
                    time.time(),
                    "Finished" if status == "completed" else status.replace("_", " "),
                    status,
                    job_id,
                ),
            )

    def heartbeat(self, job_id, owner):
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET lease=? WHERE id=? AND owner=? AND status IN ('running','cancelling')",
                (time.time() + 30, job_id, owner),
            )

    def cancel(self, job_id):
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET status=CASE WHEN status='queued' THEN 'cancelled' ELSE 'cancelling' END "
                ",updated=? WHERE id=? AND status IN ('queued','running')",
                (time.time(), job_id),
            )

    def import_record(self, import_id):
        if not ID.fullmatch(import_id):
            raise KeyError(import_id)
        with self.connect() as db:
            row = db.execute("SELECT data FROM imports WHERE id=?", (import_id,)).fetchone()
        if not row:
            raise KeyError(import_id)
        return json.loads(row[0])

    def imports(self):
        with self.connect() as db:
            rows = db.execute("SELECT data FROM imports").fetchall()
        return sorted((json.loads(row[0]) for row in rows), key=lambda item: item["created"], reverse=True)[
            :25
        ]

    def add_import(self, record):
        with self.connect() as db:
            db.execute("INSERT INTO imports VALUES (?,?)", (record["id"], json.dumps(record)))

    def update_import(self, import_id, **changes):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM imports WHERE id=?", (import_id,)).fetchone()
            if not row:
                raise KeyError(import_id)
            data = json.loads(row[0])
            if data["status"] in {"cancelled", "cancelling"} and changes.get("status") not in {
                "queued",
                "uploading",
                "cancelled",
                "interrupted",
            }:
                return data
            if changes.get("phase") and changes["phase"] != data.get("phase"):
                data["phase_started"] = time.time()
            data.update(changes, updated=time.time())
            db.execute("UPDATE imports SET data=? WHERE id=?", (json.dumps(data), import_id))
        return data

    def settings(self) -> Settings:
        path = self.root / "settings.json"
        return (
            Settings.model_validate_json(path.read_text())
            if path.exists()
            else Settings(
                editor_model=os.environ.get("GOODTAKE_EDITOR_MODEL", "gpt-5.1"),
                whisper_model=os.environ.get("GOODTAKE_WHISPER_MODEL", "base.en"),
            )
        )

    def save_settings(self, settings: Settings):
        path = self.root / "settings.json"
        path.write_text(settings.model_dump_json(indent=2))
        path.chmod(0o600)

    def key(self, name):
        path = self.root / "keys.json"
        return os.environ.get(name) or (json.loads(path.read_text()).get(name) if path.exists() else None)

    def save_keys(self, keys):
        path = self.root / "keys.json"
        previous = json.loads(path.read_text()) if path.exists() else {}
        for name, value in keys.items():
            if name not in {"OPENAI_API_KEY", "ELEVENLABS_API_KEY"}:
                raise ValueError("Unknown provider.")
            if value is not None:
                previous[name] = value.strip()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump(previous, file)
        path.chmod(0o600)

    def record_usage(self, project_id, request_id, data):
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO usage VALUES (?,?,?)", (request_id, project_id, json.dumps(data))
            )

    def usage(self, project_id):
        with self.connect() as db:
            rows = db.execute("SELECT data FROM usage WHERE project_id=?", (project_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]
