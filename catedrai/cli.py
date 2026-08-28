from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from . import storage
from .analyze import analyze_session
from .calendar_sync import get_calendar_service, sync_events
from .capture import AudioRecorder, ScreenshotCapturer, create_session
from .config import SESSIONS_DIR
from .output import write_outputs
from .transcribe import transcribe_audio
from .zoom_bot import (
    dump_zoom_windows,
    get_meeting_topic,
    is_meeting_active,
    launch_and_join,
    wait_for_meeting_end,
)
from .zoom_link import parse_zoom_link


def _run_pipeline(
    capture_dir: Path, output_dir: Path, session_date, use_calendar: bool, calendar_id: str
):
    """capture_dir holds audio.wav/screenshots/ (raw/ for the Zoom-bot flow,
    the session dir itself for the older live-capture flow). output_dir is
    where transcript.txt/notes.md/events.json get written - a sibling of
    raw/ for the Zoom-bot flow, same as capture_dir otherwise."""
    audio_path = capture_dir / "audio.wav"
    screenshots_dir = capture_dir / "screenshots"
    screenshot_paths = sorted(screenshots_dir.glob("*.png")) if screenshots_dir.exists() else []

    if not audio_path.exists():
        print(f"No audio.wav found in {capture_dir}", file=sys.stderr)
        sys.exit(1)

    print("Transcribing audio locally (faster-whisper)...")
    transcript = transcribe_audio(audio_path)

    print("Analyzing transcript with Claude...")
    analysis = analyze_session(transcript, screenshot_paths, session_date)

    notes_path = write_outputs(output_dir, transcript, analysis)
    print(f"Notes written to {notes_path}")

    if use_calendar:
        if analysis.events:
            print("Syncing extracted events to Google Calendar...")
            try:
                links = sync_events(analysis.events, calendar_id=calendar_id)
                print(f"Created {len(links)} calendar event(s).")
            except Exception as exc:
                print(f"Calendar sync failed: {exc}", file=sys.stderr)
        else:
            print("No homework, tests, or deadlines detected - nothing to sync.")

    return analysis


def cmd_class(args: argparse.Namespace) -> None:
    session = create_session(SESSIONS_DIR, args.name)
    print(f"Session '{session.name}' started at {session.dir}")
    capturing = "audio" if args.no_screenshots else "audio and screenshots"
    print(f"Capturing {capturing}. Press Ctrl+C when class ends to auto-generate notes.")

    recorder = AudioRecorder(session.audio_path)
    recorder.start()

    capturer = None
    if not args.no_screenshots:
        capturer = ScreenshotCapturer(session.screenshots_dir, interval=args.screenshot_interval)
        capturer.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping capture...")
    finally:
        recorder.stop()
        if capturer:
            capturer.stop()

    if recorder.error:
        print(f"Audio recording error: {recorder.error}", file=sys.stderr)
        sys.exit(1)
    if capturer and capturer.error:
        print(f"Screenshot capture error: {capturer.error}", file=sys.stderr)

    _run_pipeline(
        session.dir, session.dir, session.started_at.date(), not args.no_calendar, args.calendar_id
    )


def cmd_process(args: argparse.Namespace) -> None:
    session_dir = Path(args.session_dir).resolve()
    if not session_dir.exists():
        print(f"Session directory not found: {session_dir}", file=sys.stderr)
        sys.exit(1)
    session_date = datetime.fromtimestamp(session_dir.stat().st_ctime).date()
    _run_pipeline(session_dir, session_dir, session_date, not args.no_calendar, args.calendar_id)


def cmd_calendar_auth(_args: argparse.Namespace) -> None:
    get_calendar_service()
    print("Google Calendar authorization complete. Token saved.")


def cmd_zoom(args: argparse.Namespace) -> None:
    meeting = parse_zoom_link(args.link)
    started_at = datetime.now()
    print(f"Joining Zoom meeting {meeting.confno} on {meeting.domain} as '{args.display_name}'...")

    try:
        handle = launch_and_join(meeting, args.display_name)
    except TimeoutError as exc:
        print(f"Could not join the meeting: {exc}", file=sys.stderr)
        sys.exit(1)

    if not is_meeting_active(handle):
        print("Warning: no active Zoom meeting window was detected after joining.", file=sys.stderr)

    raw_topic = get_meeting_topic(handle, fallback=f"Zoom Meeting {meeting.confno}")
    course = storage.resolve_course(meeting.confno, raw_topic)
    raw_dir = storage.new_session_raw_dir(course, started_at)
    session_dir = raw_dir.parent
    print(f"Course: {course.course_id} ({course.name}, {course.semester}) -> {session_dir}")

    print("Capturing system audio" + ("" if args.no_screenshots else " and screenshots") + ".")
    print("Recording will stop automatically when the meeting ends (or Ctrl+C).")

    audio_path = raw_dir / "audio.wav"
    screenshots_dir = raw_dir / "screenshots"

    recorder = AudioRecorder(audio_path, source="loopback")
    recorder.start()

    capturer = None
    if not args.no_screenshots:
        capturer = ScreenshotCapturer(screenshots_dir, interval=args.screenshot_interval)
        capturer.start()

    try:
        wait_for_meeting_end(handle)
        print("\nMeeting ended - wrapping up...")
    except KeyboardInterrupt:
        print("\nInterrupted - stopping capture...")
    finally:
        recorder.stop()
        if capturer:
            capturer.stop()

    ended_at = datetime.now()
    storage.write_capture_meta(
        raw_dir,
        {
            "source": "zoom-bot",
            "confno": meeting.confno,
            "raw_topic": raw_topic,
            "started_at": started_at,
            "ended_at": ended_at,
            "files": {
                "audio": audio_path.name if audio_path.exists() else None,
                "screenshots": bool(capturer and capturer.saved),
            },
        },
    )

    if recorder.error:
        print(f"Audio recording error: {recorder.error}", file=sys.stderr)
        sys.exit(1)
    if capturer and capturer.error:
        print(f"Screenshot capture error: {capturer.error}", file=sys.stderr)

    _run_pipeline(raw_dir, session_dir, started_at.date(), not args.no_calendar, args.calendar_id)


def cmd_zoom_debug(_args: argparse.Namespace) -> None:
    dump_zoom_windows()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catedrai",
        description="Automate class capture, notes, term help, and homework/test tracking.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_class = sub.add_parser(
        "class", help="Record a live class and auto-generate notes + calendar events"
    )
    p_class.add_argument("--name", default=None, help="Session name (default: timestamp)")
    p_class.add_argument(
        "--screenshot-interval",
        type=float,
        default=20.0,
        help="Seconds between screenshot checks (default: 20)",
    )
    p_class.add_argument("--no-screenshots", action="store_true")
    p_class.add_argument("--no-calendar", action="store_true")
    p_class.add_argument("--calendar-id", default="primary")
    p_class.set_defaults(func=cmd_class)

    p_process = sub.add_parser(
        "process", help="Reprocess an already-captured session directory"
    )
    p_process.add_argument("session_dir")
    p_process.add_argument("--no-calendar", action="store_true")
    p_process.add_argument("--calendar-id", default="primary")
    p_process.set_defaults(func=cmd_process)

    p_auth = sub.add_parser("calendar-auth", help="Run the Google Calendar OAuth flow once")
    p_auth.set_defaults(func=cmd_calendar_auth)

    p_zoom = sub.add_parser(
        "zoom", help="Auto-join a Zoom meeting from its link and capture it end to end"
    )
    p_zoom.add_argument("link", help="Zoom join link, e.g. https://universidad.zoom.us/j/123456789")
    p_zoom.add_argument("--display-name", default="Catedrai", help="Name shown in the meeting")
    p_zoom.add_argument(
        "--screenshot-interval",
        type=float,
        default=20.0,
        help="Seconds between screenshot checks (default: 20)",
    )
    p_zoom.add_argument("--no-screenshots", action="store_true")
    p_zoom.add_argument("--no-calendar", action="store_true")
    p_zoom.add_argument("--calendar-id", default="primary")
    p_zoom.set_defaults(func=cmd_zoom)

    p_zoom_debug = sub.add_parser(
        "zoom-debug", help="Dump the control tree of any open Zoom windows (for troubleshooting)"
    )
    p_zoom_debug.set_defaults(func=cmd_zoom_debug)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
