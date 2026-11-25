# A file is not a finished clip

Goodtake separates source selection, encoded-file verification and creative approval.

## Editorial selection

The automatic editor proposes continuous source-word ranges of 25–180 seconds. Deterministic checks
validate indices, duration, overlap, title/copy constraints and optional profanity rules. A separate
reviewer sees only the selected excerpt and written copy. Blockers require words inside that numbered
excerpt and identify an incomplete opening/ending, missing payoff, misleading copy or duplicate idea.

Adjacent speech cannot invalidate an excerpt the reviewer did not receive. Hesitations, rhetorical
questions and pacing preferences are notes. The editor can move a continuous range or change written
copy; it cannot rewrite speech or remove interior phrases. Accepted choices retain their exact range
and copy across refinements and are saved before the next provider request can fail.

Manual choices are labelled as selected/edited by you. The sample is a prepared selection, not a
disguised automatic-editor result.

## Encoded-file verification

The actual first-frame headline is checked before full encoding. The final MP4 then receives:

1. Expected dimensions, aspect ratio and continuous excerpt/end-card duration.
2. Audio packet hashes identical to the prepared normalized original-voice AAC track and regular
   packet timestamps. This does not claim bit identity to the original source recording.
3. Measured integrated loudness and safe true peaks.
4. Complete encoded headline text, including unchanged numbers.
5. Up to ten sampled caption groups read with OCR, plus sampled nonblank source-picture checks.
6. Readable show identity at the opening and in the optional final end card.
7. Independent local recognition of exported speech against selected words, overall and at the edges.

An alternate OCR segmentation read or a focused speech-edge re-read can resolve recognizer ambiguity.
Expected words and thresholds stay unchanged. Missing dependencies and unreadable/mismatched words
are failures, never silently skipped passes. Reports and contact sheets stay with each export.

## Approval and recovery

- **Draft:** chosen or edited; no applicable final-file approval.
- **Checks passed:** the encoded artifact passed technical verification.
- **Approved:** you watched a checked clip and chose to include it in the guest kit.
- **Needs review:** a check failed; inspect its report and retry after repair.

Changes to a range, headline, layout, transcript or branding invalidate applicable checks. Failed
exports are available for local inspection but excluded from finished downloads and guest kits.

A checkpoint binds source SHA-256, selected words, exact composition props, renderer content/version,
and encoded/audio hashes. Matching retries reuse the file and repeat checks. An unchanged rechecked
artifact can retain its creative approval. Completed clips survive failures in later work.

Technically valid clips can still be boring or misleading in context. Human judgment remains
necessary; these checks do not promise virality or establish comparative performance.
