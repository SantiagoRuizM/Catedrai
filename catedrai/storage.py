"""Storage layout for raw capture data: data/<semester>/<course_id>/<session_id>/raw/

This module owns the *collection*-side contract only: where a capture source
(live mic, Zoom local recording, Zoom bot) puts its raw files, and how a
session gets associated with a course/semester. It knows nothing about
transcription, analysis, or notes generation - later pipeline stages write
their outputs as siblings of raw/ inside the same session directory.

Course identity is registry-backed (data/courses.json), keyed by Zoom confno.
The registry is auto-seeded by parsing the Zoom meeting topic the first time
a confno is seen, and is otherwise the source of truth - so an inconsistently
typed topic in week 6 doesn't fragment a course's sessions across two folders.
Callers that want to correct a bad auto-parse just edit courses.json by hand.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import DATA_DIR

COURSES_REGISTRY_PATH = DATA_DIR / "courses.json"

# "2554208-1 LÓGICA Y REPRESENTACIÓN I (2026-2)" -> course_id, name, semester
_TOPIC_PATTERN = re.compile(r"^(?P<course_id>\S+)\s+(?P<name>.+?)\s*\((?P<semester>[^()]+)\)\s*$")

_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")


@dataclass
class CourseInfo:
    course_id: str
    name: str
    semester: str
    raw_topic: str


def _slugify(text: str) -> str:
    slug = _SLUG_INVALID_CHARS.sub("-", text.strip().lower()).strip("-")
    return slug or "unknown"


def _parse_topic(raw_topic: str) -> tuple[str, str, str]:
    """Best-effort parse of a Zoom topic into (course_id, name, semester).
    Falls back to a slugified course_id and semester="unknown" when the topic
    doesn't follow the "<code> <name> (<semester>)" convention - the registry
    entry is still created, just meant to be hand-corrected afterward."""
    match = _TOPIC_PATTERN.match(raw_topic.strip())
    if match:
        return match.group("course_id"), match.group("name").strip(), match.group("semester").strip()
    return _slugify(raw_topic), raw_topic.strip(), "unknown"


def _load_registry() -> dict:
    if not COURSES_REGISTRY_PATH.exists():
        return {}
    return json.loads(COURSES_REGISTRY_PATH.read_text(encoding="utf-8"))


def _save_registry(registry: dict) -> None:
    COURSES_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    COURSES_REGISTRY_PATH.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_course(confno: str, raw_topic: str) -> CourseInfo:
    """Looks up the course for a Zoom confno in the registry. On first sight
    of a confno, parses raw_topic to seed a new entry and persists it -
    subsequent calls with the same confno return the registry's (possibly
    hand-edited) entry regardless of what raw_topic says that day."""
    registry = _load_registry()
    entry = registry.get(confno)
    if entry is not None:
        return CourseInfo(**entry)

    course_id, name, semester = _parse_topic(raw_topic)
    course = CourseInfo(course_id=course_id, name=name, semester=semester, raw_topic=raw_topic)
    registry[confno] = asdict(course)
    _save_registry(registry)
    return course


def resolve_course_manual(course_id: str, name: str, semester: str, confno: Optional[str] = None) -> CourseInfo:
    """Registers/overwrites a course entry without going through topic
    parsing - for non-Zoom sources (live capture) or manual correction."""
    course = CourseInfo(course_id=course_id, name=name, semester=semester, raw_topic=name)
    if confno:
        registry = _load_registry()
        registry[confno] = asdict(course)
        _save_registry(registry)
    return course


def session_id_for(started_at: datetime) -> str:
    return started_at.strftime("%Y-%m-%d_%H-%M")


def new_session_raw_dir(course: CourseInfo, started_at: datetime) -> Path:
    """Creates and returns data/<semester>/<course_id>/<session_id>/raw/."""
    session_dir = DATA_DIR / course.semester / course.course_id / session_id_for(started_at)
    raw_dir = session_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir


def write_capture_meta(raw_dir: Path, meta: dict) -> Path:
    """Writes meta.json into a session's raw/ dir. `meta` is caller-defined
    (source, confno, timestamps, files present, etc.) - this just persists it
    next to the raw files it describes."""
    meta_path = raw_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return meta_path
