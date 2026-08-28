from __future__ import annotations

from pathlib import Path

from .analyze import ClassAnalysis


def write_outputs(session_dir: Path, transcript: str, analysis: ClassAnalysis) -> Path:
    (session_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
    (session_dir / "events.json").write_text(
        analysis.model_dump_json(indent=2), encoding="utf-8"
    )

    lines = [f"# {analysis.title}", "", "## Summary", "", analysis.summary, ""]

    lines.append("## Key Points")
    lines.append("")
    lines.extend(f"- {bullet}" for bullet in analysis.bullet_notes)
    lines.append("")

    lines.append("## Key Terms")
    lines.append("")
    lines.extend(f"- **{term.term}**: {term.definition}" for term in analysis.key_terms)

    if analysis.events:
        lines.append("")
        lines.append("## Homework, Tests & Deadlines")
        lines.append("")
        for event in analysis.events:
            when = event.date or "date unknown"
            lines.append(f"- [{event.type}] **{event.title}** ({when}) - {event.description}")

    notes_path = session_dir / "notes.md"
    notes_path.write_text("\n".join(lines), encoding="utf-8")
    return notes_path
