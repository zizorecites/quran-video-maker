"""
A tiny web server, only reachable from this computer, that the app's window
talks to. Every request must carry a secret key that only the window knows,
so no website can poke at it.
"""

import json
import mimetypes
import os
import secrets
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import core, native, paths

TOKEN = secrets.token_urlsafe(24)
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/quicktime", ".mov")


def _choose_files(kind="recordings"):
    picked = native.choose_files(kind)
    if kind == "video":
        return picked
    return [core.item_view(i) for i in core.add_paths(picked)]


def _choose_folder_recordings():
    folder = native.choose_folder()
    return [core.item_view(i) for i in core.add_paths([folder])] if folder else []


def _choose_background():
    picked = native.choose_files("video", multiple=False)
    if not picked:
        return None
    core.set_background(picked[0])
    for it in core.ITEMS:                 # tick "With background" now there is one
        if it["kind"] == "audio" and not it.get("bg_touched"):
            it["options"]["bg"] = True
    return core.state()["settings"]


def _choose_output():
    folder = native.choose_folder()
    if folder:
        core.save_settings({"out_dir": folder})
        for it in core.ITEMS:
            core.refresh_done(it)
    return core.state()["settings"]


def _set_option(item_id, key, value):
    it = core.item_by_id(item_id)
    it["options"][key] = bool(value)
    if key == "bg":
        it["bg_touched"] = True
    return core.item_view(it)


def _remove_item(item_id):
    core.ITEMS[:] = [i for i in core.ITEMS if i["id"] != item_id or i["status"] in ("queued", "working")]


def _clear_items():
    core.ITEMS[:] = [i for i in core.ITEMS if i["status"] in ("queued", "working")]


def _set_settings(changes):
    s = core.save_settings(changes)
    for it in core.ITEMS:
        core.refresh_done(it)
    return s


def _reveal(path):
    native.reveal(path)


def _open_output():
    out = Path(core.settings()["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    native.open_path(out)


def _split(pid, part, at):
    a, b = core.split_screen(pid, part, int(at))
    return [a, b]


def _set_ayahs(item_id, surah, first, last, rename=False):
    return core.item_view(core.set_ayahs(item_id, surah, first, last, rename))


API = {
    "state": core.state,
    "download_model": core.download_model,
    "add_paths": lambda paths_: [core.item_view(i) for i in core.add_paths(paths_)],
    "choose_files": _choose_files,
    "choose_folder": _choose_folder_recordings,
    "remove_item": _remove_item,
    "clear_items": _clear_items,
    "set_option": _set_option,
    "set_ayahs": _set_ayahs,
    "surahs": core.surah_list,
    "ayah_preview": core.ayah_preview,
    "start": core.start,
    "pause": core.pause,
    "stop": core.stop,
    "settings_set": _set_settings,
    "choose_background": _choose_background,
    "remove_background": lambda: (core.remove_background(), core.state()["settings"])[1],
    "choose_output": _choose_output,
    "style_preview": core.style_preview,
    "projects": core.all_projects,
    "project": core.project_view,
    "save_screens": core.save_screens,
    "split_parts": _split,
    "words": core.words_for,
    "make_again": core.make_again,
    "open_file": lambda path: native.open_path(path),
    "join": lambda pid, index: core.join_screens(pid, int(index)),
    "screen_picture": core.screen_picture,
    "remake": lambda pid: core.start_project(pid, redo=False),
    "redo": lambda pid: core.start_project(pid, redo=True),
    "dismiss": core.dismiss_doubt,
    "reveal": _reveal,
    "open_output": _open_output,
    "open_tiktok": lambda: native.open_url(paths.TIKTOK),
    "can_drop": lambda: native.WINDOW is not None,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):          # keep the console quiet
        pass

    # ---- helpers
    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    # ---- GET: the screens, and media files
    def do_GET(self):
        path = unquote(self.path.split("?", 1)[0])
        if path in ("/", "/index.html"):
            html = (paths.UI / "index.html").read_text(encoding="utf-8")
            html = html.replace("__TOKEN__", TOKEN)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if path.startswith("/ui/"):
            f = (paths.UI / path[4:]).resolve()
            if paths.UI.resolve() in f.parents and f.is_file():
                ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
                return self._send(200, f.read_bytes(), ctype)
            return self._send(404, b"")
        if path.startswith("/media/"):
            return self._media(path[7:])
        if path.startswith("/font/"):
            f = (paths.FONTS / Path(path).name)
            if f.is_file():
                return self._send(200, f.read_bytes(), "font/ttf")
        return self._send(404, b"")

    do_HEAD = do_GET

    def _media(self, tok):
        f = core.MEDIA.get(tok)
        if not f or not os.path.isfile(f):
            return self._send(404, b"")
        size = os.path.getsize(f)
        ctype = mimetypes.guess_type(f)[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        code = 200
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].partition("-")
            if a:
                start = int(a)
                end = int(b) if b else size - 1
            else:                                  # the last N bytes
                start = max(0, size - int(b))
            end = min(end, size - 1)
            code = 206
        length = max(0, end - start + 1)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(f, "rb") as fh:
                fh.seek(start)
                left = length
                while left > 0:
                    chunk = fh.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---- POST: the app asking the backend to do something
    def do_POST(self):
        if self.headers.get("X-Token") != TOKEN:
            return self._send(403, b"")
        name = self.path.rsplit("/", 1)[-1]
        fn = API.get(name)
        if not fn:
            return self._json({"ok": False, "error": "unknown"}, 404)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            args = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            args = {}
        try:
            if isinstance(args, dict):
                if name == "add_paths":
                    out = fn(args.get("paths", []))
                else:
                    out = fn(**args)
            else:
                out = fn(*args)
            self._json({"ok": True, "data": out})
        except (ValueError, KeyError, IndexError) as e:
            self._json({"ok": False, "error": str(e)})
        except SystemExit as e:
            self._json({"ok": False, "error": str(e).strip()})
        except Exception as e:
            traceback.print_exc()
            self._json({"ok": False, "error": f"{e.__class__.__name__}: {e}"})


def serve(port=0):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"
