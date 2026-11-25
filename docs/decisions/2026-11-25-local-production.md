# Local production with a separate rendering adapter

Status: implemented for v0.1.

The private system coupled a podcast-specific app, hosted queue/storage and an established video
composition. Publishing that deployment would force unrelated channel/infrastructure choices on users.

Goodtake extracts the editorial principles, caption grouping, final-file checks and content-bound
recovery into a local Python application. The packaged browser interface and CLI share SQLite and
the production code. There is no required hosted database or frontend build step.

Remotion stays behind a Node adapter for frame-driven typography. It renders silent picture; FFmpeg
muxes a separately prepared continuous original-voice track. Final checks compare audio packets and
independently recognize the exported speech. The dependency retains its separate license terms.

Show identity, branding, layout, ratio, crop, captions and end cards are data. API-provided geometry
drives preview and OCR regions. SQLite serializes project changes/job claims. Heartbeats renew leases;
expired attempts become interrupted. Cancellation stops subprocess trees and preserves completed clips.

OpenAI selection/review and ElevenLabs transcription are explicit choices. Local Whisper, manual
selection and imported transcripts support local use after dependencies/models are installed. This
release does not claim local-LLM selection, automatic face tracking or public guest hosting.
