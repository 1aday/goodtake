"""Ensure a wheel install retains the exact runtime assets and excludes development dependencies."""

import zipfile
from pathlib import Path

wheel = sorted(Path("dist").glob("*.whl"))[-1]
with zipfile.ZipFile(wheel) as archive:
    files = set(archive.namelist())
    required = {
        "goodtake/web/index.html",
        "goodtake/web/app.js",
        "goodtake/renderer/package-lock.json",
        "goodtake/renderer/render.mjs",
        "goodtake/renderer/src/Clip.tsx",
        "goodtake/sample/conversation.mp4",
        "goodtake/sample/words.json",
        "goodtake/web/fonts/geist.woff2",
    }
    missing = required - files
    if missing:
        raise SystemExit(f"Missing packaged assets: {missing}")
    if any("node_modules/" in name or "/.env" in name or "sqlite" in name for name in files):
        raise SystemExit("Wheel includes a dependency tree, local state or environment file.")
    print(f"Verified {wheel.name}: {len(files)} files, all runtime assets present.")
