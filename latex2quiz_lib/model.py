"""Shared immutable data structures and user-facing errors."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

class ConversionError(Exception):
    """A user-facing input or conversion error."""


@dataclass(frozen=True)
class Answer:
    latex: str
    correct: bool
    line: int


@dataclass(frozen=True)
class Question:
    number: int
    title: str
    stem: str
    kind: str  # "single" or "multiple"
    answers: Tuple[Answer, ...]
    feedback: Optional[str]
    points: Optional[float]
    line: int


@dataclass(frozen=True)
class WrittenSubquestion:
    number: int
    label: str
    context: str
    prompt: str
    stem: str
    feedback: Optional[str]
    points: Optional[float]
    line: int


@dataclass(frozen=True)
class WrittenSection:
    number: int
    title: str
    context: str
    subquestions: Tuple[WrittenSubquestion, ...]
    points: Optional[float]
    line: int


@dataclass(frozen=True)
class RenderRequest:
    key: str
    latex: str
    alt: str
    figure: bool = False  # natural-width figure for HTML output, not a full-width block


@dataclass(frozen=True)
class RenderedImage:
    path: Path
    alt: str
    width: int
    height: int


