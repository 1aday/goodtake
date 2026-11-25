"""Local Remotion adapter. Prepared audio is muxed unchanged after the silent picture render."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from .editorial import excerpt
from .media import digest
from .models import caption_groups
from .process import run

RENDERER = Path(__file__).parent / "renderer"


def renderer_digest():
    hasher = hashlib.sha256()
    for file in sorted(
        [
            RENDERER / "package.json",
            RENDERER / "package-lock.json",
            RENDERER / "render.mjs",
            *list((RENDERER / "src").glob("*.tsx")),
        ]
    ):
        hasher.update(file.name.encode())
        hasher.update(file.read_bytes())
    return hasher.hexdigest()


def ensure_renderer(store, checkpoint=lambda: None, progress=lambda *args: None):
    if not shutil.which("node") or not shutil.which("npm"):
        raise ValueError("Install Node.js 22+ to run the local video renderer, then run goodtake setup.")
    version = int(run(["node", "--version"]).strip().lstrip("v").split(".")[0])
    if version < 22:
        raise ValueError("The renderer needs Node.js 22 or newer.")
    root = Path(os.environ.get("GOODTAKE_RUNTIME", store.root / "runtime")) / (
        "renderer-" + renderer_digest()[:12]
    )
    if not (root / "node_modules/remotion/package.json").exists():
        progress("Installing the local renderer (first run only)", 0.02)
        shutil.copytree(
            RENDERER, root, dirs_exist_ok=True, ignore=shutil.ignore_patterns("node_modules", "bundle")
        )
        run(
            ["npm", "ci", "--omit=dev", "--no-audit", "--no-fund"],
            cwd=root,
            timeout=600,
            checkpoint=checkpoint,
        )
    return root


def layout(style):
    vertical = style["ratio"] == "9:16"
    result = {
        "header": [72, 72 if vertical else 42, 936, 100 if vertical else 70],
        "title": [72, 210 if vertical else 140, 936, 240 if vertical else 180],
        "video": [40, 490 if vertical else 350, 1000, 890 if vertical else 630],
        "captions": [65, 1430 if vertical else 1020, 950, 220 if vertical else 180],
        "footer": [72, 1755 if vertical else 1250, 936, 60],
    }
    if style["template"] == "focus":
        result.update(
            video=[24, 30, 1032, 1660 if vertical else 1180],
            header=[60, 72 if vertical else 42, 960, 95],
            title=[60, 210 if vertical else 145, 960, 260 if vertical else 190],
            captions=[65, 1390 if vertical else 940, 950, 220],
        )
    return result


def render_clip(store, project_id, clip_id, checkpoint=lambda: None, progress=lambda *args: None):
    from .quality import verify

    project = store.get(project_id)
    clip = next((c for c in project["clips"] if c["id"] == clip_id), None)
    if not clip:
        raise ValueError("Clip not found.")
    directory = store.directory(project_id)
    source = directory / project["source_file"]
    progress("Verifying the original source", 0.02)
    source_digest = digest(source)
    if source_digest != project["source_sha256"]:
        raise ValueError("The source file changed. Import it again to create a new project.")
    start, end, words = excerpt(clip, project["words"], project["duration"])
    duration = round(end - start, 6)
    props = {
        "title": clip["title"],
        "takeaway": clip["takeaway"],
        "duration": duration,
        "brand": project["brand"],
        "style": clip["style"],
        "words": words,
        "groups": caption_groups(words),
        "layout": layout(clip["style"]),
    }
    identity = hashlib.sha256(
        json.dumps(
            {
                "source": source_digest,
                "start": start,
                "end": end,
                "props": props,
                "renderer": renderer_digest(),
                "version": 1,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    work = directory / "renders" / clip_id / identity[:16]
    work.mkdir(parents=True, exist_ok=True)
    manifest = work / "checkpoint.json"
    output = work / "clip.mp4"
    audio = work / "audio.m4a"
    reusable = False
    if manifest.exists() and output.exists() and audio.exists():
        saved = json.loads(manifest.read_text())
        reusable = (
            saved.get("identity") == identity
            and saved.get("sha256") == digest(output)
            and saved.get("audio_sha256") == digest(audio)
        )
    if not reusable:
        runtime = ensure_renderer(store, checkpoint, progress)
        progress("Preparing one continuous source excerpt", 0.08)
        media = work / "media"
        media.mkdir(exist_ok=True)
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                start,
                "-i",
                source,
                "-t",
                duration,
                "-an",
                "-vf",
                "scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
                "-r",
                "30",
                "-c:v",
                "libx264",
                "-crf",
                "17",
                "-preset",
                "fast",
                media / "source.mp4",
            ],
            checkpoint=checkpoint,
            timeout=600,
        )
        total = duration + (2.4 if project["brand"]["end_card"] else 0)
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                start,
                "-i",
                source,
                "-vn",
                "-af",
                f"atrim=duration={duration},aresample=48000,asetpts=N/SR/TB,loudnorm=I=-16:TP=-2:LRA=9,"
                f"aresample=48000,alimiter=limit=0.79:level=false:latency=true,apad=whole_dur={total},atrim=duration={total}",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                audio,
            ],
            checkpoint=checkpoint,
            timeout=300,
        )
        (work / "props.json").write_text(json.dumps(props))

        def tick():
            path = work / "progress.json"
            try:
                info = json.loads(path.read_text())
                progress(info["stage"], 0.15 + 0.6 * min(1, max(0, info["progress"])))
            except (OSError, ValueError, KeyError):
                pass

        node_env = {}
        if not os.environ.get("CHROME_PATH"):
            chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            if chrome.exists():
                node_env["CHROME_PATH"] = str(chrome)
        progress("Checking headline layout before the full render", 0.12)
        run(
            ["node", runtime / "render.mjs", work / "props.json", work / "preview.png", "still"],
            checkpoint=checkpoint,
            timeout=300,
            env=node_env,
        )
        from .quality import title_check

        title_check(work / "preview.png", props, work)
        run(
            ["node", runtime / "render.mjs", work / "props.json", work / "silent.mp4"],
            checkpoint=checkpoint,
            timeout=1800,
            tick=tick,
            env=node_env,
        )
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                work / "silent.mp4",
                "-i",
                audio,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                output,
            ],
            checkpoint=checkpoint,
        )
        manifest.write_text(
            json.dumps(
                {
                    "identity": identity,
                    "sha256": digest(output),
                    "audio_sha256": digest(audio),
                    "created": time.time(),
                }
            )
        )
    progress("Checking the actual picture, captions and original speech", 0.78)
    checkpoint()
    report = verify(output, audio, props, work, store.settings(), checkpoint)
    report.update(
        render_reused=reusable,
        source_sha256=source_digest,
        output_sha256=digest(output),
        identity=identity,
        checked_at=time.time(),
        creative_approval=False,
    )
    old_report = clip.get("report", {})
    if (
        report["pass"]
        and old_report.get("creative_approval")
        and old_report.get("identity") == identity
        and old_report.get("output_sha256") == report["output_sha256"]
    ):
        report["creative_approval"] = True
    (work / "report.json").write_text(json.dumps(report, indent=2))

    def save(p):
        current = next(c for c in p["clips"] if c["id"] == clip_id)
        current.update(
            status=("ready" if report["creative_approval"] else "checked")
            if report["pass"]
            else "needs_review",
            report=report,
            render_directory=str(work.relative_to(directory)),
            rendered_start=start,
            rendered_end=end,
        )

    checkpoint()
    store.change(project_id, save)
    progress(
        "Export checks passed; ready for your review" if report["pass"] else "Export needs your attention", 1
    )
    return report
