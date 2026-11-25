# Verification — November 25, 2026

This record distinguishes actual checks from proposed future work. The synthetic fixture is not a
real-podcast or competitor-quality benchmark.

## Media exports

The bundled 32-second source was rendered through Editorial, Paper and Focus in 1080 × 1920, plus
Editorial in 1080 × 1350. Every export passed all seven check families: dimensions/duration, prepared
audio packet identity/timestamps, loudness/peaks, encoded headline OCR, sampled captions/picture,
show/end-card identity, and independent local speech comparison. All have a separate 2.4-second end card.

The exact output hashes, per-check outcomes and observed elapsed times are in
[`verification-templates.json`](verification-templates.json). Those local sample timings include
verification and are not a general performance promise. Export files, covers and contact sheets
are under `docs/assets/`.

The first end-card OCR pass mis-segmented mixed type sizes. A sparse-text read of the same encoded
frame recovered the actual show words. Expected words and pass criteria were not reduced.

## Actual workflow checks

- Native Apple Silicon: source import, local Whisper transcription, manual editing, template/ratio
  changes, save, queued export, stop/retry, checks, approval and guest ZIP download.
- Browser: 1440px desktop and 390px mobile layouts; no horizontal overflow in the checked screens.
  The ZIP contained the approved video, cover, post copy and an offline gallery.
- A separate live OpenAI test used `gpt-5.1` for selection and excerpt-only review after local
  transcription. It saved a reviewed 27.34-second selection. Four actual provider responses were
  recorded, including retries; token usage stayed explicitly unpriced.
- A fresh Linux ARM64 Docker image built and booted without keys, loaded the packaged sample,
  served byte-range video, and completed a real checked sample export with local speech recognition.
- A built wheel was installed into a fresh virtual environment. Its CLI and bundled sample loaded;
  packaging inspection confirmed the web app, renderer source/lockfile, fonts and sample were present
  and no node_modules, SQLite state or environment file was included.

## Regression and build checks

The automated suite covers excerpt-local evidence, bounded reviewer repair, optional notes,
preserved approvals, persistence before provider failure, non-overlap, word padding, invalid times,
queue lease recovery, cancellation, key privacy, origin/host restrictions, stale approval invalidation,
asset allowlisting, source URL canonicalization, SRT provenance and guest bundle escaping/integrity.

Python tests, Ruff, renderer TypeScript, browser JavaScript syntax and Python package build were run.
The repository includes the real corresponding GitHub Actions commands; remote results must be
checked on GitHub rather than inferred from local success.

## Still unproven

No ten-episode blind comparison, retention uplift, virality claim, native Windows production test,
automatic speaker tracking or internet-facing multi-user deployment is asserted. The follow-up
comparison protocol is in [BENCHMARK-PLAN.md](BENCHMARK-PLAN.md).
