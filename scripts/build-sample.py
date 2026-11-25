"""Rebuild the original demo from a narration WAV and project artwork; no provider calls.

Usage: python scripts/build-sample.py /path/to/narration.wav
Requires the project's [local] extra, FFmpeg, and an existing docs/assets/project-hero.png.
"""

import json
import sys
from pathlib import Path

from goodtake.process import run
from goodtake.providers import local_model

root = Path(__file__).resolve().parents[1]
sample = root / "goodtake/sample"
sample.mkdir(exist_ok=True)
audio = Path(sys.argv[1]).resolve()
run(
    [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-loop",
        "1",
        "-framerate",
        "30",
        "-i",
        root / "docs/assets/project-hero.png",
        "-i",
        audio,
        "-filter_complex",
        "[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720[bg];"
        "[1:a]asplit=2[a][wave];[wave]showwaves=s=1000x84:mode=cline:colors=0xF36B45:r=30,"
        "format=rgba,colorkey=0x000000:0.1:0.1[w];[bg][w]overlay=140:600:shortest=1[v]",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        sample / "conversation.mp4",
    ],
    timeout=300,
)
segments, _ = local_model("base.en").transcribe(
    str(audio), language="en", word_timestamps=True, condition_on_previous_text=False
)
words = [
    {"text": w.word.strip(), "start": w.start, "end": w.end, "speaker": "0"}
    for segment in segments
    for w in segment.words
    if w.word.strip() and w.end > w.start
]
(sample / "words.json").write_text(json.dumps({"words": words}, indent=2))
print(json.dumps({"source": str(sample / "conversation.mp4"), "words": len(words)}))
