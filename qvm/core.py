"""
The app's brain: the list of recordings, making the videos one after another,
settings, and the screen editor.

The video making itself is the same engine as the Terminal tool
(engine/quranvid.py and friends). This file only drives it.
"""

import base64
import io
import json
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import uuid
from pathlib import Path

from . import native, paths

sys.path.insert(0, str(paths.ENGINE))
import english_map          # noqa: E402
import listen               # noqa: E402
import quranvid as q        # noqa: E402

LOCK = threading.RLock()


class Stopped(Exception):
    """Stop was pressed."""


# ------------------------------------------------------------------ engine
def find_ffmpeg():
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg")


def setup_engine():
    """Point the engine at the app's own files and its own copy of ffmpeg."""
    paths.make_dirs()
    q.DATA = paths.DATA
    q.FONTS = paths.FONTS
    q.ARABIC_FONT = paths.FONTS / "UthmanicHafs-v18.ttf"
    q.ENGLISH_FONT = paths.FONTS / "Montserrat.ttf"
    q.BACKGROUND_DIR = paths.BACKGROUND
    q.TIMINGS_DIR = paths.HOME / "timings"
    english_map.GLOSS_FILE = paths.DATA / "glosses.json"
    english_map._GLOSS = None
    listen.MODEL_DIR = paths.MODEL_DIR
    listen.CACHE_DIR = paths.TRANSCRIPTS
    exe = find_ffmpeg()
    if exe:
        q.FFMPEG = exe
        listen.FFMPEG = exe
    q.FFPROBE = shutil.which("ffprobe") or ""
    # most copies of ffmpeg have libx264; if this one doesn't, use what it has
    try:
        enc = q.run(["ffmpeg", "-hide_banner", "-encoders"]).stdout
    except OSError:
        enc = ""
    if " libx264 " not in enc:
        if " h264_videotoolbox " in enc:
            q.VIDEO_CODEC = ["-c:v", "h264_videotoolbox", "-b:v", "10M", "-pix_fmt", "yuv420p"]
        elif " h264_mf " in enc:
            q.VIDEO_CODEC = ["-c:v", "h264_mf", "-b:v", "10M", "-pix_fmt", "yuv420p"]
        else:
            q.VIDEO_CODEC = ["-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p"]
    return exe


QURAN = None


def quran():
    global QURAN
    if QURAN is None:
        QURAN = q.load_quran()
    return QURAN


# ---------------------------------------------------------------- settings
DEFAULTS = {
    "out_dir": str(paths.default_output()),
    "bg_file": None,          # the background for MP3s, copied into the app's folder
    "bg_name": None,
    "bg_blur": 0,
    "skip_done": True,
    "keep_awake": True,
    "arabic_size": 118,
    "english_size": 56,
    "fade": 0.25,
}


def load_settings():
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(paths.SETTINGS.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    if s.get("bg_file") and not Path(s["bg_file"]).exists():
        s["bg_file"] = s["bg_name"] = None
    return s


SETTINGS = None


def settings():
    global SETTINGS
    if SETTINGS is None:
        SETTINGS = load_settings()
    return SETTINGS


def save_settings(changes):
    s = settings()
    for k, v in changes.items():
        if k in DEFAULTS:
            s[k] = v
    paths.SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")
    return s


def apply_look(s=None):
    s = s or settings()
    q.ARABIC_SIZE = int(s["arabic_size"])
    q.ENGLISH_SIZE = int(s["english_size"])
    q.FADE = float(s["fade"])


def set_background(src):
    """Copy the chosen clip into the app's own folder, so it keeps working
    even if the original is moved or deleted."""
    src = Path(src)
    for old in paths.BACKGROUND.iterdir():
        try:
            old.unlink()
        except OSError:
            pass
    dest = paths.BACKGROUND / ("background" + src.suffix.lower())
    shutil.copyfile(src, dest)
    for old in paths.THUMBS.glob("_bg*"):
        old.unlink(missing_ok=True)
    return save_settings({"bg_file": str(dest), "bg_name": src.name})


def remove_background():
    for old in paths.BACKGROUND.iterdir():
        try:
            old.unlink()
        except OSError:
            pass
    return save_settings({"bg_file": None, "bg_name": None})


# ------------------------------------------------------------- the listener
MODEL_FILES = ["config.json", "tokenizer.json", "vocabulary.txt", "model.bin"]
MODEL_URL = "https://huggingface.co/Systran/faster-whisper-small/resolve/main/"
SETUP = {"downloading": False, "done": 0, "total": 0, "error": None, "tested": False}


def model_ready():
    return all((paths.MODEL_DIR / f).exists() for f in MODEL_FILES)


def _ssl_context():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def download_model():
    """Fetch the listener (about 480 MB) the first time the app opens."""
    with LOCK:
        if SETUP["downloading"]:
            return
        SETUP.update(downloading=True, error=None, done=0, total=0)

    def work():
        try:
            paths.MODEL_DIR.mkdir(parents=True, exist_ok=True)
            ctx = _ssl_context()
            sizes = {}
            for f in MODEL_FILES:
                req = urllib.request.Request(MODEL_URL + f, method="HEAD")
                with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
                    sizes[f] = int(r.headers.get("Content-Length") or 0)
            SETUP["total"] = sum(sizes.values())
            done_before = 0
            for f in MODEL_FILES:
                dest = paths.MODEL_DIR / f
                if dest.exists() and dest.stat().st_size == sizes[f]:
                    done_before += sizes[f]
                    SETUP["done"] = done_before
                    continue
                tmp = dest.with_suffix(dest.suffix + ".part")
                with urllib.request.urlopen(MODEL_URL + f, context=ctx, timeout=60) as r, \
                        open(tmp, "wb") as out:
                    got = 0
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                        got += len(chunk)
                        SETUP["done"] = done_before + got
                tmp.replace(dest)
                done_before += sizes[f]
            # a quick test that it really loads
            from faster_whisper import WhisperModel
            WhisperModel(str(paths.MODEL_DIR), device="cpu", compute_type="int8")
            SETUP["tested"] = True
        except Exception as e:                       # no internet, etc.
            SETUP["error"] = str(e) or e.__class__.__name__
        finally:
            SETUP["downloading"] = False

    threading.Thread(target=work, daemon=True).start()


# ----------------------------------------------------------------- recordings
def surah_label(surah, first, last):
    name = q.SURAHS[surah - 1]
    count = quran()[2][surah]
    if first == 1 and last == count:
        return name
    return f"{name} {first}" + (f"–{last}" if last != first else "")


def file_name_for(surah, first, last):
    """Al-Mulk 7-12 -> Mulk7-12, the way your files are named."""
    name = re.sub(r"^(Al|An|Ar|As|Ash|At|Ad|Adh|Az)-", "", q.SURAHS[surah - 1])
    name = name.replace(" ", "")
    count = quran()[2][surah]
    if first == 1 and last == count:
        return name
    return f"{name}{first}" + (f"-{last}" if last != first else "")


def reference_for(stem):
    surah, first, last = q.parse_reference(stem)
    if not surah:
        return None
    counts = quran()[2]
    if first is None:
        first, last = 1, counts[surah]
    last = min(last, counts[surah])
    if first > last:
        return None
    return {"surah": surah, "first": first, "last": last,
            "label": surah_label(surah, first, last)}


def video_size(path):
    """Width and height of a video, the right way up (phones save some sideways)."""
    out = q.run(["ffmpeg", "-hide_banner", "-i", str(path)]).stderr
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    rot = re.search(r"rotation of (-?\d+(?:\.\d+)?)|rotate\s*:\s*(-?\d+)", out)
    if rot:
        angle = abs(float(rot.group(1) or rot.group(2))) % 180
        if 45 < angle < 135:
            w, h = h, w
    return w, h


def output_size(w, h):
    """The size to make a video that uses your own recording as the background:
    the same shape as your video, no bigger than 1920 on its long side."""
    scale = min(1.0, 1920.0 / max(w, h))
    return int(round(w * scale / 2)) * 2, int(round(h * scale / 2)) * 2


ITEMS = []          # the recordings on the Make videos screen


def item_by_id(item_id):
    for it in ITEMS:
        if it["id"] == item_id:
            return it
    return None


def outputs_for(it, s=None):
    """Every video this recording can make: kind -> file path."""
    s = s or settings()
    out = Path(s["out_dir"])
    stem = Path(it["path"]).stem
    res = {"black": out / f"{stem}_guess.mp4"}
    if it["kind"] == "video":
        own = out / f"{stem}.mp4"
        if own.resolve() == Path(it["path"]).resolve():
            own = out / f"{stem} (with text).mp4"
        res["own"] = own
    else:
        res["bg"] = out / f"{stem}.mp4"
    return res


def already_made(path, s=None):
    s = s or settings()
    path = Path(path)
    return path.exists() or (path.parent / "Published" / path.name).exists()


def refresh_done(it):
    outs = outputs_for(it)
    it["made"] = {} if it.get("remake") else {k: already_made(p) for k, p in outs.items()}


def wanted(it):
    return [k for k in ("black", "bg", "own") if it["options"].get(k)]


def add_paths(raw_paths):
    """Add recordings (or every recording in a folder) to the list."""
    found = []
    for p in raw_paths:
        p = Path(p)
        if p.is_dir():
            found += sorted(f for f in p.iterdir()
                            if f.suffix.lower() in native.AUDIO_TYPES + native.VIDEO_TYPES
                            and not f.name.startswith(".") and ".part." not in f.name)
        elif p.suffix.lower() in native.AUDIO_TYPES + native.VIDEO_TYPES and p.exists():
            found.append(p)
    added = []
    have = {str(Path(it["path"]).resolve()) for it in ITEMS}
    for f in found:
        key = str(f.resolve())
        if key in have:
            continue
        have.add(key)
        kind = "video" if f.suffix.lower() in native.VIDEO_TYPES else "audio"
        it = {"id": uuid.uuid4().hex[:10], "path": str(f), "name": f.name, "kind": kind,
              "ref": reference_for(f.stem), "duration": None, "size": None,
              "status": "ready", "error": None, "made": {}}
        try:
            it["duration"] = q.audio_length(f)
        except SystemExit:
            it["status"], it["error"] = "failed", "This file can't be opened."
        if kind == "video":
            it["size"] = video_size(f)
            it["options"] = {"own": True, "black": False}
            still = frame_of(f, min(1.0, (it["duration"] or 2) / 2),
                             f"_item_{it['id']}.jpg", 320)
            it["thumb"] = media_url(still) if still else None
        else:
            it["options"] = {"black": True, "bg": bool(settings().get("bg_file"))}
        if not it["ref"] and it["status"] == "ready":
            it["status"] = "needs_ayahs"
        refresh_done(it)
        ITEMS.append(it)
        added.append(it)
    return added


def set_ayahs(item_id, surah, first, last, rename=False):
    it = item_by_id(item_id)
    counts = quran()[2]
    surah, first, last = int(surah), int(first), int(last)
    if not (1 <= surah <= 114) or not (1 <= first <= last <= counts[surah]):
        raise ValueError(f"{q.SURAHS[surah - 1]} has ayahs 1 to {counts[surah]}.")
    it["ref"] = {"surah": surah, "first": first, "last": last,
                 "label": surah_label(surah, first, last)}
    if rename:
        src = Path(it["path"])
        dest = src.with_name(file_name_for(surah, first, last) + src.suffix)
        if not dest.exists():
            try:
                src.rename(dest)
                it["path"], it["name"] = str(dest), dest.name
            except OSError:
                pass
    if it["status"] == "needs_ayahs":
        it["status"] = "ready"
    refresh_done(it)
    return it


def ayah_preview(surah, first, last):
    ar = quran()[0]
    a = q.mushaf_arabic(ar[(int(surah), int(first))]).split()
    b = q.mushaf_arabic(ar[(int(surah), int(last))]).split()
    return {"start": " ".join(a[:6]) + (" …" if len(a) > 6 else ""),
            "end": ("… " if len(b) > 5 else "") + " ".join(b[-5:])}


def surah_list():
    counts = quran()[2]
    return [{"n": i, "name": q.SURAHS[i - 1], "ayahs": counts[i]} for i in range(1, 115)]


# ------------------------------------------------------------------ projects
def project_path(pid):
    return paths.PROJECTS / f"{pid}.json"


def project_id(source):
    stem = Path(source).stem
    return re.sub(r"[^A-Za-z0-9'_-]+", "_", stem) or "recording"


def load_project(pid):
    try:
        return json.loads(project_path(pid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_project(p):
    p["updated"] = time.time()
    project_path(p["id"]).write_text(json.dumps(p, ensure_ascii=False, indent=1),
                                     encoding="utf-8")


def text_model(ref):
    """Every word of these ayahs, and the English for any run of them."""
    ar, en, _ = quran()
    ayahs = [(ref["surah"], a) for a in range(ref["first"], ref["last"] + 1)]
    text = []
    for key in ayahs:
        for w in q.mushaf_arabic(ar[key]).split():
            text.append((key[1], w))
    finals = {}
    for k, (ay, _) in enumerate(text):
        finals[ay] = k
    return text, finals, q.EnglishForWords(ayahs, ar, en)


_MODELS = {}


def model_for(ref):
    key = (ref["surah"], ref["first"], ref["last"])
    if key not in _MODELS:
        _MODELS[key] = text_model(ref)
    return _MODELS[key]


def words_shown(ref, lo, hi):
    text, finals, english_for = model_for(ref)
    shown = []
    for k in range(lo, hi + 1):
        shown.append(text[k][1])
        if finals[text[k][0]] == k:
            shown.append(q.ayah_marker(text[k][0]))
    return " ".join(shown), english_for(lo, hi), text[hi][0]


def word_times(parts, heard, where, total):
    """When each word of each screen was said - so a screen can be split at a
    word without anyone typing a time."""
    said = {}
    for h, j in zip(heard, where):
        if j is None:
            continue
        said.setdefault(j, []).append(h["start"])
        if h.get("two"):
            said.setdefault(j - 1, []).append(h["start"])
    for i, p in enumerate(parts):
        if "lo" not in p:
            continue
        end = parts[i + 1]["start"] if i + 1 < len(parts) else total
        times = []
        for k in range(p["lo"], p["hi"] + 1):
            inside = [t for t in said.get(k, []) if p["start"] - 0.3 <= t < end]
            times.append(round(min(inside), 2) if inside else None)
        p["times"] = times


def waveform(db, bars=400):
    if db is None or len(db) == 0:
        return []
    import numpy as np
    n = len(db)
    edges = np.linspace(0, n, bars + 1).astype(int)
    vals = [float(db[a:b].max()) if b > a else -90.0 for a, b in zip(edges, edges[1:])]
    lo, hi = float(np.percentile(db, 10)), max(vals)
    return [round(max(0.0, min(1.0, (v - lo) / max(1e-6, hi - lo))), 3) for v in vals]


def screens(p):
    """The screens of a project with their end times and repeat marks."""
    parts = p["parts"]
    out = []
    for i, part in enumerate(parts):
        end = parts[i + 1]["start"] if i + 1 < len(parts) else p["duration"]
        d = dict(part)
        d["end"] = end
        prev_hi = max([x.get("hi", -1) for x in parts[:i]] or [-1])
        d["repeat"] = "lo" in part and i > 0 and part["lo"] <= prev_hi
        out.append(d)
    return out


def split_screen(pid, part, at):
    """Split a screen before its word number `at` (counting from 0)."""
    p = load_project(pid)
    lo, hi = part["lo"], part["hi"]
    m = lo + int(at)
    if not (lo < m <= hi):
        raise ValueError("Pick a gap between two words.")
    end = float(part.get("end") or p["duration"])
    times = part.get("times") or [None] * (hi - lo + 1)
    t = times[m - lo]
    if t is None:                                   # never heard: share out the time
        t = part["start"] + (end - part["start"]) * (m - lo) / (hi - lo + 1)
    t = max(part["start"] + 0.2, min(end - 0.2, t - 0.1))
    a_ar, a_en, a_ay = words_shown(p["ref"], lo, m - 1)
    b_ar, b_en, b_ay = words_shown(p["ref"], m, hi)
    first = {"start": part["start"], "ayah": a_ay, "lo": lo, "hi": m - 1,
             "arabic": a_ar, "english": a_en, "times": times[:m - lo]}
    second = {"start": round(t, 2), "ayah": b_ay, "lo": m, "hi": hi,
              "arabic": b_ar, "english": b_en, "times": times[m - lo:]}
    return first, second


def words_for(pid, lo, hi):
    p = load_project(pid)
    ar, en, ay = words_shown(p["ref"], int(lo), int(hi))
    return {"arabic": ar, "english": en, "ayah": ay}


def make_again(item_id):
    it = item_by_id(item_id)
    it["remake"] = True
    it["made"] = {}
    return item_view(it)


def join_screens(pid, index):
    """Join screen `index` with the one after it."""
    p = load_project(pid)
    a, b = p["parts"][index], p["parts"][index + 1]
    if "lo" in a and "lo" in b and not a.get("custom") and not b.get("custom") \
            and b["lo"] == a["hi"] + 1:
        ar, en, ay = words_shown(p["ref"], a["lo"], b["hi"])
        return {"start": a["start"], "ayah": ay, "lo": a["lo"], "hi": b["hi"],
                "arabic": ar, "english": en,
                "times": (a.get("times") or []) + (b.get("times") or [])}
    # a repeat, or text you typed: keep both, one after the other
    return {"start": a["start"], "ayah": b["ayah"], "arabic": a["arabic"] + " " + b["arabic"],
            "english": (a["english"] + " " + b["english"]).strip(), "custom": True}


# -------------------------------------------------------------- media + pics
MEDIA = {}          # token -> path, only files we handed out can be fetched


def media_url(path):
    if not path:
        return None
    path = str(path)
    for tok, p in MEDIA.items():
        if p == path:
            return f"/media/{tok}"
    tok = uuid.uuid4().hex
    MEDIA[tok] = path
    return f"/media/{tok}"


def frame_of(video, at, name, width=960):
    """A still from a video, kept so it is only made once."""
    dest = paths.THUMBS / name
    if not dest.exists():
        q.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(video),
               "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(dest)])
    return dest if dest.exists() else None


def bg_still():
    s = settings()
    if not s.get("bg_file"):
        return None
    f = Path(s["bg_file"])
    if f.suffix.lower() in (".jpg", ".png"):
        return f
    return frame_of(f, 1.0, f"_bg_{int(f.stat().st_mtime)}.jpg")


def picture(arabic, english, under=None, size=(1920, 1080), width=960):
    """What one screen looks like, as a picture for the app to show."""
    from PIL import Image
    apply_look()
    layer = q.render_slide(arabic, english, tuple(size))
    if under and Path(under).exists():
        base = Image.open(under).convert("RGBA").resize(size)
    else:
        base = Image.new("RGBA", size, (0, 0, 0, 255))
    img = Image.alpha_composite(base, layer).convert("RGB")
    img.thumbnail((width, width))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


SAMPLE_AR = None


def style_preview(look=None):
    global SAMPLE_AR
    if SAMPLE_AR is None:
        words = q.mushaf_arabic(quran()[0][(98, 8)]).split()
        SAMPLE_AR = " ".join(words[5:12])
    s = dict(settings())
    s.update(look or {})
    apply_look(s)
    try:
        return picture(SAMPLE_AR, "under which rivers flow, to stay there for ever and ever.",
                       under=bg_still())
    finally:
        apply_look()


# --------------------------------------------------------------- making videos
RUN = {"active": False, "paused": False, "stop": False, "item": None, "steps": [],
       "overall": 0.0, "eta": None, "slide": None, "queue": [], "results": [],
       "started": None, "error": None}
PAUSE = threading.Event()
PAUSE.set()
RATE = {"render": 1.0, "listen": 0.6}       # seconds of work per second of audio


def _check():
    if RUN["stop"]:
        raise Stopped()
    if not PAUSE.is_set():
        RUN["paused"] = True
        while not PAUSE.wait(0.3):
            if RUN["stop"]:
                raise Stopped()
        RUN["paused"] = False


def _step(i, state, detail=None, progress=None):
    st = RUN["steps"][i]
    st["state"] = state
    if detail is not None:
        st["detail"] = detail
    st["progress"] = progress
    _update_eta()


def _update_eta():
    left = 0.0
    for it_id in RUN["queue"]:
        it = item_by_id(it_id)
        if it and it["status"] == "queued":
            left += _estimate(it)
    if RUN["item"]:
        it = item_by_id(RUN["item"])
        for st in RUN["steps"]:
            if st["state"] != "done":
                left += st.get("cost", 0) * (1 - (st.get("progress") or 0))
    RUN["eta"] = left


def _estimate(it):
    d = it.get("duration") or 60
    cached = (paths.TRANSCRIPTS / f"{Path(it['path']).stem}.json").exists()
    return (0 if cached else RATE["listen"] * d) + len(wanted(it)) * RATE["render"] * d + 3


def start(item_ids=None):
    with LOCK:
        if RUN["active"]:
            return
        todo = []
        for it in ITEMS:
            if item_ids is not None and it["id"] not in item_ids:
                continue
            if it["status"] in ("ready", "done", "stopped", "failed", "skipped") \
                    and wanted(it) and it["ref"]:
                it["status"] = "queued"
                it["error"] = None
                todo.append(it["id"])
        if not todo:
            return
        RUN.update(active=True, stop=False, paused=False, queue=todo, results=[],
                   started=time.time(), error=None, item=None, steps=[])
        PAUSE.set()
    threading.Thread(target=_worker, daemon=True).start()


def start_project(pid, redo=False):
    """Make a finished recording's videos again (after editing its screens)."""
    p = load_project(pid)
    if not p or not Path(p["source"]).exists():
        raise ValueError("The recording for this one has been moved or deleted.")
    it = None
    for x in ITEMS:
        if Path(x["path"]).resolve() == Path(p["source"]).resolve():
            it = x
    if it is None:
        it = add_paths([p["source"]])[0]
    it["ref"] = p["ref"]
    it["options"] = dict(p.get("options") or it["options"])
    it["remake"] = True                    # make them again even if they exist
    it["redo"] = bool(redo)
    it["status"] = "ready"
    start([it["id"]])


def pause(on):
    if on:
        PAUSE.clear()
    else:
        PAUSE.set()
        RUN["paused"] = False


def stop():
    RUN["stop"] = True
    PAUSE.set()


def _worker():
    s = settings()
    awake = native.KeepAwake() if s.get("keep_awake") else None
    try:
        if awake:
            awake.__enter__()
        for it_id in list(RUN["queue"]):
            it = item_by_id(it_id)
            if not it or it["status"] != "queued":
                continue
            if RUN["stop"]:
                it["status"] = "stopped"
                continue
            RUN["item"] = it_id
            it["status"] = "working"
            try:
                made = _make(it)
                it["status"] = "done" if made is not None else "skipped"
            except Stopped:
                it["status"] = "stopped"
                for other in ITEMS:
                    if other["status"] == "queued":
                        other["status"] = "stopped"
                break
            except SystemExit as e:
                it["status"], it["error"] = "failed", str(e).strip() or "Something went wrong."
            except Exception as e:
                traceback.print_exc()
                it["status"], it["error"] = "failed", friendly(e)
            finally:
                it.pop("remake", None)
                it.pop("redo", None)
                refresh_done(it)
    finally:
        if awake:
            awake.__exit__(None, None, None)
        RUN.update(active=False, item=None, slide=None, paused=False)


def friendly(e):
    """Turn a computer error into something a person can act on."""
    text = str(e)
    low = text.lower()
    if "model" in low and ("incomplete" in low or "unable to open" in low or "no such" in low):
        return ("The listener didn't download properly. Close the app and open it "
                "again - it will download it again.")
    if isinstance(e, PermissionError) or "permission denied" in low:
        return "The app isn't allowed to save there. Pick another folder in Settings."
    if "no space" in low:
        return "The disk is full. Free up some space and try again."
    return f"Something went wrong ({e.__class__.__name__}: {text})"


def _make(it):
    s = settings()
    apply_look(s)
    src = Path(it["path"])
    ref = it["ref"]
    outs = outputs_for(it, s)
    kinds = [k for k in wanted(it) if k in outs]
    if s.get("skip_done") and not it.get("remake"):
        kinds = [k for k in kinds if not already_made(outs[k])]
    if not kinds:
        RUN["results"].append({"id": it["id"], "skipped": True})
        return None
    if "bg" in kinds and not s.get("bg_file"):
        raise SystemExit("Pick a background for MP3s in Settings first.")

    pid = project_id(src)
    proj = load_project(pid)
    reuse = (proj and not it.get("redo") and proj.get("ref") == ref
             and Path(proj.get("source", "")).name == src.name and proj.get("parts"))

    label = {"black": "Making the black video",
             "bg": "Making the video with your background",
             "own": "Making the video with your recording"}
    d = it.get("duration") or q.audio_length(src)
    RUN["steps"] = [
        {"label": "Found your breaths", "state": "todo", "cost": 1},
        {"label": "Listened, one breath at a time", "state": "todo",
         "cost": 0 if reuse else _estimate(it) - len(kinds) * RATE["render"] * d},
        {"label": "Matched it to the mushaf", "state": "todo", "cost": 0.5},
        {"label": "Matched the English to each screen", "state": "todo", "cost": 0.5},
    ] + [{"label": label[k], "state": "todo", "cost": RATE["render"] * d, "kind": k}
         for k in kinds]
    _check()

    ar, en, counts = quran()
    ayahs = [(ref["surah"], a) for a in range(ref["first"], ref["last"] + 1)]
    total = q.audio_length(src)

    if reuse:
        parts = proj["parts"]
        for i, txt in ((0, "using your saved screens"), (1, "already done"),
                       (2, f"{sum(1 for x in screens(proj) if x['repeat'])} repeats"),
                       (3, f"{len(parts)} screens")):
            _step(i, "done", txt)
        db = None
        wave = proj.get("wave") or []
        doubts = proj.get("doubts") or []
    else:
        _step(0, "now")
        db = q.loudness(src)
        begin, finish = q.speech_bounds(db, total)
        breaths = q.strong_breaths(db, begin, finish)
        _step(0, "done", f"{len(breaths)} breaths")
        _step(1, "now", None, 0.0)
        _check()
        info = {}
        t0 = time.time()

        def heard_progress(f):
            _step(1, "now", None, f)
            _check()

        parts = None
        if listen.available():
            parts = q.build_parts_heard(src, ayahs, ar, en, db, total,
                                        info=info, progress=heard_progress)
        if parts is None:                    # no listener: cut at the stop marks
            pauses = sorted(q.find_pauses(src), key=lambda p: p[0])
            spans = q.plan_timings(begin, finish, ayahs, ar, pauses)
            parts = q.build_parts(ayahs, ar, en, spans, db)
        took = time.time() - t0
        if took > 5:
            RATE["listen"] = 0.5 * RATE["listen"] + 0.5 * took / max(1.0, total)
        words = len(info.get("heard") or [])
        _step(1, "done", f"{words} words heard" if words else "split at the stop marks")
        parts = [{k: v for k, v in p.items() if k in
                  ("start", "ayah", "lo", "hi", "arabic", "english")} for p in parts]
        parts = sorted(parts, key=lambda p: p["start"])
        parts[0]["start"] = 0.0
        if info.get("heard") is not None:
            word_times(parts, info["heard"], info["where"], total)
        doubts = [{"t": t, "msg": m, "ok": False} for t, m in (info.get("doubts") or [])]
        wave = waveform(db)
        tmp = {"parts": parts, "duration": total}
        reps = sum(1 for x in screens(tmp) if x["repeat"])
        _step(2, "done", f"{reps} repeat{'s' if reps != 1 else ''} found" if reps else "no repeats")
        _step(3, "done", f"{len(parts)} screens")

    proj = {"id": pid, "name": src.stem, "source": str(src), "kind": it["kind"],
            "ref": ref, "duration": total, "options": dict(it["options"]),
            "parts": parts, "doubts": doubts, "wave": wave,
            "size": list(output_size(*it["size"])) if it.get("size") else None,
            "outputs": (proj or {}).get("outputs", {}) if reuse else {},
            "created": (proj or {}).get("created", time.time())}
    save_project(proj)

    # draw every screen, once per video shape
    settled = q.settle_parts([dict(p) for p in parts], total)
    spans = [(p["start"], p["end"]) for p in settled]
    work = Path(tempfile.mkdtemp(prefix="qvm-", dir=paths.WORK))
    slides_for = {}

    def slides(size):
        if size not in slides_for:
            folder = work / f"{size[0]}x{size[1]}"
            folder.mkdir()
            files = []
            for i, p in enumerate(settled):
                _check()
                f = folder / f"{i:03d}.png"
                q.render_slide(p["arabic"], p["english"], size).save(f)
                files.append(f)
            slides_for[size] = files
        return slides_for[size]

    Path(s["out_dir"]).mkdir(parents=True, exist_ok=True)
    try:
        for n, kind in enumerate(kinds):
            i = 4 + n
            _step(i, "now", None, 0.0)
            size = (1920, 1080)
            background = None
            if kind == "bg":
                background = q.seamless_loop(Path(s["bg_file"]))
                q.BACKGROUND_BLUR = int(s.get("bg_blur") or 0)
            elif kind == "own":
                size = tuple(proj["size"]) if proj.get("size") else (1920, 1080)
                background = src                     # your video, just as it is
                q.BACKGROUND_BLUR = 0
            files = slides(size)
            t0 = time.time()

            def on_progress(f, i=i, files=files):
                _step(i, "now", f"{int(f * 100)}%", f)
                at = f * total
                k = max(0, sum(1 for a, _ in spans if a <= at) - 1)
                RUN["slide"] = media_url(files[min(k, len(files) - 1)])

            try:
                q.build(src, files, spans, outs[kind], background=background,
                        progress=on_progress, cancel=lambda: RUN["stop"], size=size)
            except SystemExit:
                if RUN["stop"]:
                    raise Stopped()
                raise
            finally:
                q.BACKGROUND_BLUR = 0
            took = time.time() - t0
            RATE["render"] = 0.5 * RATE["render"] + 0.5 * took / max(1.0, total)
            proj["outputs"][kind] = str(outs[kind])
            for old in paths.THUMBS.glob(f"{pid}_{kind}*"):
                old.unlink(missing_ok=True)
            frame_of(outs[kind], min(total / 2, total - 0.5), f"{pid}_{kind}_{int(time.time())}.jpg", 320)
            save_project(proj)
            _step(i, "done", "done")
            _check()
    finally:
        shutil.rmtree(work, ignore_errors=True)
        RUN["slide"] = None
    RUN["results"].append({"id": it["id"], "project": pid})
    return proj


# ------------------------------------------------------------- what the UI sees
def item_view(it):
    d = {k: it.get(k) for k in ("id", "name", "kind", "ref", "duration", "status", "error",
                                "options", "made", "size", "thumb")}
    d["outputs"] = {k: str(v) for k, v in outputs_for(it).items()}
    return d


def project_summary(p):
    sc = screens(p)
    thumbs = {}
    for kind in ("bg", "own", "black"):
        hits = sorted(paths.THUMBS.glob(f"{p['id']}_{kind}_*.jpg"))
        if hits:
            thumbs[kind] = media_url(hits[-1])
    outs = {k: v for k, v in (p.get("outputs") or {}).items() if v and Path(v).exists()}
    return {"id": p["id"], "name": p["name"], "label": p["ref"]["label"],
            "kind": p.get("kind"), "screens": len(sc),
            "repeats": sum(1 for x in sc if x["repeat"]),
            "doubts": [d for d in p.get("doubts", []) if not d.get("ok")],
            "outputs": outs, "thumbs": thumbs, "updated": p.get("updated", 0),
            "duration": p["duration"]}


def all_projects():
    out = []
    for f in paths.PROJECTS.glob("*.json"):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
            out.append(project_summary(p))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(out, key=lambda x: -x["updated"])


def project_view(pid):
    p = load_project(pid)
    if not p:
        raise ValueError("That recording isn't here any more.")
    v = project_summary(p)
    v["parts"] = screens(p)
    v["wave"] = p.get("wave") or []
    v["videos"] = {k: media_url(path) for k, path in v["outputs"].items()}
    v["paths"] = v["outputs"]
    v["source_ok"] = Path(p["source"]).exists()
    v["size"] = p.get("size") or [1920, 1080]
    return v


def save_screens(pid, parts):
    p = load_project(pid)
    clean = []
    for part in parts:
        c = {k: part[k] for k in ("start", "ayah", "arabic", "english") if k in part}
        for k in ("lo", "hi", "times", "custom"):
            if k in part and part[k] is not None:
                c[k] = part[k]
        c["start"] = round(float(c["start"]), 2)
        clean.append(c)
    clean.sort(key=lambda x: x["start"])
    clean[0]["start"] = 0.0
    p["parts"] = clean
    save_project(p)
    return project_view(pid)


def dismiss_doubt(pid, t):
    p = load_project(pid)
    for d in p.get("doubts", []):
        if abs(d["t"] - float(t)) < 0.01:
            d["ok"] = True
    save_project(p)


def screen_picture(pid, arabic, english, kind):
    p = load_project(pid)
    under, size = None, (1920, 1080)
    if kind == "bg":
        under = bg_still()
    elif kind == "own" and p:
        size = tuple(p.get("size") or (1920, 1080))
        under = frame_of(p["source"], 1.0, f"_src_{p['id']}.jpg", 960)
    return picture(arabic, english, under=under, size=size)


def state():
    s = settings()
    return {
        "version": paths.VERSION,
        "setup": {"ready": model_ready(), **SETUP},
        "settings": {**s, "bg_url": media_url(bg_still()) if s.get("bg_file") else None},
        "items": [item_view(it) for it in ITEMS],
        "run": {k: RUN[k] for k in ("active", "paused", "item", "steps", "overall", "eta",
                                    "slide", "queue", "results", "started")},
        "platform": sys.platform,
    }
