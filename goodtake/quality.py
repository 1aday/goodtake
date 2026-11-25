"""Checks on encoded files. Missing checks are explicit and never count as a pass."""

from __future__ import annotations

import json
import math
import re
import shutil
from difflib import SequenceMatcher
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageDraw, ImageStat

from .models import caption_groups
from .process import Cancelled, run


def tokens(text):
    return re.findall(r"[\w]+", text.casefold().replace("'", "").replace("’", ""))


def similarity(a, b):
    return SequenceMatcher(None, "".join(tokens(a)), "".join(tokens(b))).ratio()


def title_readability(expected, read):
    expected_clean = re.sub(r"(?<=\d),(?=\d)", "", expected)
    read_clean = re.sub(r"(?<=\d),(?=\d)", "", read)
    expected_words, heard = tokens(expected_clean), tokens(read_clean)
    if "ai" in expected_words:
        heard = ["ai" if word in {"al", "a1"} else word for word in heard]
    match = SequenceMatcher(None, "".join(expected_words), "".join(heard)).ratio()
    coverage = sum(
        any(SequenceMatcher(None, word, got).ratio() >= 0.75 for got in heard) for word in expected_words
    ) / max(1, len(expected_words))
    numbers_match = re.findall(r"\d+(?:\.\d+)?", expected_clean) == re.findall(r"\d+(?:\.\d+)?", read_clean)
    return {
        "match": round(match, 4),
        "word_coverage": round(coverage, 4),
        "numbers_match": numbers_match,
        "expected": expected,
        "read": read,
        "pass": bool(expected_words) and match >= 0.9 and coverage >= 0.88 and numbers_match,
    }


def ocr(image, output, name="ocr", psm=6):
    if not shutil.which("tesseract"):
        raise ValueError("Install Tesseract to verify rendered titles and captions.")
    path = Path(output) / f"{name}.png"
    image.save(path)
    return run(["tesseract", path, "stdout", "--psm", psm, "-l", "eng"])


def title_check(image_path, props, output):
    image = Image.open(image_path).convert("RGB")
    x, y, w, h = props["layout"]["title"]
    crop = image.crop((x, y, x + w, y + h))
    reports = [title_readability(props["title"], ocr(crop, output, "title", 6))]
    if not reports[0]["pass"]:
        reports.append(title_readability(props["title"], ocr(crop, output, "title-sparse", 11)))
    best = max(reports, key=lambda report: (report["pass"], report["match"]))
    if not best["pass"]:
        raise ValueError("The encoded headline is not fully readable. Shorten it or try another template.")
    return best


def audio_integrity(video, audio):
    def packets(path):
        data = json.loads(
            run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_packets",
                    "-show_data_hash",
                    "sha256",
                    "-show_entries",
                    "packet=data_hash,pts_time,duration_time",
                    "-of",
                    "json",
                    path,
                ]
            )
        )
        return data["packets"]

    original, exported = packets(audio), packets(video)
    if not original or [p["data_hash"] for p in original] != [p["data_hash"] for p in exported]:
        raise ValueError("The exported audio differs from the prepared original-voice track.")
    timestamps = [float(p["pts_time"]) for p in exported]
    if any(not 0 < b - a < 0.08 for a, b in pairwise(timestamps)):
        raise ValueError("The exported audio has a timestamp gap or discontinuity.")
    return {
        "unchanged_prepared_audio_packets": True,
        "packet_count": len(original),
        "continuous_timestamps": True,
    }


def speech_check(video, props, output, settings, checkpoint=lambda: None):
    from .providers import local_model

    wav = Path(output) / "speech-check.wav"
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            video,
            "-t",
            props["duration"],
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            wav,
        ],
        checkpoint=checkpoint,
    )
    model = local_model(settings.whisper_model)

    def transcribe(path):
        segments, _ = model.transcribe(
            str(path),
            language=settings.language,
            beam_size=5,
            condition_on_previous_text=False,
            vad_filter=True,
        )
        result = []
        for segment in segments:
            checkpoint()
            result.append(segment.text)
        return " ".join(result)

    text = transcribe(wav)
    expected = tokens(" ".join(w["text"] for w in props["words"]))
    heard = tokens(text)
    if len(expected) < 4 or len(heard) < 4:
        raise ValueError("The exported speech could not be verified.")
    match = SequenceMatcher(None, expected, heard).ratio()

    def edge(a, b):
        return sum(block.size for block in SequenceMatcher(None, a, b).get_matching_blocks()) / len(a)

    opening, ending = edge(expected[:14], heard[:22]), edge(expected[-14:], heard[-22:])
    focused = []
    if match >= 0.8 and (opening < 0.7 or ending < 0.7):
        for name, score, start in [
            ("opening", opening, 0),
            ("ending", ending, max(0, props["duration"] - 18)),
        ]:
            if score >= 0.7:
                continue
            sample = Path(output) / f"speech-{name}.wav"
            run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-ss",
                    start,
                    "-i",
                    video,
                    "-t",
                    min(18, props["duration"]),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    sample,
                ],
                checkpoint=checkpoint,
            )
            got = tokens(transcribe(sample))
            improved = edge(expected[:14], got[:22]) if name == "opening" else edge(expected[-14:], got[-22:])
            focused.append({"edge": name, "match": round(improved, 4)})
            if name == "opening":
                opening = max(opening, improved)
            else:
                ending = max(ending, improved)
            sample.unlink(missing_ok=True)
    wav.unlink(missing_ok=True)
    if match < 0.8 or opening < 0.7 or ending < 0.7:
        raise ValueError(
            f"Export speech differs from the selected transcript: {match:.0%} overall, "
            f"{opening:.0%} opening, {ending:.0%} ending. Review transcript and boundaries."
        )
    return {
        "speech_match": round(match, 4),
        "opening_match": round(opening, 4),
        "ending_match": round(ending, 4),
        "focused_checks": focused,
        "method": "Independent local recognition of the encoded export",
    }


def verify(video, audio, props, output, settings, checkpoint=lambda: None):
    output = Path(output)
    checks = []

    def check(name, label, function):
        checkpoint()
        try:
            details = function()
            checks.append({"id": name, "label": label, "status": "pass", "details": details})
        except Cancelled:
            raise
        except (ValueError, RuntimeError, OSError, TimeoutError, ImportError) as error:
            checks.append({"id": name, "label": label, "status": "fail", "message": str(error)[:600]})

    def media_check():
        data = json.loads(
            run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", video])
        )
        stream = next(s for s in data["streams"] if s["codec_type"] == "video")
        expected = props["duration"] + (2.4 if props["brand"]["end_card"] else 0)
        expected_height = 1920 if props["style"]["ratio"] == "9:16" else 1350
        actual = float(data["format"]["duration"])
        if stream["width"] != 1080 or stream["height"] != expected_height or abs(actual - expected) > 0.12:
            raise ValueError("The export dimensions or duration do not match the selected composition.")
        return {"width": 1080, "height": expected_height, "duration": actual, "fps": stream["avg_frame_rate"]}

    check("media", "Dimensions and continuous duration", media_check)
    check("audio", "Original-voice audio and timestamps", lambda: audio_integrity(video, audio))

    def loudness():
        text = run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                video,
                "-af",
                "loudnorm=I=-16:TP=-2:LRA=9:print_format=json",
                "-f",
                "null",
                "-",
            ],
            checkpoint=checkpoint,
        )
        result = json.loads(re.findall(r'\{[^{}]*"input_i"[^{}]*\}', text, re.S)[-1])
        integrated, peak = float(result["input_i"]), float(result["input_tp"])
        if not math.isfinite(integrated) or not -21 <= integrated <= -11 or peak > -0.8:
            raise ValueError(f"Export loudness needs review: {integrated} LUFS, {peak} dBTP.")
        return {"integrated_lufs": integrated, "true_peak_dbtp": peak}

    check("loudness", "Comfortable loudness and safe peaks", loudness)
    frames = []

    def frame(time, name):
        path = output / f"{name}.jpg"
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                max(0, time),
                "-i",
                video,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                path,
            ],
            checkpoint=checkpoint,
        )
        image = Image.open(path).convert("RGB")
        frames.append((image, time))
        return image

    opening = frame(0, "cover")
    check(
        "title",
        "Headline readable in the encoded video",
        lambda: title_check(output / "cover.jpg", props, output),
    )

    def captions():
        groups = [g for g in caption_groups(props["words"]) if g[-1]["end"] - g[0]["start"] > 0.15]
        if not props["style"]["captions"]:
            return {"enabled": False, "note": "Captions disabled by the creator."}
        if not groups:
            raise ValueError("No caption groups could be verified.")
        count = min(10, len(groups))
        chosen = sorted(set(round(i * (len(groups) - 1) / max(1, count - 1)) for i in range(count)))
        samples = []
        for index in chosen:
            group = groups[index]
            time = group[0]["start"] + (group[-1]["end"] - group[0]["start"]) * 0.6
            image = frame(time, f"caption-{index}")
            x, y, width, height = props["layout"]["captions"]
            read = ocr(image.crop((x, y, x + width, y + height)), output, f"read-{index}")
            expected = " ".join(word["text"] for word in group)
            match = similarity(expected, read)
            samples.append(
                {"time": round(time, 3), "expected": expected, "read": read.strip(), "match": round(match, 3)}
            )
            vx, vy, vw, vh = props["layout"]["video"]
            if max(ImageStat.Stat(image.crop((vx, vy, vx + vw, vy + vh))).stddev) < 5:
                raise ValueError("A sampled source picture is blank or missing.")
        if sum(s["match"] < 0.58 for s in samples) > max(1, len(samples) // 4):
            raise ValueError("Sampled captions are missing, mistimed or unreadable in the encoded video.")
        return {"samples": samples, "method": "OCR of sampled encoded frames", "enabled": True}

    check("captions", "Caption timing, legibility and picture", captions)

    def brand_check():
        image = opening
        x, y, w, h = props["layout"]["header"]
        read = ocr(image.crop((x, y, x + w, y + h)), output, "show-brand")
        if similarity(props["brand"]["show"], read.replace("EXCERPT", "").replace("01 /", "")) < 0.72:
            raise ValueError("The show name is not readable in the first encoded frame.")
        if props["brand"]["end_card"]:
            end = frame(props["duration"] + 2, "endcard")
            end_text = ocr(end, output, "endcard-text")
            if not all(word in tokens(end_text) for word in tokens(props["brand"]["show"])):
                # Mixed display/body sizes can confuse block segmentation. Re-read the same encoded
                # frame in sparse-text mode; the required show words and acceptance rule are unchanged.
                end_text = ocr(end, output, "endcard-sparse", 11)
                if not all(word in tokens(end_text) for word in tokens(props["brand"]["show"])):
                    raise ValueError("The show name is missing from the encoded end card.")
        return {"show": props["brand"]["show"], "end_card": props["brand"]["end_card"]}

    check("brand", "Show identity and end card", brand_check)
    check(
        "speech",
        "Exported speech matches the selected words",
        lambda: speech_check(video, props, output, settings, checkpoint),
    )
    sheet = Image.new("RGB", (1080, math.ceil(len(frames) / 4) * 520), "#F1EEE6")
    draw = ImageDraw.Draw(sheet)
    for index, (image, time) in enumerate(frames):
        thumbnail = image.copy()
        thumbnail.thumbnail((258, 474))
        x, y = (index % 4) * 270 + 6, (index // 4) * 520 + 8
        sheet.paste(thumbnail, (x, y))
        draw.text((x + 5, y + 482), f"{time:.2f}s", fill="#20261E")
    sheet.save(output / "contact-sheet.jpg", quality=90)
    return {
        "pass": all(c["status"] == "pass" for c in checks),
        "checks": checks,
        "scope": "Technical checks and sampled frames; creative judgment remains yours.",
    }
