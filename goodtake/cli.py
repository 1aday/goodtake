"""The same production workflow from a terminal, with JSON output for scripts."""

from __future__ import annotations

import argparse
import json
import sys
import time
import webbrowser
from pathlib import Path

from . import __version__
from .bundle import make_bundle
from .media import create_project, download, import_transcript
from .models import ClipInput
from .render import ensure_renderer
from .store import Store, new_id


def wait_for_job(store, project_id, kind, clip_id, progress):
    from .worker import Worker

    job = store.enqueue(project_id, kind, clip_id)
    worker = Worker(store, only_job=job["id"])
    worker.start()
    previous = None
    try:
        while True:
            current = store.job(job["id"])
            if current["stage"] != previous:
                progress(current["stage"], current["progress"])
                previous = current["stage"]
            if current["status"] not in {"queued", "running", "cancelling"}:
                if current["status"] != "completed":
                    raise RuntimeError(current["error"] or "Production stopped before finishing.")
                return current
            time.sleep(0.5)
    except KeyboardInterrupt:
        store.cancel(job["id"])
        raise
    finally:
        worker.close()


def main():
    parser = argparse.ArgumentParser(
        prog="goodtake", description="Complete moments. Expressive captions. Your machine."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--home", type=Path, help="Private local data directory")
    commands = parser.add_subparsers(dest="command", required=True)
    studio = commands.add_parser("studio", help="Open the local review app")
    studio.add_argument("--port", type=int, default=3210)
    studio.add_argument(
        "--host",
        choices=["127.0.0.1", "0.0.0.0"],
        default="127.0.0.1",
        help="Loopback by default; 0.0.0.0 is for the container's internal listener",
    )
    studio.add_argument("--no-open", action="store_true")
    commands.add_parser("doctor", help="Check installed tools and configured providers")
    commands.add_parser("setup", help="Install the isolated local renderer")
    demo = commands.add_parser("demo", help="Load the bundled synthetic sample, no API key needed")
    demo.add_argument("--render", action="store_true")
    commands.add_parser("projects", help="List project IDs")
    ingest = commands.add_parser("import", help="Import a local video or YouTube link")
    ingest.add_argument("source")
    ingest.add_argument("--transcript", type=Path)
    for name in ["transcribe", "analyze", "render", "bundle", "show", "approve"]:
        sub = commands.add_parser(name)
        sub.add_argument("project_id")
        if name == "render":
            sub.add_argument("--clip", help="Export one clip; otherwise export unfinished clips")
        if name == "approve":
            sub.add_argument("--clip", required=True, help="Clip you have watched and want in the guest kit")
    produce = commands.add_parser("produce", help="Import, transcribe, select and render a conversation")
    produce.add_argument("source")
    produce.add_argument("--transcript", type=Path)
    add = commands.add_parser("add", help="Add a continuous source moment by timestamps")
    add.add_argument("project_id")
    add.add_argument("--start", type=float, required=True)
    add.add_argument("--end", type=float, required=True)
    add.add_argument("--title", required=True)
    args = parser.parse_args()
    store = Store(args.home)

    def progress(stage, value=0):
        print(f"{value:.0%} {stage}", file=sys.stderr, flush=True)

    try:
        if args.command == "studio":
            import uvicorn

            from .server import create_app

            if not args.no_open:
                import threading

                threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
            uvicorn.run(create_app(store), host=args.host, port=args.port)
        elif args.command == "doctor":
            from .server import doctor

            print(json.dumps(doctor(store), indent=2))
        elif args.command == "setup":
            print(ensure_renderer(store, progress=progress))
        elif args.command == "demo":
            from .sample import load_sample

            project = load_sample(store)
            if args.render:
                wait_for_job(store, project["id"], "render", project["clips"][0]["id"], progress)
                report = store.get(project["id"])["clips"][0]["report"]
                print(json.dumps(report, indent=2))
                if not report["pass"]:
                    return 1
            print(
                json.dumps(
                    {
                        "project_id": project["id"],
                        "clip_id": project["clips"][0]["id"],
                        "sample": "Synthetic narration and original generated artwork",
                    }
                )
            )
        elif args.command == "import":
            project = (
                download(store, args.source)
                if args.source.startswith("https:")
                else create_project(store, Path(args.source))
            )
            if args.transcript:
                project = import_transcript(
                    store,
                    project["id"],
                    args.transcript.read_text(),
                    "srt" if args.transcript.suffix.lower() == ".srt" else "json",
                )
            print(json.dumps({"project_id": project["id"], "duration": project["duration"]}))
        elif args.command == "projects":
            print(
                json.dumps(
                    [{key: p[key] for key in ["id", "title", "duration"]} for p in store.projects()], indent=2
                )
            )
        elif args.command == "show":
            print(json.dumps(store.get(args.project_id), indent=2))
        elif args.command == "add":
            clip = ClipInput(title=args.title, start=args.start, end=args.end)
            project = store.get(args.project_id)
            if clip.end > project["duration"]:
                raise ValueError("The range extends beyond the source.")
            clip_id = new_id()
            store.change(
                args.project_id,
                lambda p: p["clips"].append(
                    {
                        **clip.model_dump(),
                        "id": clip_id,
                        "status": "draft",
                        "editorial": {"method": "Selected by you"},
                    }
                ),
            )
            print(json.dumps({"clip_id": clip_id}))
        elif args.command == "bundle":
            print(make_bundle(store, args.project_id))
        elif args.command == "approve":

            def approve(p):
                clip = next((c for c in p["clips"] if c["id"] == args.clip), None)
                if (
                    not clip
                    or clip["status"] not in {"checked", "ready"}
                    or not clip.get("report", {}).get("pass")
                ):
                    raise ValueError(
                        "Approve a clip only after all export checks pass and you have watched it."
                    )
                clip["status"] = "ready"
                clip["report"]["creative_approval"] = True

            store.change(args.project_id, approve)
            print(json.dumps({"approved": args.clip}))
        elif args.command == "produce":
            project = (
                download(store, args.source)
                if args.source.startswith("https:")
                else create_project(store, Path(args.source))
            )
            if args.transcript:
                import_transcript(
                    store,
                    project["id"],
                    args.transcript.read_text(),
                    "srt" if args.transcript.suffix.lower() == ".srt" else "json",
                )
            print(json.dumps({"project_id": project["id"]}), flush=True)
            wait_for_job(store, project["id"], "analyze", None, progress)
            wait_for_job(store, project["id"], "render", None, progress)
            print(
                json.dumps(
                    {"project_id": project["id"], "clips": store.get(project["id"])["clips"]}, indent=2
                )
            )
            if any(c["status"] == "needs_review" for c in store.get(project["id"])["clips"]):
                return 1
        else:
            result = wait_for_job(store, args.project_id, args.command, getattr(args, "clip", None), progress)
            if args.command == "render":
                result["exports"] = [
                    {
                        "clip_id": c["id"],
                        "status": c["status"],
                        "path": str(store.directory(args.project_id) / c["render_directory"] / "clip.mp4"),
                    }
                    for c in store.get(args.project_id)["clips"]
                    if c.get("render_directory")
                ]
                if any(c["status"] == "needs_review" for c in result["exports"]):
                    print(json.dumps(result, indent=2))
                    return 1
            print(json.dumps(result, indent=2))
    except KeyboardInterrupt:
        return 130
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        from .worker import safe_error

        print("Goodtake: " + safe_error(store, error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
