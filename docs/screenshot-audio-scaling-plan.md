# Screenshot fix + audio scaling — implementation plan

Written 2026-09-15 after a live test of `catedrai zoom` during an actual class
(link `https://udearroba.zoom.us/j/93948155904`, course `2554208-1`, semester
`2026-2`). Captured here so the next session doesn't need to re-derive it —
tokens ran out mid-session before implementing.

## State as of writing (uncommitted)

- `catedrai/zoom_playwright_bot.py` (new) — joins via `/wc/join/<confno>`
  (not `/j/<confno>` — that URL triggers a native "Open Zoom Meetings?"
  browser dialog outside the page DOM that the bot can't see or dismiss).
  Name-entry fill is verified (`input_value()` read back) before submitting,
  fixing an earlier bug where it clicked "Entrar" with a blank name field.
  **No longer has `PageScreenshotCapturer`** — see Option 1, that's the
  pending work.
- `catedrai/zoom_names.py` (new) — random Colombian-name generator for the
  guest display name.
- `catedrai/cli.py` — `cmd_zoom` currently uses `capture.ScreenshotCapturer`
  (OS-level `mss` grab of `sct.monitors[1]`, the primary monitor) as a
  stand-in fix, because the original `PageScreenshotCapturer` called
  `page.screenshot()` from a background thread, which crashes Playwright's
  sync API (`greenlet.error: cannot switch to a different thread`). This
  stand-in **is what Option 1 below replaces** — it captures the wrong thing
  when there are multiple monitors or the Zoom window isn't what's on top.
- `catedrai/capture.py` — refactored `frame_changed()` out to module level so
  both capturers could share it (still relevant either way).
- `requirements.txt` — added `playwright` (browsers already installed in
  `.venv` via `playwright install`, confirmed working).
- Live-tested end to end: join flow, audio loopback recording, and the mss
  screenshot stand-in all confirmed working during the actual class.
  **Nothing has been committed yet** — do that once Option 1 lands and is
  re-tested.

Known unrelated footgun from this session: killing a stray/duplicate
`python.exe` process by PID (`Stop-Process -Id ... -Force`) took down the
*other*, actively-recording `catedrai zoom` process with it — they appear to
share a job object under whatever supervises background processes here.
**Don't kill one of a pair of python.exe processes spawned by `catedrai
zoom` without expecting the other to die too.**

---

## Option 1 — screenshots should only be the Zoom tab's content

**Problem:** the current `capture.ScreenshotCapturer` grabs the whole primary
monitor (`sct.monitors[1]`). With two monitors, if Zoom isn't on monitor 1,
it captures the wrong screen entirely; even on the right monitor, switching
tabs/apps or having another window on top means the screenshot captures
whatever's on top, not the class content — and could capture unrelated
personal content on screen.

**Fix:** go back to Playwright's `page.screenshot()` (captures the page's
rendered content via CDP — immune to focus, occlusion, and monitor layout),
but *don't* call it from a background thread. Playwright's sync API is
documented as not thread-safe; calling it from a second thread while the
main thread also holds Playwright objects is exactly what crashed last time.

**Correct structure:** merge the screenshot cadence into the same main-thread
loop that already polls `is_meeting_active()` in `wait_for_meeting_end()` —
one thread, one Playwright user, no cross-thread calls.

Sketch (replaces `wait_for_meeting_end(handle)` call in `cmd_zoom`, and the
`ScreenshotCapturer`/`PageScreenshotCapturer` instantiation):

```python
# in zoom_playwright_bot.py — replaces wait_for_meeting_end, or add alongside it
def run_capture_loop(
    handle: ZoomBrowserHandle,
    screenshots_dir: Optional[Path],
    interval: float = 20.0,
    diff_threshold: float = 0.02,
    poll: float = 3.0,
) -> list[Path]:
    """Blocks until the meeting ends, taking a page screenshot every
    `interval` seconds (skipped entirely if screenshots_dir is None). Single
    thread, single Playwright user — safe."""
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
            except PWError:
                pass  # transient navigation/closed page - keep going
            next_shot = time.time() + interval
        time.sleep(min(poll, max(0.1, next_shot - time.time())))

    return saved
```

Then in `cmd_zoom` (`cli.py`): drop the separate `capturer.start()`/`.stop()`
thread management entirely, call `run_capture_loop(handle, screenshots_dir if
not args.no_screenshots else None, interval=args.screenshot_interval)`
directly in place of `wait_for_meeting_end(handle)`, inside the same
try/except KeyboardInterrupt block. `AudioRecorder` stays on its own thread —
that's fine, it never touches Playwright.

Needs re-adding to `zoom_playwright_bot.py`: `io`, `datetime`, `PIL.Image`,
`from .capture import frame_changed` (all were removed when
`PageScreenshotCapturer` was deleted — see git diff of this session).

**Test:** join a real/dummy meeting, confirm screenshots land in
`raw/screenshots/` and that switching Chrome tabs or covering the window with
another app does *not* affect what gets captured (unlike the mss stand-in).

---

## Option 2 — free up system audio for other things (single class)

No code change needed. `AudioRecorder(source="loopback")` records whatever
the Windows *default* output device is playing — so it picks up everything,
not just Zoom.

Windows 11 has per-app output device routing built in:
Settings → System → Sound → Volume mixer → pick a different output device
for each running app. Practical setup: leave the Zoom Chromium instance on
the system default device (what the bot loopback-records), and route
anything else you want to listen to (Discord, Spotify, another call) to your
headphones/a different device. No installs, no code.

Worth a line in `README.md`'s Zoom section once Option 1 lands.

---

## Option 3 — 6 classes in parallel, each with separate audio + screenshots

**Screenshots: already solved by Option 1.** Once screenshots come from
`page.screenshot()` on each instance's own `page` object, running 6 separate
`catedrai zoom <link>` processes (just literally invoke the CLI 6 times, no
new code) gives 6 independent, non-overlapping screenshot streams for free —
each is scoped to that instance's own browser tab regardless of monitors or
window layering.

**Audio is the real blocker.** `soundcard`'s loopback grabs the *system
default output device* — a single shared resource. Running 6 instances today
would have all 6 `AudioRecorder`s each capture the exact same mixed audio
(all 6 classes overlapping, indistinguishable). Two ways to actually isolate
per-instance audio:

### Option 3.A (recommended) — per-process WASAPI loopback capture

Windows has a native API (available since ~Windows 10 2004 / build 19041) to
capture the audio rendered by one specific process (and optionally its
children) instead of the whole system mix — this is what OBS's "Application
Audio Capture" source and Windows' own per-app audio features are built on.
Since each `catedrai zoom` instance already runs its own dedicated Chromium
process (Playwright launches a fresh one per `launch_and_join()` call), this
maps cleanly: capture *that PID's* rendered audio, nothing else, no virtual
devices, no extra installs, and it scales to any number of instances.

**Why this isn't already done:** no mature Python library exposes this
directly. `soundcard` (already a dependency) does device-level loopback
only, not process-level. This needs a small `ctypes`/`comtypes` wrapper
around the raw COM/WASAPI calls. Concretely:

1. `ActivateAudioInterfaceAsync` targeting the virtual audio device ID
   `VAD://Process/<PID>` (the loopback-for-a-process virtual device), passing
   `AUDIOCLIENT_ACTIVATION_PARAMS` with
   `AudioClientActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK`
   and `ProcessLoopbackParams.TargetProcessId = <chromium pid>`,
   `ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE`
   (include the tree, since Chromium is multi-process — the renderer/audio
   service subprocesses are children of the browser process; the browser
   PID is `context.browser.process.pid` via Playwright, but confirm the
   audio-rendering subprocess is actually in that tree before trusting this).
2. `IAudioClient::Initialize` with `AUDCLNT_STREAMFLAGS_LOOPBACK`, then
   `IAudioClient::GetService(IID_IAudioCaptureClient)` and read buffers same
   as any WASAPI capture loop.
3. Microsoft's official C++ reference sample for exactly this is
   **`ApplicationLoopback`** in the `microsoft/Windows-classic-samples`
   GitHub repo — port its `ActivateAudioInterfaceAsync` + activation-params
   struct layout to `ctypes`/`comtypes` rather than reinventing the struct
   offsets. This is the main engineering cost: getting the
   `AUDIOCLIENT_ACTIVATION_PARAMS` struct (a C union) right in ctypes.
4. Wrap the result behind the *same* `AudioRecorder` interface
   (`source="process_loopback"`, taking a `pid` instead of using
   `sc.default_speaker()`), so `cmd_zoom` barely changes — just pass
   `handle.browser` (or whatever exposes the Chromium PID) through.

Estimate: this is a real chunk of COM interop work (get comfortable with
`comtypes.GUID`, custom `ctypes.Structure` for the activation params union,
and the async activation callback pattern) — budget a session, not a
quick patch. Test incrementally: first get *any* process-loopback capture
working against a simple known PID (e.g. a music player) before wiring it
into the Zoom bot.

### Option 3.B — virtual audio cables + per-app routing automation

Simpler conceptually, more moving parts operationally: install a virtual
audio driver (e.g. VB-CABLE; free tier gives 1-2 virtual devices, more
needs a paid tier or running multiple driver products side by side) and
route each Chromium instance's output to its own virtual cable
programmatically — Windows has no public API for "set this process's output
device," but NirSoft's `svcl.exe` (SoundVolumeCommandLine) can do it via
undocumented interfaces and is scriptable from Python via `subprocess`.
`AudioRecorder` per instance then just loopback-records its assigned cable
instead of the system default.

Trade-offs vs. 3.A: needs installing a third-party audio driver (admin
rights, a `.exe` download the user needs to explicitly approve per this
project's rules) plus a third-party CLI tool, and needs enough virtual
devices for 6 concurrent classes (may mean paying for VB-Audio's higher
tier, or combining multiple virtual-cable products). Less code to write,
but more fragile external dependencies and a heavier one-time setup.

**Recommendation:** if parallel classes become a recurring need, invest in
3.A — no runtime dependencies beyond what's already installed, scales to any
number of instances, and is the same mechanism real audio-capture tools use.
If it's a rare/occasional need, 3.B gets there faster despite the extra
moving parts.

---

## Suggested order for next session

1. Implement Option 1 (screenshot fix) — self-contained, fixes a real bug,
   no new dependencies, prerequisite for Option 3 scaling anyway.
2. Re-test `catedrai zoom` end to end (join, audio, screenshots) against a
   real or throwaway meeting.
3. Commit the whole Zoom-bot feature (currently fully uncommitted).
4. Add the Option 2 per-app-audio-routing tip to `README.md`.
5. Only then, if parallel classes are actually needed soon, start Option 3.A
   as its own scoped piece of work.
