"""Validated, portable contracts shared by the API, CLI, editor and renderer."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Word(Contract):
    text: str = Field(min_length=1, max_length=160)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    speaker: str = "0"

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("A word must end after it starts.")
        return self


class Brand(Contract):
    show: str = Field(default="The conversation", min_length=1, max_length=60)
    guest: str = Field(default="Guest", min_length=1, max_length=60)
    role: str = Field(default="", max_length=90)
    accent: str = Field(default="#F36B45", pattern=r"^#[0-9a-fA-F]{6}$")
    end_card: bool = True


class Style(Contract):
    template: Literal["editorial", "paper", "focus"] = "editorial"
    ratio: Literal["9:16", "4:5"] = "9:16"
    framing: Literal["fit", "fill"] = "fit"
    focal_x: float = Field(default=0.5, ge=0, le=1)
    captions: bool = True


class ClipInput(Contract):
    title: str = Field(min_length=2, max_length=65)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    takeaway: str = Field(default="", max_length=140)
    reason: str = Field(default="Selected by you", max_length=400)
    post: str = Field(default="", max_length=3000)
    style: Style = Field(default_factory=Style)

    @model_validator(mode="after")
    def duration(self):
        if not 5 <= self.end - self.start <= 180:
            raise ValueError("Select one continuous 5–180 second excerpt.")
        if len(self.title.split()) > 10:
            raise ValueError("Keep the headline to ten words or fewer.")
        return self


class Settings(Contract):
    editor_model: str = Field(default="gpt-5.1", min_length=1, max_length=100)
    transcription: Literal["local", "elevenlabs"] = "local"
    language: str = Field(default="en", pattern=r"^[a-z]{2,3}$")
    whisper_model: str = Field(default="base.en", min_length=1, max_length=100)
    exclude_profanity: bool = False
    clips_per_episode: int = Field(default=3, ge=1, le=8)


def normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def caption_groups(words: list[dict]) -> list[list[dict]]:
    """Group by speaker, punctuation, pause and measured reading load, never arbitrary sentence chunks."""
    result, group = [], []
    for word in words:
        previous = group[-1] if group else None
        if group and (
            len(group) >= 3
            or len(" ".join(w["text"] for w in group)) + len(word["text"]) > 22
            or re.search(r'[.?!,]["”]?$', previous["text"])
            or word["start"] - previous["end"] > 0.3
            or word.get("speaker") != previous.get("speaker")
        ):
            result.append(group)
            group = []
        group.append(word)
    if group:
        result.append(group)
    return result
