"""
Where everything lives.

- RESOURCES: things that ship inside the app (Quran text, fonts, screens).
- HOME: this computer's own folder for the app - settings, the listener
  model, what was heard in each recording, and each recording's screens.
"""

import os
import sys
from pathlib import Path

APP_NAME = "Quran Video Maker"
VERSION = "1.0.0"
TIKTOK = "https://www.tiktok.com/@zizorecites"

if getattr(sys, "frozen", False):                 # inside the built app
    RESOURCES = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:                                             # running from the source folder
    RESOURCES = Path(__file__).resolve().parent.parent

ENGINE = RESOURCES / "engine"
DATA = RESOURCES / "resources" / "data"
FONTS = RESOURCES / "resources" / "fonts"
UI = RESOURCES / "ui"


def _home():
    custom = os.environ.get("QVM_HOME")           # lets the tests use a clean folder
    if custom:
        return Path(custom)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / "quran-video-maker"


HOME = _home()
MODELS = HOME / "models"
MODEL_DIR = MODELS / "whisper-small"
TRANSCRIPTS = HOME / "transcripts"
PROJECTS = HOME / "projects"
BACKGROUND = HOME / "background"
THUMBS = HOME / "thumbs"
WORK = HOME / "work"
SETTINGS = HOME / "settings.json"


def default_output():
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "Quran Videos"


def make_dirs():
    for d in (HOME, MODELS, TRANSCRIPTS, PROJECTS, BACKGROUND, THUMBS, WORK):
        d.mkdir(parents=True, exist_ok=True)
