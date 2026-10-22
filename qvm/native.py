"""
Things that work differently on Mac and Windows: file pickers, showing a file
in Finder / Explorer, opening a web link, and keeping the computer awake.
"""

import subprocess
import sys
import webbrowser
from pathlib import Path

WINDOW = None          # the app window, set by main.py once it exists

AUDIO_TYPES = (".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus", ".aiff")
VIDEO_TYPES = (".mp4", ".mov", ".m4v")
HIDDEN = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


def _dialog_kind(name):
    import webview
    fd = getattr(webview, "FileDialog", None)
    if fd is not None:
        return getattr(fd, name)
    return getattr(webview, {"OPEN": "OPEN_DIALOG", "FOLDER": "FOLDER_DIALOG"}[name])


def choose_files(kind="recordings", multiple=True):
    if WINDOW is None:
        return []
    if kind == "video":
        types = ("Videos (*.mp4;*.mov;*.m4v)", "All files (*.*)")
    else:
        types = ("Recordings (*.mp3;*.m4a;*.wav;*.aac;*.flac;*.ogg;*.mp4;*.mov;*.m4v)",
                 "All files (*.*)")
    got = WINDOW.create_file_dialog(_dialog_kind("OPEN"), allow_multiple=multiple,
                                    file_types=types)
    return [str(p) for p in (got or [])]


def choose_folder():
    if WINDOW is None:
        return None
    got = WINDOW.create_file_dialog(_dialog_kind("FOLDER"))
    if not got:
        return None
    return str(got[0] if isinstance(got, (list, tuple)) else got)


def reveal(path):
    """Show this file in Finder / Explorer."""
    path = Path(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except OSError:
        pass


def open_path(path):
    path = str(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            import os
            os.startfile(path)          # noqa - Windows only
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass


def open_url(url):
    webbrowser.open(url)


class KeepAwake:
    """Stop the computer going to sleep while videos are being made."""

    def __init__(self):
        self.proc = None

    def __enter__(self):
        try:
            if sys.platform == "darwin":
                import os
                self.proc = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
            elif sys.platform == "win32":
                import ctypes
                # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        try:
            if self.proc:
                self.proc.terminate()
            elif sys.platform == "win32":
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        except Exception:
            pass
        return False
