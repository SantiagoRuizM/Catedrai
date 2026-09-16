"""Joins a Zoom meeting through the web client via Playwright, instead of the
desktop app. This replaces zoom_bot.py as the capture module's connection to
Zoom - same downstream contract (a handle you can check with
is_meeting_active(), get_meeting_topic() for course resolution), different
transport.

Why: the desktop client (zoom_bot.py) joins as whichever profile is already
logged into the machine - it can't join anonymously with a made-up name, so
every capture is attributed to the real account. The web client, run through
a fresh disposable browser context, joins as a plain guest with whatever
display name we give it - here, a random one from zoom_names.py each time,
so the bot shows up as an ordinary participant rather than a fixed,
obviously-automated identity.
"""

from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeoutError

from .capture import frame_changed
from .zoom_link import ZoomMeeting
from .zoom_names import random_display_name

JOIN_FROM_BROWSER_TEXTS = ("Unirse desde el navegador", "Join from your Browser", "Join from Browser")
NAME_SUBMIT_TEXTS = ("Entrar", "Join")
AUDIO_PROMPT_TEXTS = (
    "Unirse con audio de la computadora",
    "Join with Computer Audio",
    "Join Audio",
    "Unirse ahora",
    "Join Now",
)
IN_MEETING_MARKERS = ("Salir", "Leave", "Finalizar reunión", "End Meeting")
MEETING_ENDED_MARKERS = (
    "ha sido finalizada por el anfitrión",
    "This meeting has been ended",
    "Esta reunión ha finalizado",
    "You have left the meeting",
    "Ha salido de la reunión",
    "Meeting is locked",
)
_TOPIC_LIKE = re.compile(r"\(.+\)\s*$")


@dataclass
class ZoomBrowserHandle:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    display_name: str


def _landing_url(meeting: ZoomMeeting) -> str:
    """.../wc/join/<confno> is Zoom's web-client join URL - unlike
    .../j/<confno>, it skips the attempt to auto-launch the desktop app,
    which otherwise pops a native "Open Zoom Meetings?" browser dialog. That
    dialog lives outside the page DOM, so nothing here can see or dismiss it
    - it just sits there blocking the join flow until the timeout."""
    url = f"https://{meeting.domain}/wc/join/{meeting.confno}"
    if meeting.pwd:
        url += f"?pwd={meeting.pwd}"
    return url


def _try_click(page: Page, texts, timeout: float = 2000) -> bool:
    for text in texts:
        locator = page.get_by_text(text, exact=False).first
        try:
            if locator.count() == 0:
                continue
            locator.click(timeout=timeout)
            return True
        except (PWTimeoutError, Exception):
            continue
    return False


def _has_any_text(page: Page, texts) -> bool:
    for text in texts:
        try:
            if page.get_by_text(text, exact=False).count() > 0:
                return True
        except Exception:
            continue
    return False


def launch_and_join(
    meeting: ZoomMeeting,
    display_name: Optional[str] = None,
    headless: bool = False,
    join_timeout: float = 60.0,
) -> ZoomBrowserHandle:
    """Joins via the Zoom web client as a guest with a random display name
    (unless one is given). headless=False by default: audio/screenshot
    capture both rely on this actually rendering on screen (loopback audio
    needs the OS to actually play the meeting's audio somewhere, and
    screenshots capture screen pixels, not hidden window content) - the same
    visibility tradeoff as the desktop-app approach. The join flow isn't a
    fixed number of steps (a name-entry screen, an audio-preview screen, and
    the landing page can each independently appear or not) - so this polls
    and clicks through whatever's actually on screen until an in-meeting
    marker (a "Leave" button) shows up, instead of a fixed click sequence."""
    name = display_name or random_display_name()
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(
        headless=headless,
        args=["--autoplay-policy=no-user-gesture-required", "--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(permissions=["microphone", "camera"])
    page = context.new_page()
    page.goto(_landing_url(meeting), wait_until="domcontentloaded")

    deadline = time.time() + join_timeout
    try:
        while time.time() < deadline:
            if _has_any_text(page, IN_MEETING_MARKERS):
                return ZoomBrowserHandle(
                    playwright=playwright, browser=browser, context=context, page=page, display_name=name
                )

            if _try_click(page, JOIN_FROM_BROWSER_TEXTS):
                page.wait_for_timeout(1500)
                continue

            name_input = page.locator('input[type="text"]').first
            if name_input.count() > 0:
                try:
                    current_value = name_input.input_value(timeout=500)
                except Exception:
                    current_value = None  # not actionable yet - don't submit blind

                if current_value != name:
                    try:
                        name_input.click(timeout=1500)
                        name_input.fill(name, timeout=1500)
                        current_value = name_input.input_value(timeout=500)
                    except Exception:
                        current_value = None

                # Only submit once the field is confirmed to hold our name -
                # otherwise Zoom happily joins with a blank display name.
                if current_value == name and _try_click(page, NAME_SUBMIT_TEXTS):
                    page.wait_for_timeout(1500)
                    continue
                else:
                    page.wait_for_timeout(500)
                    continue

            if _try_click(page, AUDIO_PROMPT_TEXTS):
                page.wait_for_timeout(1500)
                continue

            page.wait_for_timeout(1000)
    except PWError as exc:
        # The page/context/browser died mid-flow (crash, or the target was
        # closed some other way) - surface this distinctly from a plain
        # timeout, since the cause is different and worth knowing.
        for step in (context.close, browser.close, playwright.stop):
            try:
                step()
            except Exception:
                pass
        raise TimeoutError(f"Browser closed unexpectedly while joining: {exc}") from exc

    for step in (context.close, browser.close, playwright.stop):
        try:
            step()
        except Exception:
            pass
    raise TimeoutError(f"Could not confirm joining the meeting within {join_timeout}s")


def get_meeting_topic(handle: ZoomBrowserHandle, fallback: str = "") -> str:
    """Best-effort topic extraction. The page <title> is often just a generic
    "Zoom Meeting" for the web client, so this falls back to scanning visible
    body text for a topic-like "<code> <name> (<term>)" fragment."""
    try:
        title = handle.page.title().strip()
    except Exception:
        title = ""
    if title and "zoom" not in title.lower():
        return title
    try:
        body_text = handle.page.inner_text("body")
    except Exception:
        return fallback
    for line in body_text.splitlines():
        line = line.strip()
        if _TOPIC_LIKE.search(line):
            return line
    return fallback


def is_meeting_active(handle: ZoomBrowserHandle) -> bool:
    try:
        if handle.page.is_closed():
            return False
        if _has_any_text(handle.page, MEETING_ENDED_MARKERS):
            return False
        return True
    except Exception:
        return False


def run_capture_loop(
    handle: ZoomBrowserHandle,
    screenshots_dir: Optional[Path],
    interval: float = 20.0,
    diff_threshold: float = 0.02,
    poll: float = 3.0,
) -> list[Path]:
    """Blocks until the meeting ends, taking a page screenshot every
    `interval` seconds (skipped entirely if screenshots_dir is None).

    Uses page.screenshot() (captures the page's rendered content via CDP -
    immune to focus, occlusion, and monitor layout) from the same thread
    that polls is_meeting_active(), since Playwright's sync API isn't
    thread-safe and this handle's Playwright objects are already owned by
    the calling thread."""
    if screenshots_dir:
        screenshots_dir.mkdir(parents=True, exist_ok=True)
    last_image = None
    saved: list[Path] = []
    next_shot = time.time()

    while is_meeting_active(handle):
        if screenshots_dir and time.time() >= next_shot:
            try:
                png_bytes = handle.page.screenshot(type="png")
                img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
                if frame_changed(last_image, img, diff_threshold):
                    ts = datetime.now().strftime("%H%M%S_%f")
                    path = screenshots_dir / f"{ts}.png"
                    img.save(path)
                    saved.append(path)
                    last_image = img
            except Exception:
                pass  # transient navigation/closed page/decode error - keep going
            next_shot = time.time() + interval
        sleep_for = min(poll, max(0.1, next_shot - time.time())) if screenshots_dir else poll
        time.sleep(sleep_for)

    return saved


def close(handle: ZoomBrowserHandle) -> None:
    for step in (handle.context.close, handle.browser.close, handle.playwright.stop):
        try:
            step()
        except Exception:
            pass
