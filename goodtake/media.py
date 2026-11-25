"""Source acquisition and explicit transcript provenance. Imported SRT timing is approximate."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

from .models import Brand, Word
from .process import run
from .store import new_id

MAX_BYTES = 3 * 1024**3


def digest(path: Path, checkpoint=lambda: None, progress=None):
    hasher = hashlib.sha256()
    total, done = path.stat().st_size, 0
    with path.open("rb") as file:
        while block := file.read(4 * 1024**2):
            checkpoint()
            hasher.update(block)
            done += len(block)
            if progress:
                progress(done, total)
    return hasher.hexdigest()


def probe(path):
    data = json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path]))
    videos = [s for s in data["streams"] if s["codec_type"] == "video"]
    audio = [s for s in data["streams"] if s["codec_type"] == "audio"]
    duration = float(data["format"].get("duration", 0))
    if not videos or not audio or not math.isfinite(duration) or not 5 <= duration <= 10800:
        raise ValueError("Use a video with audio, between five seconds and three hours long.")
    return {"duration": duration, "width": videos[0]["width"], "height": videos[0]["height"]}


def create_project(
    store,
    source: Path,
    *,
    title=None,
    brand=None,
    move=False,
    sample=False,
    project_id=None,
    checkpoint=lambda: None,
    progress=lambda **kwargs: None,
):
    if not source.is_file() or source.stat().st_size > MAX_BYTES:
        raise ValueError("Use an existing video under 3 GB.")
    checkpoint()
    progress(phase="inspect", stage="Checking video", phase_progress=None, bytes_done=None, bytes_total=None)
    meta = probe(source)
    checkpoint()
    project_id = project_id or new_id()
    directory = store.directory(project_id)
    target = directory / (
        "source"
        + (
            source.suffix.lower()
            if source.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
            else ".mp4"
        )
    )
    if source.resolve() != target.resolve():
        progress(phase="save", stage="Saving video", phase_progress=None)
        if move:
            shutil.move(source, target)
        else:
            total, done = source.stat().st_size, 0
            with source.open("rb") as original, target.open("wb") as saved:
                while block := original.read(4 * 1024**2):
                    checkpoint()
                    saved.write(block)
                    done += len(block)
                    progress(
                        phase="save",
                        stage="Saving video",
                        phase_progress=done / total,
                        bytes_done=done,
                        bytes_total=total,
                    )
    progress(phase="hash", stage="Verifying source", phase_progress=0)
    source_digest = digest(
        target,
        checkpoint,
        lambda done, total: progress(
            phase="hash",
            stage="Verifying source",
            phase_progress=done / total,
            bytes_done=done,
            bytes_total=total,
        ),
    )
    checkpoint()
    project = {
        "id": project_id,
        "title": title or source.stem,
        "source_name": source.name,
        "source_file": target.name,
        "source_sha256": source_digest,
        **meta,
        "brand": (brand or Brand()).model_dump(),
        "words": [],
        "transcript": None,
        "clips": [],
        "created": time.time(),
        "updated": time.time(),
        "sample": sample,
    }
    store.put(project)
    return project


def youtube_id(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("Paste an HTTPS YouTube video URL, or upload the original video.")
    if parsed.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        raise ValueError("Only YouTube video links are supported. Upload other sources as files.")
    if "/shorts/" in parsed.path:
        raise ValueError("Use a full conversation rather than a YouTube Short.")
    import urllib.parse

    value = (
        parsed.path.strip("/")
        if parsed.hostname == "youtu.be"
        else (
            urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
            if parsed.path == "/watch"
            else parsed.path.removeprefix("/live/")
        )
    )
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        raise ValueError("Paste a single YouTube video URL.")
    return value


def download(store, url, checkpoint=lambda: None, progress=lambda **kwargs: None, project_id=None):
    import tempfile

    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        raise ValueError('Install YouTube support with pip install "goodtake-studio[youtube]".') from None
    import sys

    video_id = youtube_id(url)
    progress(phase="connect", stage="Connecting to YouTube", phase_progress=None)
    with tempfile.TemporaryDirectory(dir=store.root) as temporary:
        target = Path(temporary) / "source.mp4"
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--newline",
            "--no-colors",
            "--progress-template",
            "download:goodtake:%(progress)j",
            "--max-filesize",
            "3G",
            "--match-filter",
            "duration >= 5 & duration <= 10800 & !is_live",
            "--merge-output-format",
            "mp4",
            "-f",
            "bv*[height<=1080]+ba/b[height<=1080]",
            "-o",
            target,
            f"https://www.youtube.com/watch?v={video_id}",
        ]

        tracks = {}

        def report(line):
            if not line.startswith("goodtake:"):
                return
            try:
                value = json.loads(line[len("goodtake:") :])
                done = value.get("downloaded_bytes", 0)
                total = value.get("total_bytes")
                filename = value.get("filename") or "source"
                tracks.setdefault(filename, len(tracks) + 1)
                progress(
                    phase="download",
                    stage=f"Downloading track {tracks[filename]}",
                    phase_progress=done / total if total else None,
                    bytes_done=done,
                    bytes_total=total,
                    speed=value.get("speed"),
                    transfer_file=tracks[filename],
                )
            except (ValueError, TypeError):
                return

        run(command, timeout=1800, checkpoint=checkpoint, on_line=report)
        if not target.exists():
            raise ValueError("YouTube did not provide a usable file. Upload the original video to continue.")
        project = create_project(
            store,
            target,
            title=f"YouTube · {video_id}",
            move=True,
            project_id=project_id,
            checkpoint=checkpoint,
            progress=progress,
        )
        store.change(
            project["id"], lambda p: p.update(source_url=f"https://www.youtube.com/watch?v={video_id}")
        )
        return store.get(project["id"])


def validate_words(raw, duration):
    if not isinstance(raw, list) or not raw or len(raw) > 100000:
        raise ValueError("The transcript must contain between 1 and 100,000 timed words.")
    words = []
    previous = -1
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each transcript word must be an object with text, start and end.")
        if item.get("type", "word") != "word":
            continue
        word = Word(
            text=str(item.get("text") or item.get("word", "")).strip(),
            start=item.get("start"),
            end=item.get("end"),
            speaker=str(item.get("speaker", item.get("speaker_id", "0"))),
        )
        if word.start < previous - 0.01 or word.end > duration + 0.3:
            raise ValueError("Transcript timestamps must be chronological and inside the source video.")
        previous = word.start
        words.append(word.model_dump())
    if not words:
        raise ValueError("No spoken words were found.")
    return words


def srt_words(text):
    def seconds(value):
        parts = re.split(r"[:,.]", value)
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) + int(parts[3]) / 1000

    words = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "").strip()):
        match = re.search(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})", block)
        if not match:
            continue
        start, end = (seconds(value) for value in match.groups())
        tokens = re.sub(r"<[^>]+>", "", block[match.end() :]).split()
        if not tokens or end <= start:
            continue
        total = sum(max(1, len(token)) for token in tokens)
        current = start
        for token in tokens:
            length = (end - start) * max(1, len(token)) / total
            words.append({"text": token, "start": current, "end": current + length, "speaker": "0"})
            current += length
    return words


def import_transcript(store, project_id, content, kind="json"):
    project = store.get(project_id)
    if kind == "srt":
        raw = srt_words(content)
        method, timing = "Imported SRT", "estimated"
    else:
        data = json.loads(content)
        raw = data.get("words") if isinstance(data, dict) else data
        method, timing = "Imported word timestamps", "imported"
    words = validate_words(raw, project["duration"])

    def update(p):
        p["words"] = words
        p["transcript"] = {"method": method, "timing": timing, "source_sha256": p["source_sha256"]}
        for clip in p["clips"]:
            clip["status"] = "draft"
            clip.pop("report", None)
            clip.pop("render_directory", None)

    return store.change(project_id, update)
