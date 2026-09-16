# Catedrai

Class time shouldn't be two silent hours of listening and hoping you remember it later.
Catedrai automates the part that doesn't need a human: it captures the class as it
happens, turns it into notes you'd actually study from, and tracks the homework, tests,
and deadlines that came out of it - so the focus goes back to the student's own learning
path instead of surviving the lecture.

## What it does (v1 - CLI)

1. **Captures the class automatically** - records the microphone and periodically
   screenshots your screen (deduplicated, so a static slide isn't saved 40 times) for
   the whole session, no manual note-taking required.
2. **Transcribes locally** - audio is transcribed on your machine with
   [faster-whisper](https://github.com/SYSTRAN/faster-whisper); nothing leaves your
   computer at this stage.
3. **Understands the content with Claude** - the transcript (plus the captured slide
   screenshots) is turned into a summary, bullet-point study notes, and plain-language
   definitions for the key terms/concepts mentioned.
4. **Extracts what you're on the hook for** - any homework, tests, or deadlines
   mentioned in class are pulled out with resolved dates (e.g. "next Monday" becomes an
   actual date) and pushed to your Google Calendar automatically.

Everything lands in `sessions/<name>/`: `audio.wav`, `screenshots/`, `transcript.txt`,
`notes.md`, and `events.json`.

### Deliberately out of scope for v1

- No UI yet - this is a CLI to validate the pipeline first.
- No full day-by-day spaced-repetition study plan generator - v1 stops at extracting
  and listing/syncing deadlines. Worth adding once the core loop is solid.
- No dedicated video recording - periodic deduplicated screenshots cover slide/board
  content without the size and processing cost of full video.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY
```

Whisper model size trades speed for accuracy - the default (`small`) runs fine on CPU.
Set `CATEDRAI_WHISPER_MODEL=base` for faster/lower-quality, or `medium`/`large-v3` if you
have a GPU (`CATEDRAI_WHISPER_DEVICE=cuda`).

### Google Calendar (for automatic event sync)

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and
   enable the **Google Calendar API**.
2. Create an OAuth client ID of type **Desktop app** and download it.
3. Save the downloaded file as `credentials.json` in the project root.
4. Run `catedrai calendar-auth` once - it opens a browser to authorize, then stores a
   `token.json` locally so future runs don't prompt again.

If you skip this, use `--no-calendar` and events still show up in `notes.md` /
`events.json`.

## Usage

Start a class - records until you stop it, then automatically transcribes, analyzes,
writes notes, and syncs calendar events:

```bash
python -m catedrai class
python -m catedrai class --name "algo101-lecture4" --screenshot-interval 15
python -m catedrai class --no-calendar        # skip Google Calendar sync
python -m catedrai class --no-screenshots     # audio only
```

Press `Ctrl+C` to end the class and kick off processing.

Reprocess a session you already captured (e.g. calendar sync failed, or you want to
rerun analysis):

```bash
python -m catedrai process sessions/algo101-lecture4
```

### Zoom auto-join

Auto-join a Zoom meeting from its link and capture it (audio + screenshots only - run
`process` afterward once you have an `ANTHROPIC_API_KEY` to generate notes):

```bash
python -m catedrai zoom https://universidad.zoom.us/j/123456789
python -m catedrai zoom <link> --no-screenshots     # audio only
python -m catedrai zoom <link> --headless           # no visible browser window
```

It joins via the web client as a guest with a random display name, records system audio
(whatever the default output device is playing), and takes deduplicated screenshots of
the meeting page itself - immune to which window/tab is on top. Recording stops
automatically when the meeting ends, or on `Ctrl+C`.

Because audio is recorded from the *system default output device* by default, it picks
up anything else playing through that device too. If you want to listen to something
else (Discord, Spotify, another call) while the bot records, route it to a different
output device: Windows Settings -> System -> Sound -> Volume mixer -> pick a different
output per app, leaving the Zoom browser on the default device.

**Recording without hearing the class:** loopback capture requires the audio to actually
be rendered to *some* output device, but that device doesn't have to be your real
speakers/headphones - it can be a virtual one:

1. Install a virtual audio cable, e.g. [VB-CABLE](https://vb-audio.com/Cable/) (free,
   needs admin rights to install). It adds a playback device named
   `CABLE Input` and a matching recording device `CABLE Output`.
2. Start the bot with `--audio-device "CABLE Input"` (the exact name, not just `CABLE` -
   `CABLE Output` also contains that substring and picking the wrong one silently
   records nothing):
   ```bash
   python -m catedrai zoom <link> --audio-device "CABLE Input"
   ```
3. *Once it's joined and the meeting's Chromium tab is actively playing audio* (Windows
   only lists apps with an active audio session), route it to the cable: Windows
   Settings -> System -> Sound -> Volume mixer -> set Chromium's output device to
   `CABLE Input`.

The meeting audio is still captured in full; it just never reaches a device you can
hear. A typo in `--audio-device` is rejected immediately at startup rather than silently
recording nothing for the whole class.

## Project layout

```
catedrai/
  capture.py        # audio + screenshot recording during class
  transcribe.py      # local speech-to-text (faster-whisper)
  analyze.py         # Claude: summary, notes, key terms, event extraction
  calendar_sync.py   # Google Calendar OAuth + event creation
  output.py          # writes notes.md / events.json / transcript.txt
  cli.py             # `class`, `process`, `calendar-auth` commands
sessions/             # captured + generated output per class (gitignored)
```
