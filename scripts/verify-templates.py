"""Render real template exports into an isolated data directory and write a portable verification record.

This is an integration check, not a comparison or a render-speed benchmark.
"""

import argparse
import json
import shutil
import time
from pathlib import Path

from goodtake.models import ClipInput
from goodtake.render import render_clip
from goodtake.sample import load_sample
from goodtake.store import Store, new_id

parser = argparse.ArgumentParser()
parser.add_argument("--home", type=Path, default=Path("work/template-verification"))
parser.add_argument("--assets", type=Path, default=Path("docs/assets"))
parser.add_argument("--template", choices=["editorial", "paper", "focus"])
parser.add_argument("--ratio", choices=["9:16", "4:5"], default="9:16")
args = parser.parse_args()
store = Store(args.home)
project = load_sample(store)
combinations = (
    [(args.template, args.ratio)]
    if args.template
    else [("editorial", "9:16"), ("paper", "9:16"), ("focus", "9:16"), ("editorial", "4:5")]
)
results = []
for template, ratio in combinations:
    key = f"{template}-{ratio.replace(':', 'x')}"
    project = store.get(project["id"])
    existing = next((c for c in project["clips"] if c.get("verification_key") == key), None)
    if not existing:
        clip = ClipInput.model_validate(
            {
                key: project["clips"][0][key]
                for key in ["title", "start", "end", "takeaway", "reason", "post", "style"]
            }
        )
        clip.style.template, clip.style.ratio = template, ratio
        if template == "paper":
            # Every template uses the same show identity. A dark blue accent also exercises dark-on-paper OCR.
            store.change(project["id"], lambda p: p["brand"].update(accent="#4265A4"))
        else:
            store.change(project["id"], lambda p: p["brand"].update(accent="#F36B45"))
        clip_id = new_id()
        store.change(
            project["id"],
            lambda p, clip_id=clip_id, clip=clip, key=key: p["clips"].append(
                {**clip.model_dump(), "id": clip_id, "status": "draft", "verification_key": key}
            ),
        )
    else:
        clip_id = existing["id"]
    print(f"Rendering {key}", flush=True)
    started = time.monotonic()
    previous_stage = [None]

    def progress(stage, value=0, previous_stage=previous_stage, **detail):
        if stage != previous_stage[0]:
            print(stage, flush=True)
            previous_stage[0] = stage

    report = render_clip(store, project["id"], clip_id, progress=progress)
    current = next(c for c in store.get(project["id"])["clips"] if c["id"] == clip_id)
    work = store.directory(project["id"]) / current["render_directory"]
    results.append(
        {
            "template": template,
            "ratio": ratio,
            "pass": report["pass"],
            "checks": [
                {"id": c["id"], "status": c["status"], "message": c.get("message")} for c in report["checks"]
            ],
            "output_sha256": report["output_sha256"],
            "render_reused": report["render_reused"],
            "elapsed_seconds": round(time.monotonic() - started, 2),
        }
    )
    if not report["pass"]:
        print(json.dumps(results[-1], indent=2))
        raise SystemExit(f"{key} failed. Inspect {work / 'report.json'}; no thresholds were changed.")
    args.assets.mkdir(exist_ok=True, parents=True)
    for source, suffix in [("clip.mp4", ".mp4"), ("cover.jpg", ".jpg"), ("contact-sheet.jpg", "-frames.jpg")]:
        shutil.copy2(work / source, args.assets / (key + suffix))
record = {
    "sample": "Original generated artwork and synthetic narration; not a real podcast benchmark",
    "results": results,
}
path = args.assets.parent / (f"verification-{args.template or 'templates'}.json")
path.write_text(json.dumps(record, indent=2))
print(json.dumps(record, indent=2))
