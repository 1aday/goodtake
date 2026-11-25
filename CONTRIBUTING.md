# Contributing

Goodtake is early. Help a new person finish a good clip before adding another settings screen.

1. Use Python 3.11+, Node.js 22+, FFmpeg/FFprobe and Tesseract.
2. Create a virtual environment and `pip install -e '.[local,youtube,dev]'`.
3. Run `npm ci --prefix goodtake/renderer`.
4. Run `python -m pytest`, `ruff check .`, and `npm run typecheck --prefix goodtake/renderer`.
5. For rendering changes, run `goodtake --home ./work demo --render` and inspect its encoded
   clip, full speech, contact sheet and check report. Use a separate data directory for experiments.

The frontend is packaged HTML/CSS/JavaScript, served by the same local Python process. It has no
frontend build step. Rendering runs through an isolated Node adapter. State lives in SQLite and
private files under `GOODTAKE_HOME`, outside the source tree by default.

Useful first contributions:

- An original template with its own 9:16 and 4:5 geometry, phone screenshot and encoded OCR checks.
- A failing source-boundary, caption or recovery case reduced to a nonprivate regression fixture.
- Native Windows/Linux installation evidence and clearer first-run diagnostics.
- Caption accessibility and language support, with real OCR and speech-check evidence.
- A model/provider adapter that preserves schema validation, source evidence and explicit usage.

Open an issue before large changes. Include OS, versions, the failing stage and a redacted report.
Do not attach private recordings, provider keys or complete diagnostic directories. Never weaken
checks to hide an unreadable frame, altered source claim or missing words. Explain alternative OCR
reads or recognizer repairs and keep their acceptance rule intact.

Use small commits with clear Conventional Commit subjects. Record material decisions under
`docs/decisions/`. Public descriptions should stand on their own and avoid unsupported superiority
or virality claims. Contributors retain credit for their work.
