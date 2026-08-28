# Catedrai — Project Overview & Plan

## What Catedrai is

Class time is mostly overhead. A two-hour lecture usually boils down to: a handful of
concepts worth understanding, a few terms worth defining, and one or two things you now
owe (a homework, a test date, a deadline). Catedrai automates everything *up to* that
point, so the student's actual time and attention go into the part a machine can't do —
learning the material and getting the homework/test done.

**Mission:** capture the class automatically, turn it into notes worth reading, and
surface exactly what the student needs to act on next — no manual note-taking, no
re-listening to a recording to find the one sentence where the professor mentioned the
exam date.

## Core pipeline

The pipeline is the same regardless of where the class content comes from — only the
*capture* step differs by source:

```
[Capture] --> [Transcribe] --> [Analyze with Claude] --> [Outputs]
                                                            |
                                                            |-- notes.md      (summary, bullet notes, key-term glossary)
                                                            |-- events.json   (homework / tests / deadlines, dates resolved)
                                                            |-- transcript.txt
                                                            `-- (later) calendar sync + self-study plan
```

- **Transcribe** — local speech-to-text (faster-whisper). Nothing leaves the machine at
  this stage.
- **Analyze** — the transcript (plus any slide/screen images captured) is sent to Claude,
  which returns a structured result: title, summary, bullet-point notes, key terms with
  plain-language definitions, and a list of extracted events (`homework` / `test` /
  `deadline` / `event`) with dates resolved to absolute ISO dates using the class date as
  the reference point.
- **Outputs** — written per-session so nothing is silently lost even if a later step
  (like calendar sync) fails.

## Capture sources

Catedrai is meant to work regardless of how the class happens. Two sources:

### 1. Live capture (already implemented)

For an in-person class or any call happening on the student's own machine: records the
microphone continuously and takes periodic, de-duplicated screenshots (so a static slide
isn't saved dozens of times). Lives in `catedrai/capture.py`, driven by `catedrai class`.

### 2. Zoom auto-join bot — **implemented, tested live**

The actual point of this source: you shouldn't need to manually attend, click record, or
even be at the computer for the class to get captured. Given just the class's Zoom link,
Catedrai joins it automatically, on your own PC, as a distinct participant - no Zoom
Marketplace app, no cloud recording permission from the host, no VPS.

**How it works (`catedrai/zoom_link.py` + `catedrai/zoom_bot.py`):**

1. **Parse the link** - `parse_zoom_link()` pulls the meeting number (and passcode, if
   present in the URL's `pwd` param) out of a normal join link
   (`https://<org>.zoom.us/j/<id>?pwd=...`).
2. **Launch straight into the join flow** - `build_join_uri()` constructs the
   `zoommtg://` deep link Zoom's own "Open Zoom Workplace app" button uses under the
   hood, and `os.startfile()` hands it to the OS, which routes it directly to the
   installed Zoom desktop client (no browser involved).
3. **Click through whatever the client shows** - name entry, "join with computer audio",
   etc. Real Zoom buttons carry full accessible descriptions (e.g. `"Abandonar, Alt+Q"`,
   not just `"Abandonar"`), and pywinauto's raw `Desktop().windows()` wrapper doesn't
   support `child_window()`/`.wait()`/substring title matching at all - so
   `_find_button()` walks the live control tree itself and matches by substring. Zoom
   windows are identified by their **owning process** (`zoom.exe`/`cpthost.exe`), not by
   window title or class name - a title-substring match will happily grab an unrelated
   window that merely mentions "Zoom" (confirmed live: it grabbed a Chrome tab and a
   terminal tab during testing).
4. **Capture system audio, not the microphone** - `AudioRecorder(source="loopback")` in
   `capture.py` records whatever Windows is actually playing (via `soundcard`'s WASAPI
   loopback), which is the mixed meeting audio - no dependency on the host granting
   local-recording permission, since this isn't Zoom's own recording feature at all, just
   OS-level capture of your own machine's audio output.
5. **Capture the screen** - the same periodic, de-duplicated screenshot capture used by
   Source 1, pointed at whatever's on screen (the joined meeting window, ideally not
   minimized - minimizing the window stops it from being drawn, and screenshots capture
   pixels, not window content).
6. **Detect when the meeting ends** - `wait_for_meeting_end()` polls the meeting window's
   raw HWND via `win32gui.IsWindow()` until it's destroyed (the host ending the meeting
   closes it for every participant automatically - no click needed on our end for the
   real "class ends" case).
7. **Resolve course identity and write output** - `get_meeting_topic()` reads the topic
   off the joined window (its own title turned out to be the reliable source, live-tested
   against an ad-hoc meeting; descendant `Text` controls mostly held small UI badges, not
   the topic), then `storage.resolve_course()` / `storage.new_session_raw_dir()` (see
   below) pick where the captured files land, and the existing pipeline -
   `transcribe_audio()` → `analyze_session()` → `write_outputs()` - runs unchanged.

**Storage layout (`catedrai/storage.py`):** `data/<semester>/<course_id>/<session_id>/raw/`
holds the raw capture (audio, screenshots, `meta.json`); transcript/notes/events get
written as siblings of `raw/`. Course identity is registry-backed
(`data/courses.json`, keyed by the Zoom meeting number) since a recurring class link has a
static confno but an inconsistently-typed topic isn't reliable across weeks - the registry
auto-seeds from the first topic seen and is the source of truth after that (hand-editable
if a parse comes out wrong). **Only ever read/write `data/courses.json` through
`storage.py`'s functions, or explicit `encoding="utf-8"` Python** - a plain
`Get-Content`/`ConvertTo-Json` round-trip in Windows PowerShell silently mangles the
accented characters (confirmed the hard way during testing).

**Validated live**, end to end: joined a real second Zoom meeting as a distinct
participant (confirmed via the participant list showing 2 participants), captured real
loopback audio and a screenshot, detected the meeting ending after leaving, and wrote
`meta.json` into the correct `data/.../raw/` path.

**Known limitations / not yet handled:**

- The join-time dialogs actually observed (name entry, "join with computer audio")
  weren't exercised live this session - the test meeting joined without needing either,
  so `_click_first_match`'s handling of them is implemented and uses the now-validated
  `_find_button()` mechanism, but hasn't been exercised against a real occurrence yet.
- If the bot needs to leave a meeting itself (rather than the host ending it), Zoom shows
  a confirmation dialog ("¿Finalizar reunión o salir de la reunión?") - deliberately not
  auto-clicked, since auto-confirming a "leave/end meeting" prompt is the kind of action
  that could disrupt an actual ongoing call if the detection logic ever misfires.
- A meeting with a real Waiting Room (host must manually admit each participant) will
  block the bot exactly like it would any human guest - there's no way around that from
  either the SDK or this approach.
- Calendar sync stays out of scope for now - `calendar_sync.py` still works via
  `catedrai process <session>`, just isn't wired into the Zoom flow yet.

## Roadmap

| Phase | Scope |
|---|---|
| **1 — done** | Zoom auto-join bot → loopback audio + screenshots → transcript + notes + key terms + extracted events, tested live end to end |
| 2 | Calendar sync wired into the Zoom flow by default |
| 3 | Self-study plan generation — break detected homework/tests into a day-by-day plan |
| 4 (maybe) | A scheduler that knows class times and launches the bot itself, a real UI instead of the CLI |

## Repository layout (current)

```
catedrai/
  capture.py          # mic OR system-audio (loopback) recording + de-duplicated screenshots
  zoom_link.py         # parses a Zoom join link into meeting number + passcode
  zoom_bot.py           # auto-joins Zoom via zoommtg://, drives the UI, detects meeting end
  storage.py             # data/<semester>/<course_id>/<session_id>/raw/ layout + course registry
  transcribe.py           # local speech-to-text (faster-whisper)
  analyze.py               # Claude: summary, notes, key terms, event extraction
  calendar_sync.py          # Google Calendar OAuth + event creation (implemented, deprioritized)
  output.py                  # writes notes.md / events.json / transcript.txt
  cli.py                      # `class`, `zoom`, `zoom-debug`, `process`, `calendar-auth` commands
sessions/                     # output for the older live-capture flow (Source 1, gitignored)
data/                          # output for the Zoom bot flow (Source 2, gitignored) - see storage.py
docs/
  CATEDRAI.md                  # this document
```
