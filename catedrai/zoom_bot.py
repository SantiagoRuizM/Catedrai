from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import win32api
import win32con
import win32gui
import win32process
from pywinauto import Desktop

from .zoom_link import ZoomMeeting, build_join_uri

# Zoom's own executables. Matching on the owning process (not window class or
# title) is what's actually robust: the client uses different window classes
# for different screens (ZPPTMainFrmWndClassEx for the home screen,
# ZPFloatVideoWndClass for the floating thumbnail, ConfMultiTabContentWndClass
# for the real in-meeting window - confirmed live, and there may be others we
# haven't seen yet), and a title-substring match can accidentally hit an
# unrelated window (a browser tab, a terminal) that merely mentions "Zoom".
ZOOM_PROCESS_NAMES = {"zoom.exe", "cpthost.exe"}


def _process_name(pid: int) -> str:
    try:
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            return win32process.GetModuleFileNameEx(handle, 0).rsplit("\\", 1)[-1].lower()
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return ""

# Candidate texts for buttons we need to click, across locales/versions we've
# seen so far. Extend these tuples as new Zoom builds show different text.
JOIN_BUTTON_TEXTS = ("Entrar", "Join", "Unirse")
COMPUTER_AUDIO_TEXTS = (
    "Unirse con audio de la computadora",
    "Join with Computer Audio",
    "Join Audio",
)


@dataclass
class ZoomWindowHandle:
    window: object  # pywinauto UIAWrapper


def _dump_tree(element, depth: int, max_depth: int) -> None:
    indent = "  " * depth
    try:
        text = element.window_text()
        ctrl_type = element.element_info.control_type
        auto_id = element.element_info.automation_id
    except Exception as exc:
        print(f"{indent}(error reading element: {exc})")
        return
    print(f"{indent}[{ctrl_type}] text={text!r} auto_id={auto_id!r}")
    if depth >= max_depth:
        return
    try:
        children = element.children()
    except Exception:
        return
    for child in children:
        _dump_tree(child, depth + 1, max_depth)


def _is_zoom_window(w) -> bool:
    try:
        return _process_name(w.element_info.process_id) in ZOOM_PROCESS_NAMES
    except Exception:
        return False


def dump_zoom_windows(max_depth: int = 4) -> None:
    """Debug helper: prints every real Zoom process window, plus its control
    tree, so we can read off real button names/automation ids while
    iterating against a live meeting."""
    windows = Desktop(backend="uia").windows()
    zoom_windows = [w for w in windows if _is_zoom_window(w)]
    if not zoom_windows:
        print("No Zoom process window was found.")
        return
    for w in zoom_windows:
        print("=" * 80)
        print(f"TITLE: {w.window_text()!r}  class={w.element_info.class_name}")
        try:
            _dump_tree(w, 0, max_depth)
        except Exception as exc:
            print(f"  (could not dump control tree: {exc})")


# The confirmed real in-meeting window class (as opposed to the home screen,
# a floating video thumbnail, or a transient notification popup - several of
# which can legitimately coexist with the meeting window, e.g. if Zoom was
# already open in the background before joining).
IN_MEETING_CLASS_HINT = "conf"


def _find_zoom_window(timeout: float = 45.0, poll: float = 1.0, exclude_titles=()):
    deadline = time.time() + timeout
    while time.time() < deadline:
        candidates = [
            w
            for w in Desktop(backend="uia").windows()
            if _is_zoom_window(w) and w.window_text() not in exclude_titles
        ]
        if candidates:
            in_meeting = [
                w for w in candidates if IN_MEETING_CLASS_HINT in w.element_info.class_name.lower()
            ]
            return (in_meeting or candidates)[0]
        time.sleep(poll)
    raise TimeoutError("No Zoom window appeared within the timeout.")


def _find_button(window, substrings, timeout: float = 5.0, poll: float = 0.5):
    """Finds a Button descendant whose text contains any of `substrings`
    (case-insensitive). Zoom's buttons carry full accessible descriptions
    (e.g. "Abandonar, Alt+Q", not just "Abandonar"), and the UIAWrapper
    returned by Desktop().windows() only supports exact-match `title` in its
    underlying descendants() condition (confirmed live - title_re raises
    TypeError, and child_window()/.wait() aren't available on this wrapper
    type at all) - so filtering happens here in Python instead."""
    needles = [s.lower() for s in substrings]
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            buttons = window.descendants(control_type="Button")
        except Exception:
            buttons = []
        for btn in buttons:
            text = btn.window_text().lower()
            if any(n in text for n in needles):
                return btn
        time.sleep(poll)
    return None


def _click_first_match(window, texts, timeout: float = 5.0) -> bool:
    btn = _find_button(window, texts, timeout=timeout)
    if btn is None:
        return False
    try:
        btn.click_input()
        return True
    except Exception:
        return False


def launch_and_join(
    meeting: ZoomMeeting,
    display_name: str,
    pre_launch_titles: tuple[str, ...] = (),
    join_timeout: float = 45.0,
) -> ZoomWindowHandle:
    """Launches the Zoom desktop client straight into the meeting via the
    zoommtg:// deep link, then clicks through the name-entry and
    computer-audio prompts if they appear. Returns the meeting window handle
    so the caller can poll it to detect when the meeting ends."""
    uri = build_join_uri(meeting, display_name)
    os.startfile(uri)

    window = _find_zoom_window(timeout=join_timeout, exclude_titles=pre_launch_titles)

    _click_first_match(window, JOIN_BUTTON_TEXTS, timeout=10.0)
    time.sleep(2.0)
    # Re-fetch: the name-entry window usually closes and a new meeting
    # window (with the class/topic title) takes its place.
    try:
        window = _find_zoom_window(timeout=join_timeout, exclude_titles=pre_launch_titles)
    except TimeoutError:
        pass

    _click_first_match(window, COMPUTER_AUDIO_TEXTS, timeout=8.0)

    return ZoomWindowHandle(window=window)


_TOPIC_LIKE = re.compile(r"\(.+\)\s*$")


def get_meeting_topic(handle: ZoomWindowHandle, fallback: str = "") -> str:
    """Best-effort extraction of the meeting topic - e.g.
    "2554208-1 LOGICA Y REPRESENTACION I (2026-2)". Falls back to `fallback`
    if nothing usable is found; storage.resolve_course() degrades gracefully
    on an unparseable topic, so this never needs to be exact.

    Checks the window's own title first (confirmed live: the in-meeting
    window's title *is* the topic, e.g. "Zoom Reunion 40 minutos" for an
    ad-hoc meeting), then descendant Text controls as a fallback source -
    those turned out to mostly hold small UI badges (a "2" participant
    counter, in one live test), so short candidates are deprioritized."""
    candidates = []
    try:
        own_text = handle.window.window_text().strip()
        if own_text:
            candidates.append(own_text)
    except Exception:
        pass
    try:
        for t in handle.window.descendants(control_type="Text"):
            text = t.window_text().strip()
            if text:
                candidates.append(text)
    except Exception:
        pass

    if not candidates:
        return fallback

    topic_like = [c for c in candidates if _TOPIC_LIKE.search(c)]
    if topic_like:
        return max(topic_like, key=len)
    substantial = [c for c in candidates if len(c) > 3]
    return max(substantial or candidates, key=len)


def is_meeting_active(handle: ZoomWindowHandle) -> bool:
    """True as long as the meeting window's HWND still exists - regardless of
    whether it's currently visible/focused/minimized. The window closing (not
    merely being hidden) is the real "meeting ended" signal. Raw UIAWrapper
    objects from Desktop().windows() have no .exists()/.is_visible() (those
    belong to WindowSpecification) - .handle is the one thing both share, so
    we go straight to the Win32 API instead of the wrapper here."""
    try:
        return bool(win32gui.IsWindow(handle.window.handle))
    except Exception:
        return False


def wait_for_meeting_end(handle: ZoomWindowHandle, poll: float = 3.0) -> None:
    while is_meeting_active(handle):
        time.sleep(poll)
