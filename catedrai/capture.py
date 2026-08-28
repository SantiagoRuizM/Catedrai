from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import mss
import soundcard as sc
import soundfile as sf
from PIL import Image, ImageChops


@dataclass
class Session:
    name: str
    dir: Path
    audio_path: Path
    screenshots_dir: Path
    started_at: datetime


def create_session(base_dir: Path, name: str | None) -> Session:
    started_at = datetime.now()
    session_name = name or started_at.strftime("%Y-%m-%d_%H%M%S")
    session_dir = base_dir / session_name
    screenshots_dir = session_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    return Session(
        name=session_name,
        dir=session_dir,
        audio_path=session_dir / "audio.wav",
        screenshots_dir=screenshots_dir,
        started_at=started_at,
    )


class AudioRecorder:
    """Records audio to a WAV file until stopped.

    source="microphone" records whatever mic is default (for a live, in-room
    class). source="loopback" records system audio output instead - i.e.
    whatever Windows is playing through the speakers, which is what actually
    picks up a Zoom call's audio regardless of who has permission to record
    inside Zoom itself.
    """

    def __init__(
        self,
        path: Path,
        source: str = "microphone",
        samplerate: int = 48000,
        channels: int = 2,
        chunk_frames: int = 4096,
    ):
        if source not in ("microphone", "loopback"):
            raise ValueError(f"Unknown audio source: {source!r}")
        self.path = path
        self.source = source
        self.samplerate = samplerate
        self.channels = channels
        self.chunk_frames = chunk_frames
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: Exception | None = None

    def _get_device(self):
        if self.source == "loopback":
            speaker = sc.default_speaker()
            return sc.get_microphone(id=str(speaker.name), include_loopback=True)
        return sc.default_microphone()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            device = self._get_device()
            with sf.SoundFile(
                str(self.path),
                mode="w",
                samplerate=self.samplerate,
                channels=self.channels,
                subtype="PCM_16",
            ) as out_file:
                with device.recorder(samplerate=self.samplerate, channels=self.channels) as rec:
                    while not self._stop.is_set():
                        out_file.write(rec.record(numframes=self.chunk_frames))
        except Exception as exc:  # surfaced to the main thread via .error
            self.error = exc

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


class ScreenshotCapturer:
    """Periodically captures the primary monitor, keeping only frames that
    changed meaningfully (so a static slide isn't saved dozens of times)."""

    def __init__(self, out_dir: Path, interval: float = 20.0, diff_threshold: float = 0.02):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.interval = interval
        self.diff_threshold = diff_threshold
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_image: Image.Image | None = None
        self.saved: list[Path] = []
        self.error: Exception | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                while not self._stop.is_set():
                    shot = sct.grab(monitor)
                    img = Image.frombytes("RGB", shot.size, shot.rgb)
                    if self._is_new_frame(img):
                        ts = datetime.now().strftime("%H%M%S_%f")
                        path = self.out_dir / f"{ts}.png"
                        img.save(path)
                        self.saved.append(path)
                        self._last_image = img
                    self._stop.wait(self.interval)
        except Exception as exc:
            self.error = exc

    def _is_new_frame(self, img: Image.Image) -> bool:
        if self._last_image is None:
            return True
        prev = self._last_image.resize((160, 90)).convert("L")
        cur = img.resize((160, 90)).convert("L")
        diff = ImageChops.difference(prev, cur)
        hist = diff.histogram()
        total = sum(i * n for i, n in enumerate(hist))
        max_total = 255 * 160 * 90
        return (total / max_total) > self.diff_threshold

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
