"""Loopback-only studio API. No telemetry, external scripts, account or cloud infrastructure."""

from __future__ import annotations

import importlib.util
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .bundle import make_bundle
from .media import MAX_BYTES, create_project, digest, download, import_transcript
from .models import Brand, ClipInput, Contract, Settings
from .store import Store, new_id
from .worker import Worker, safe_error

WEB = Path(__file__).parent / "web"


def doctor(store):
    return {
        "version": __version__,
        "tools": {
            name: bool(shutil.which(name)) for name in ["node", "npm", "ffmpeg", "ffprobe", "tesseract"]
        },
        "local_speech": bool(importlib.util.find_spec("faster_whisper")),
        "youtube": bool(importlib.util.find_spec("yt_dlp")),
        "providers": {
            "openai": bool(store.key("OPENAI_API_KEY")),
            "elevenlabs": bool(store.key("ELEVENLABS_API_KEY")),
        },
    }


class SettingsInput(Contract):
    settings: Settings
    openai_key: str | None = Field(default=None, max_length=4096)
    elevenlabs_key: str | None = Field(default=None, max_length=4096)


class ProjectInput(Contract):
    title: str = Field(min_length=1, max_length=150)
    brand: Brand


class UrlInput(Contract):
    url: str = Field(max_length=1000)


def create_app(store=None, *, testing=False, run_worker=True):
    store = store or Store()
    worker = Worker(store)

    @asynccontextmanager
    async def lifespan(app):
        if run_worker:
            worker.start()
        yield
        if run_worker:
            worker.close()

    app = FastAPI(title="Goodtake", version=__version__, lifespan=lifespan)
    app.state.store = store
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]"] + (["testserver"] if testing else []),
    )

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("x-goodtake") != "1":
                return JSONResponse({"detail": "Local requests require X-Goodtake: 1."}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    {"detail": "This studio only accepts same-origin changes."}, status_code=403
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; "
            "font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
        )
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(KeyError)
    async def not_found(request, error):
        return JSONResponse({"detail": "Project, clip or job not found."}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": safe_error(store, error)}, status_code=422)

    @app.exception_handler(RuntimeError)
    async def media_error(request, error):
        return JSONResponse({"detail": safe_error(store, error)}, status_code=422)

    def unlocked(project_id):
        if any(j["status"] in {"queued", "running", "cancelling"} for j in store.jobs(project_id)):
            raise HTTPException(409, "Stop or finish this project's queued work before editing it.")

    def public(project, summary=False):
        data = {key: value for key, value in project.items() if key not in {"source_file", "source_sha256"}}
        data["source_url_local"] = f"/api/projects/{project['id']}/source"
        if summary:
            data.pop("words", None)
        data["clips"] = []
        for clip in project["clips"]:
            value = {key: item for key, item in clip.items() if key != "render_directory"}
            if clip.get("render_directory") and clip["status"] in {"checked", "ready", "needs_review"}:
                value["video_url"] = f"/api/projects/{project['id']}/clips/{clip['id']}/assets/clip.mp4"
                value["cover_url"] = f"/api/projects/{project['id']}/clips/{clip['id']}/assets/cover.jpg"
                value["sheet_url"] = (
                    f"/api/projects/{project['id']}/clips/{clip['id']}/assets/contact-sheet.jpg"
                )
            data["clips"].append(value)
        return data

    @app.get("/api/status")
    def status():
        from .render import layout

        return {
            **doctor(store),
            "settings": store.settings().model_dump(),
            "layouts": {
                ratio: {
                    template: layout({"ratio": ratio, "template": template})
                    for template in ["editorial", "paper", "focus"]
                }
                for ratio in ["9:16", "4:5"]
            },
        }

    @app.put("/api/settings")
    def settings(body: SettingsInput):
        store.save_settings(body.settings)
        store.save_keys({"OPENAI_API_KEY": body.openai_key, "ELEVENLABS_API_KEY": body.elevenlabs_key})
        return {**doctor(store), "settings": store.settings().model_dump()}

    @app.get("/api/projects")
    def projects():
        return [public(project, True) for project in store.projects()]

    @app.post("/api/projects/upload")
    async def upload(file: UploadFile = File(...)):
        suffix = Path(file.filename or "video.mp4").suffix.lower()
        if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
            raise ValueError("Upload an MP4, MOV, MKV, M4V or WebM video.")
        target = store.root / ("incoming-" + new_id() + suffix)
        size = 0
        try:
            with target.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(413, "Videos must be smaller than 3 GB.")
                    output.write(chunk)
            result = await run_in_threadpool(
                create_project, store, target, title=Path(file.filename).stem, move=True
            )
            return public(result)
        finally:
            target.unlink(missing_ok=True)
            await file.close()

    @app.post("/api/projects/youtube")
    def youtube(body: UrlInput):
        return public(download(store, body.url))

    @app.post("/api/sample")
    def sample():
        from .sample import load_sample

        return public(load_sample(store))

    @app.get("/api/projects/{project_id}")
    def project(project_id: str):
        return {
            **public(store.get(project_id)),
            "jobs": store.jobs(project_id),
            "usage": store.usage(project_id),
        }

    @app.put("/api/projects/{project_id}")
    def update_project(project_id: str, body: ProjectInput):
        unlocked(project_id)

        def update(p):
            p["title"] = body.title
            if p["brand"] != body.brand.model_dump():
                p["brand"] = body.brand.model_dump()
                for clip in p["clips"]:
                    clip["status"] = "draft"
                    clip.pop("report", None)
                    clip.pop("render_directory", None)

        return public(store.change(project_id, update))

    @app.get("/api/projects/{project_id}/source")
    def source(project_id: str):
        project = store.get(project_id)
        return FileResponse(store.directory(project_id) / project["source_file"], media_type="video/mp4")

    @app.post("/api/projects/{project_id}/transcript")
    async def transcript(project_id: str, file: UploadFile = File(...)):
        unlocked(project_id)
        content = await file.read(12 * 1024**2 + 1)
        await file.close()
        if len(content) > 12 * 1024**2:
            raise ValueError("Transcripts must be smaller than 12 MB.")
        kind = "srt" if (file.filename or "").lower().endswith(".srt") else "json"
        return public(import_transcript(store, project_id, content.decode("utf-8-sig"), kind))

    @app.post("/api/projects/{project_id}/clips")
    def add_clip(project_id: str, body: ClipInput):
        unlocked(project_id)

        def update(p):
            if body.end > p["duration"] + 0.05:
                raise ValueError("This range extends beyond the source video.")
            p["clips"].append(
                {
                    **body.model_dump(),
                    "id": new_id(),
                    "status": "draft",
                    "editorial": {"method": "Selected by you"},
                }
            )

        return public(store.change(project_id, update))

    @app.put("/api/projects/{project_id}/clips/{clip_id}")
    def update_clip(project_id: str, clip_id: str, body: ClipInput):
        unlocked(project_id)

        def update(p):
            if body.end > p["duration"] + 0.05:
                raise ValueError("This range extends beyond the source video.")
            clip = next((c for c in p["clips"] if c["id"] == clip_id), None)
            if not clip:
                raise KeyError(clip_id)
            if any(clip.get(key) != value for key, value in body.model_dump().items()):
                p["clips"][p["clips"].index(clip)] = {
                    **body.model_dump(),
                    "id": clip_id,
                    "status": "draft",
                    "editorial": {"method": "Edited by you; review this selection"},
                }

        return public(store.change(project_id, update))

    @app.delete("/api/projects/{project_id}/clips/{clip_id}")
    def delete_clip(project_id: str, clip_id: str):
        unlocked(project_id)
        return public(
            store.change(project_id, lambda p: p.update(clips=[c for c in p["clips"] if c["id"] != clip_id]))
        )

    @app.post("/api/projects/{project_id}/clips/{clip_id}/approve")
    def approve(project_id: str, clip_id: str):
        unlocked(project_id)

        def update(p):
            clip = next((c for c in p["clips"] if c["id"] == clip_id), None)
            if not clip:
                raise KeyError(clip_id)
            if clip["status"] not in {"checked", "ready"} or not clip.get("report", {}).get("pass"):
                raise ValueError("All export checks must pass before creative approval.")
            clip["status"] = "ready"
            clip["report"]["creative_approval"] = True

        return public(store.change(project_id, update))

    @app.post("/api/projects/{project_id}/jobs/{kind}")
    def start_job(project_id: str, kind: str, clip_id: str | None = None):
        if kind not in {"transcribe", "analyze", "render"}:
            raise HTTPException(404)
        project = store.get(project_id)
        if kind == "analyze" and not store.key("OPENAI_API_KEY"):
            raise ValueError("Add an OpenAI key in Settings, or select a moment manually.")
        if kind == "render" and not project["words"]:
            raise ValueError("Transcribe the video or import timed words before exporting.")
        return store.enqueue(project_id, kind, clip_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def stop_job(job_id: str):
        store.job(job_id)
        store.cancel(job_id)
        return store.job(job_id)

    @app.get("/api/projects/{project_id}/clips/{clip_id}/assets/{name}")
    def asset(project_id: str, clip_id: str, name: str, download: bool = False):
        if name not in {"clip.mp4", "cover.jpg", "contact-sheet.jpg", "report.json"}:
            raise HTTPException(404)
        project = store.get(project_id)
        clip = next((c for c in project["clips"] if c["id"] == clip_id), None)
        if not clip or not clip.get("render_directory"):
            raise HTTPException(404)
        # Failed exports are available only as clearly labelled review copies; never in approved kits.
        if download and clip["status"] == "needs_review" and name == "clip.mp4":
            raise HTTPException(409, "Resolve failed export checks before downloading a finished clip.")
        path = (store.directory(project_id) / clip["render_directory"] / name).resolve()
        if not path.is_relative_to(store.directory(project_id)) or not path.is_file():
            raise HTTPException(404)
        if download and name == "clip.mp4" and digest(path) != clip.get("report", {}).get("output_sha256"):
            raise HTTPException(409, "The export changed after its checks. Export and verify it again.")
        filename = f"{clip['title'][:60]}.mp4" if name == "clip.mp4" else name
        return FileResponse(path, filename=filename if download else None)

    @app.get("/api/projects/{project_id}/kit")
    def kit(project_id: str):
        return FileResponse(
            make_bundle(store, project_id), filename="goodtake-guest-kit.zip", media_type="application/zip"
        )

    @app.get("/")
    def home():
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app
