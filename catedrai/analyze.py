from __future__ import annotations

import base64
from datetime import date
from pathlib import Path
from typing import List, Literal

import anthropic
from pydantic import BaseModel

from .config import ANTHROPIC_MODEL


class KeyTerm(BaseModel):
    term: str
    definition: str


class ExtractedEvent(BaseModel):
    type: Literal["homework", "test", "deadline", "event"]
    title: str
    date: str  # ISO 8601 date (YYYY-MM-DD) or datetime; "" if it can't be determined
    description: str


class ClassAnalysis(BaseModel):
    title: str
    summary: str
    bullet_notes: List[str]
    key_terms: List[KeyTerm]
    events: List[ExtractedEvent]


SYSTEM_PROMPT = """You are Catedrai, an assistant that turns a raw class transcript (and \
optional slide screenshots) into what a student actually needs: a summary, study notes, \
key term definitions, and any homework, tests, or deadlines that were mentioned. Ignore \
filler, small talk, and administrative rambling - focus only on content that helps the \
student learn and stay on top of deliverables. Resolve relative dates ("next Monday", \
"in two weeks", "before the end of the month") into absolute ISO 8601 dates (YYYY-MM-DD) \
using the class date given in the message as the reference point. If a date truly cannot \
be determined, leave it as an empty string rather than guessing."""


def _screenshot_content_blocks(screenshot_paths: List[Path], limit: int = 12) -> list[dict]:
    blocks = []
    for path in screenshot_paths[:limit]:
        data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
        blocks.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": data},
            }
        )
    return blocks


def analyze_session(
    transcript: str, screenshot_paths: List[Path], session_date: date
) -> ClassAnalysis:
    client = anthropic.Anthropic()

    content = _screenshot_content_blocks(screenshot_paths)
    content.append(
        {
            "type": "text",
            "text": (
                f"Class date: {session_date.isoformat()}\n\n"
                f"Transcript:\n{transcript}\n\n"
                "The screenshots above (if any) were captured periodically during class - "
                "use them for extra context on terms, diagrams, or written deadlines the "
                "transcript alone might miss."
            ),
        }
    )

    response = client.messages.parse(
        model=ANTHROPIC_MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_format=ClassAnalysis,
    )
    return response.parsed_output
