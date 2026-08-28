from __future__ import annotations

from pathlib import Path

from faster_whisper import WhisperModel

from .config import WHISPER_COMPUTE_TYPE, WHISPER_DEVICE, WHISPER_MODEL_SIZE

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(
            WHISPER_MODEL_SIZE, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE
        )
    return _model


def transcribe_audio(audio_path: Path) -> str:
    """Transcribes a recorded class locally (no audio ever leaves the machine)."""
    model = _get_model()
    segments, _info = model.transcribe(str(audio_path), vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()
