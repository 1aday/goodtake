# Goodtake

Do not use subagents unless the user explicitly asks.

Python 3.11+ owns the local API, queue, selection and verification. The packaged Remotion renderer
owns frame-driven layouts. Keep the two interfaces JSON based. Never add cloud infrastructure as a
requirement for local production. All user media, keys and generated files belong under GOODTAKE_HOME.

Run `python -m pytest`, `ruff check .`, and the renderer type check after relevant changes. Exercise a
real sample export before changing rendering or final-file checks. A technically checked clip still
needs creative approval; never label missing or skipped checks as passed. Do not loosen thresholds
to make a sample pass. Keep regression cases for source evidence and approved selection preservation.

Do not copy private footage, guest metadata, credentials or deployment configuration from another
project into this repository. Document actual behavior and tested platforms. No invented benchmarks.
