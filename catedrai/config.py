import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SESSIONS_DIR = Path(os.environ.get("CATEDRAI_SESSIONS_DIR", PROJECT_ROOT / "sessions"))
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# New layout: data/<semester>/<course_id>/<session_id>/raw/ - see storage.py
DATA_DIR = Path(os.environ.get("CATEDRAI_DATA_DIR", PROJECT_ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

WHISPER_MODEL_SIZE = os.environ.get("CATEDRAI_WHISPER_MODEL", "small")
WHISPER_DEVICE = os.environ.get("CATEDRAI_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("CATEDRAI_WHISPER_COMPUTE", "int8")

ANTHROPIC_MODEL = os.environ.get("CATEDRAI_MODEL", "claude-opus-5")

GOOGLE_CREDENTIALS_PATH = Path(
    os.environ.get("CATEDRAI_GOOGLE_CREDENTIALS", PROJECT_ROOT / "credentials.json")
)
GOOGLE_TOKEN_PATH = Path(os.environ.get("CATEDRAI_GOOGLE_TOKEN", PROJECT_ROOT / "token.json"))
