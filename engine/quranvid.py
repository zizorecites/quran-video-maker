#!/usr/bin/env python3
"""
Quran video maker.

Give it an audio file. It works out the surah and ayahs from the file name,
finds where each ayah starts by listening for your pauses, puts the Madani
Arabic and the English on screen, and saves two videos:

    <Name>_guess.mp4   black background      (Guess the Surah)
    <Name>.mp4         your blurred video    (zizorecites)

    python3 quranvid.py ../publishable/Qadr.mp3

Everything runs on this computer. Nothing is uploaded.
"""

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, features
except ImportError:
    sys.exit("\n  The Python imaging library is missing.\n"
             "  Double-click setup.command in this folder, then try again.\n")

import arabic_text          # our own Arabic drawing, sits next to this file

# Arabic letters change shape depending on their neighbours. Pillow does this
# itself when it is built with raqm; if it is not, these two small packages do
# the same job.
SHAPING_BUILT_IN = features.check("raqm")
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAVE_RESHAPER = True
except ImportError:
    HAVE_RESHAPER = False

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
FONTS = ROOT / "fonts"
BACKGROUND_DIR = ROOT / "background"
TIMINGS_DIR = ROOT / "timings"
QURAN_DIR = ROOT.parent
OUT_DIR = QURAN_DIR / "videos"

# ---------------------------------------------------------------- look & feel
W, H = 1920, 1080
FPS = 30

# The real Madani mushaf typeface, from the King Fahd Glorious Quran Printing
# Complex. Swapping this for another Arabic font will change how the letters
# and the ayah markers are drawn - see MUSHAF_FONT below.
ARABIC_FONT = FONTS / "UthmanicHafs-v18.ttf"
MUSHAF_FONT = True          # True when ARABIC_FONT is the King Fahd Complex one
ENGLISH_FONT = FONTS / "Montserrat.ttf"
ENGLISH_WEIGHT = "SemiBold"

ARABIC_SIZE = 118
ENGLISH_SIZE = 56
ARABIC_LINE_GAP = 1.45      # line height, as a multiple of font size
ENGLISH_LINE_GAP = 1.40
GAP_BETWEEN = 95            # pixels between the Arabic block and the English block
BLOCK_CENTER = 0.47         # where the middle of the text sits, 0 = top, 1 = bottom
MAX_BLOCK_HEIGHT = 0.86     # most of the screen height the text may fill
ARABIC_MAX_W = 0.88         # share of the screen width the text may use
ENGLISH_MAX_W = 0.80
TEXT_COLOR = (255, 255, 255, 255)
SHADOW = True               # soft dark glow behind the text so it reads over video
SHADOW_BLUR = 10
SHADOW_ALPHA = 165
BACKGROUND_BLUR = 0         # raise to about 12 if you ever drop in a sharp video
FADE = 0.25                 # seconds each ayah takes to fade in, and to fade out

# -------------------------------------------------------------- pause hunting
PAUSE_MIN = 0.22            # a dip must last this long to count as a pause
PAUSE_ABOVE_FLOOR = 9.0     # how far above the quietest level still counts as a pause

SURAHS = [
    "Al-Fatihah", "Al-Baqarah", "Ali 'Imran", "An-Nisa", "Al-Ma'idah",
    "Al-An'am", "Al-A'raf", "Al-Anfal", "At-Tawbah", "Yunus",
    "Hud", "Yusuf", "Ar-Ra'd", "Ibrahim", "Al-Hijr",
    "An-Nahl", "Al-Isra", "Al-Kahf", "Maryam", "Taha",
    "Al-Anbiya", "Al-Hajj", "Al-Mu'minun", "An-Nur", "Al-Furqan",
    "Ash-Shu'ara", "An-Naml", "Al-Qasas", "Al-'Ankabut", "Ar-Rum",
    "Luqman", "As-Sajdah", "Al-Ahzab", "Saba", "Fatir",
    "Ya-Sin", "As-Saffat", "Sad", "Az-Zumar", "Ghafir",
    "Fussilat", "Ash-Shura", "Az-Zukhruf", "Ad-Dukhan", "Al-Jathiyah",
    "Al-Ahqaf", "Muhammad", "Al-Fath", "Al-Hujurat", "Qaf",
    "Adh-Dhariyat", "At-Tur", "An-Najm", "Al-Qamar", "Ar-Rahman",
    "Al-Waqi'ah", "Al-Hadid", "Al-Mujadila", "Al-Hashr", "Al-Mumtahanah",
    "As-Saff", "Al-Jumu'ah", "Al-Munafiqun", "At-Taghabun", "At-Talaq",
    "At-Tahrim", "Al-Mulk", "Al-Qalam", "Al-Haqqah", "Al-Ma'arij",
    "Nuh", "Al-Jinn", "Al-Muzzammil", "Al-Muddaththir", "Al-Qiyamah",
    "Al-Insan", "Al-Mursalat", "An-Naba", "An-Nazi'at", "'Abasa",
    "At-Takwir", "Al-Infitar", "Al-Mutaffifin", "Al-Inshiqaq", "Al-Buruj",
    "At-Tariq", "Al-A'la", "Al-Ghashiyah", "Al-Fajr", "Al-Balad",
    "Ash-Shams", "Al-Layl", "Ad-Duha", "Ash-Sharh", "At-Tin",
    "Al-'Alaq", "Al-Qadr", "Al-Bayyinah", "Az-Zalzalah", "Al-'Adiyat",
    "Al-Qari'ah", "At-Takathur", "Al-'Asr", "Al-Humazah", "Al-Fil",
    "Quraysh", "Al-Ma'un", "Al-Kawthar", "Al-Kafirun", "An-Nasr",
    "Al-Masad", "Al-Ikhlas", "Al-Falaq", "An-Nas",
]

ARTICLES = ("al", "ar", "as", "ash", "at", "ad", "adh", "az", "an")
EXTRA_NAMES = {"ayatulkursi": (2, 255, 255), "kursi": (2, 255, 255)}


def die(msg):
    print("\n  " + msg + "\n", file=sys.stderr)
    sys.exit(1)


# The app brings its own copy of ffmpeg and points these at it.
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
# How the video is squeezed down. The app can swap this if libx264 is missing.
VIDEO_CODEC = ["-c:v", "libx264", "-preset", "fast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-profile:v", "high"]


def tool(cmd):
    """Swap "ffmpeg" / "ffprobe" for the copy we were told to use."""
    first = {"ffmpeg": FFMPEG, "ffprobe": FFPROBE}.get(cmd[0], cmd[0])
    return [first] + list(cmd[1:])


# On Windows every ffmpeg run would flash a black console window; this hides it.
HIDDEN = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


def run(cmd, **kw):
    kw.update(HIDDEN)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "replace")
    return subprocess.run(tool(cmd), capture_output=True, text=True, **kw)


# ------------------------------------------------------------------ surah ids
def squash(name):
    return re.sub(r"[^a-z]", "", name.lower())


def name_keys(name):
    """Every spelling a surah might be typed as."""
    flat = squash(name)
    keys = {flat}
    for art in ARTICLES:
        if flat.startswith(art) and len(flat) > len(art) + 2:
            keys.add(flat[len(art):])
    return keys


SURAH_LOOKUP = {}
for i, nm in enumerate(SURAHS, start=1):
    for k in name_keys(nm):
        SURAH_LOOKUP.setdefault(k, i)


def find_surah(text):
    flat = squash(text)
    if flat in SURAH_LOOKUP:
        return SURAH_LOOKUP[flat]
    for k in name_keys(text):
        if k in SURAH_LOOKUP:
            return SURAH_LOOKUP[k]
    return None


def parse_reference(stem):
    """'Baqarah260-261' -> (2, 260, 261).  'Qadr' -> (97, None, None)."""
    flat = squash(stem)
    if flat in EXTRA_NAMES:
        return EXTRA_NAMES[flat]

    m = re.match(r"^\s*(\d+)\s*[:.\s]\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*$", stem)
    if m:
        s, a, b = int(m.group(1)), int(m.group(2)), m.group(3)
        return s, a, int(b) if b else a

    m = re.match(r"^(.*?)[\s_-]*(\d+)(?:\s*[-–]\s*(\d+))?\s*$", stem)
    if m and find_surah(m.group(1)):
        s = find_surah(m.group(1))
        a = int(m.group(2))
        b = int(m.group(3)) if m.group(3) else a
        return s, a, b

    s = find_surah(stem)
    if s:
        return s, None, None
    return None, None, None


# -------------------------------------------------------------- the quran text
def load_quran():
    try:
        ar = json.loads((DATA / "arabic.json").read_text(encoding="utf-8"))["quran"]
        en = json.loads((DATA / "english.json").read_text(encoding="utf-8"))["quran"]
    except FileNotFoundError:
        die("The Quran text is missing from maker/data/. Ask Claude to put it back.")
    arabic, english, counts = {}, {}, {}
    for row in ar:
        key = (row["chapter"], row["verse"])
        arabic[key] = row["text"]
        counts[row["chapter"]] = max(counts.get(row["chapter"], 0), row["verse"])
    for row in en:
        english[(row["chapter"], row["verse"])] = row["text"]
    return arabic, english, counts


SAFE_EXTRA = set("“”‘’—…àâäãåçéèêëîïíìôöòóõûüùúñ"
                 "ÀÂÄÃÅÇÉÈÊËÎÏÍÌÔÖÒÓÕÛÜÙÚÑ")


def clean_english(text):
    """Drop the ˹added word˺ brackets and any letter the English font lacks."""
    text = text.replace("˹", "").replace("˺", "")
    text = text.replace(" ", " ")
    out = []
    for ch in text:
        if ch.isascii() or ch in SAFE_EXTRA:
            out.append(ch)
            continue
        plain = "".join(c for c in unicodedata.normalize("NFKD", ch)
                        if not unicodedata.combining(c))
        out.append("".join(c for c in plain if c.isascii() or c in SAFE_EXTRA))
    return re.sub(r"\s+", " ", "".join(out)).strip()


# The text from the Quran Complex had three marks swapped for look-alike
# Unicode ones. Their own font does not know those, so we put them back.
TANWEEN_BACK = {0x08F0: "ٗ", 0x08F1: "ٞ", 0x08F2: "ٖ"}


def join_stray_letters(text):
    """
    In about 100 places the source text puts a space before a word's last
    letter - "سَعۡيٗ ا", "هُدٗ ى" - which would draw as a gap in the middle of
    the word. A lone ا or ى (with any marks on it) is glued back on.
    The opening letters of some surahs, like صٓ and قٓ, really are words on
    their own, so only these two letters are joined.
    """
    out = []
    for token in text.split():
        letters = "".join(c for c in token if unicodedata.category(c) == "Lo")
        if out and letters in ("ا", "ى"):
            out[-1] += token
        else:
            out.append(token)
    return " ".join(out)


def mushaf_arabic(text):
    text = join_stray_letters(text)
    return text.translate(TANWEEN_BACK) if MUSHAF_FONT else text


# ------------------------------------------------------- splitting into parts
# The mushaf prints little symbols above the line showing where a reciter may
# stop. They are exactly the places you pause, so they are where we cut.
WAQF_MARKS = set(range(0x06D6, 0x06DD))
HARAKAT = set(range(0x064B, 0x0653)) | {0x0670, 0x0656, 0x0657, 0x065E,
                                        0x08F0, 0x08F1, 0x08F2}


def split_phrases(text):
    """Break one ayah at its stop marks. No marks means one phrase."""
    phrases, cur = [], []
    for word in text.split():
        cur.append(word)
        if any(ord(c) in WAQF_MARKS for c in word):
            phrases.append(" ".join(cur))
            cur = []
    if cur:
        phrases.append(" ".join(cur))

    merged = []                      # a lone word is not worth its own screen
    for p in phrases:
        if merged and len(p.split()) < 2:
            merged[-1] += " " + p
        else:
            merged.append(p)
    return merged or [text]


def beats(text):
    """
    Roughly how long a piece takes to recite.

    Every letter is one beat. A madd sign stretches a vowel out, so it counts
    for several. This only has to be good enough to tell which pause belongs to
    which stop mark.
    """
    n = 0
    for c in text:
        o = ord(c)
        if o in WAQF_MARKS or o == 0x06DD or 0x0660 <= o <= 0x0669:
            continue
        if o == 0x0653:              # madd sign - a long stretch
            n += 3
        elif o == 0x0651:            # shadda - doubled letter
            n += 1
        elif o in HARAKAT or o == 0x0652:
            continue
        elif not c.isspace():
            n += 1
    return max(1, n)


MIN_DIP_DB = 4.0            # how much quieter a breath has to be to count
MAX_PART_SECONDS = 10.0     # longer than this and we look for another breath
MIN_PART_SECONDS = 1.6      # shorter than this and it is not worth its own screen


def cut_words_at(phrase, fraction):
    """Split a phrase in two at the word nearest the given way through it."""
    words = phrase.split()
    if len(words) < 2:
        return None
    run, cum = 0, []
    for w in words:
        run += beats(w)
        cum.append(run)
    target = run * fraction
    best = min(range(1, len(words)), key=lambda i: abs(cum[i - 1] - target))
    return " ".join(words[:best]), " ".join(words[best:])


SENTENCE_END = re.compile(r'[.!?]["”’\')\]]*\s+')
CLAUSE_END = re.compile(r'[;:—]\s+|,\s+')


def english_atoms(text):
    """Chop the translation at punctuation, strongest breaks first."""
    atoms, last = [], 0
    for m in SENTENCE_END.finditer(text):
        atoms.append((text[last:m.end()].strip(), 3.0))
        last = m.end()
    if last < len(text):
        atoms.append((text[last:].strip(), 3.0))

    out = []
    for piece, rank in atoms:
        start = 0
        for m in CLAUSE_END.finditer(piece):
            out.append((piece[start:m.end()].strip(), 1.5 if m.group().strip() != "," else 0.6))
            start = m.end()
        tail = piece[start:].strip()
        if tail:
            out.append((tail, rank))
    return [a for a in out if a[0]]


def split_english(text, weights):
    """
    Cut the translation into one piece per Arabic phrase.

    Pieces are chosen so each one carries about as much of the English as its
    phrase carries of the Arabic, and so the cuts land on full stops and commas
    rather than mid-sentence.
    """
    n = len(weights)
    if n == 1 or not text:
        return [text] * n
    atoms = english_atoms(text)
    if len(atoms) < n:                              # not enough punctuation
        words = text.split()
        if len(words) < n:
            return [text] + [""] * (n - 1)
        atoms = [(w, 0.0) for w in words]

    lens = [max(1, len(a[0])) for a in atoms]
    cum = [0]
    for L in lens:
        cum.append(cum[-1] + L)
    whole = cum[-1]
    tw = sum(weights)
    target = [w / tw for w in weights]

    INF = float("inf")
    cost = [[INF] * (n + 1) for _ in range(len(atoms) + 1)]
    pick = [[None] * (n + 1) for _ in range(len(atoms) + 1)]
    cost[0][0] = 0.0
    for i in range(1, len(atoms) + 1):
        for k in range(1, min(n, i) + 1):
            for j in range(k - 1, i):
                if cost[j][k - 1] == INF:
                    continue
                share = (cum[i] - cum[j]) / whole
                c = cost[j][k - 1] + abs(share - target[k - 1]) * 10.0
                if i < len(atoms):
                    c -= atoms[i - 1][1] * 0.12     # reward stopping at a full stop
                if c < cost[i][k]:
                    cost[i][k] = c
                    pick[i][k] = j

    if cost[len(atoms)][n] == INF:
        return [text] + [""] * (n - 1)
    cuts, i = [], len(atoms)
    for k in range(n, 0, -1):
        j = pick[i][k]
        cuts.append((j, i))
        i = j
    cuts.reverse()
    return [" ".join(a[0] for a in atoms[j:i]).strip() for j, i in cuts]


def ayah_marker(n):
    """
    The flower-shaped ayah number from the mushaf.

    In the King Fahd Complex font each Arabic digit is already drawn inside the
    flower, so the number on its own is the whole marker. Other Arabic fonts
    need U+06DD in front of it to build one.
    """
    digits = "".join("٠١٢٣٤٥٦٧٨٩"[int(d)]
                     for d in str(n))
    return digits if MUSHAF_FONT else "۝" + digits


# ----------------------------------------------------------------- text layout
_FONTS = {}


def font_at(path, size, weight=None):
    key = (path, size, weight)
    if key not in _FONTS:
        f = ImageFont.truetype(str(path), size)
        if weight:
            try:
                f.set_variation_by_name(weight)
            except Exception:
                pass
        _FONTS[key] = f
    return _FONTS[key]


def check_fonts():
    if not ARABIC_FONT.exists() or not ENGLISH_FONT.exists():
        die("The fonts are missing from maker/fonts/. Ask Claude to put them back.")


def arabic_width(text, size):
    if arabic_text.AVAILABLE:
        return arabic_text.ArabicFont.get(ARABIC_FONT).width(text, size)
    # falling back to Pillow's own shaping
    shown = text if SHAPING_BUILT_IN else (
        get_display(arabic_reshaper.reshape(text)) if HAVE_RESHAPER else text)
    kw = {"direction": "rtl", "language": "ar"} if SHAPING_BUILT_IN else {}
    box = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox(
        (0, 0), shown, font=font_at(ARABIC_FONT, size), **kw)
    return box[2] - box[0]


def greedy_wrap(text, measure, max_w):
    words = []
    for w in text.split():                  # an ayah number never starts a line:
        if words and has_ayah_number(w):    # it stays glued to the word before it
            words[-1] += " " + w
        else:
            words.append(w)
    lines, cur = [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        if cur and measure(trial) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [""]


def wrap(text, measure, max_w):
    """
    Break the text into lines of roughly equal length.

    Plain wrapping fills each line to the edge, which often leaves one short
    word stranded on the last line. So: find how many lines are needed, then
    squeeze the width down as far as it will go while still using that many.
    """
    lines = greedy_wrap(text, measure, max_w)
    if len(lines) < 2:
        return lines
    want = len(lines)
    low, high = 0.0, max_w                 # high always fits in `want` lines
    for _ in range(14):
        mid = (low + high) / 2
        if len(greedy_wrap(text, measure, mid)) <= want:
            high = mid
        else:
            low = mid
    return greedy_wrap(text, measure, high)


def lay_out(draw, arab, eng, size=None):
    """
    Work out the lines and the text size.

    A long ayah needs more lines than a short one. Rather than let it run off
    the screen, the text is stepped down in size until the whole block fits.
    """
    W, H = size or (globals()["W"], globals()["H"])
    scale = 1.0
    while True:
        ar_size = max(44, round(ARABIC_SIZE * scale))
        en_size = max(30, round(ENGLISH_SIZE * scale))
        en_font = font_at(ENGLISH_FONT, en_size, ENGLISH_WEIGHT)

        ar_lines = wrap(arab, lambda s: arabic_width(s, ar_size), W * ARABIC_MAX_W)
        en_lines = wrap(eng, lambda s: draw.textlength(s, font=en_font),
                        W * ENGLISH_MAX_W)

        ar_step = ar_size * ARABIC_LINE_GAP
        en_step = en_size * ENGLISH_LINE_GAP
        total = len(ar_lines) * ar_step + GAP_BETWEEN + len(en_lines) * en_step

        if total <= H * MAX_BLOCK_HEIGHT or scale <= 0.5:
            return ar_lines, en_lines, ar_size, en_font, ar_step, en_step, total
        scale -= 0.04


def render_slide(arab, eng, size=None):
    """One transparent 1920x1080 layer with this part on it (or `size`)."""
    W, H = size or (globals()["W"], globals()["H"])
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    (ar_lines, en_lines, ar_size, en_font,
     ar_step, en_step, total) = lay_out(draw, arab, eng, (W, H))

    y = H * BLOCK_CENTER - total / 2
    y = max(H * (1 - MAX_BLOCK_HEIGHT) / 2, y)

    if arabic_text.AVAILABLE:
        renderer = arabic_text.ArabicFont.get(ARABIC_FONT)
        ascent, _ = arabic_text.ascent_descent(ARABIC_FONT, ar_size)
        for line in ar_lines:
            renderer.draw(img, line, ar_size, W / 2, y + ascent, TEXT_COLOR)
            y += ar_step
    else:
        ar_font = font_at(ARABIC_FONT, ar_size)
        kw = {"direction": "rtl", "language": "ar"} if SHAPING_BUILT_IN else {}
        for line in ar_lines:
            shown = line if SHAPING_BUILT_IN else (
                get_display(arabic_reshaper.reshape(line)) if HAVE_RESHAPER else line)
            draw.text((W / 2, y), shown, font=ar_font, fill=TEXT_COLOR,
                      anchor="ma", **kw)
            y += ar_step

    y += GAP_BETWEEN
    for line in en_lines:
        draw.text((W / 2, y), line, font=en_font, fill=TEXT_COLOR, anchor="ma")
        y += en_step

    if not SHADOW:
        return img
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow.putalpha(img.getchannel("A").point(lambda v: min(255, v * SHADOW_ALPHA // 255))
                  .filter(ImageFilter.GaussianBlur(SHADOW_BLUR)))
    return Image.alpha_composite(glow, img)


# --------------------------------------------------------------------- timing
def audio_length(path):
    path = Path(path)
    if FFPROBE and (shutil.which(FFPROBE) or Path(FFPROBE).exists()):
        out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "csv=p=0", str(path)])
        try:
            return float(out.stdout.strip())
        except ValueError:
            pass
    # no ffprobe: ffmpeg prints "Duration: 00:01:53.73" when it opens a file
    out = run(["ffmpeg", "-hide_banner", "-i", str(path)])
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out.stderr)
    if not m:
        die(f"ffmpeg could not read {path.name}.")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


HOP = 0.02                  # we look at the sound 50 times a second


def loudness(path):
    """How loud the recording is, moment to moment, in decibels."""
    import numpy as np

    raw = subprocess.run(tool(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000",
         "-f", "s16le", "-acodec", "pcm_s16le", "-"]),
        capture_output=True, **HIDDEN).stdout
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size == 0:
        return None
    sr = 8000
    win = int(sr * HOP)
    count = samples.size // win
    if count < 10:
        return None
    rms = np.sqrt((samples[:count * win].reshape(count, win) ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    return np.convolve(db, np.ones(5) / 5, mode="same")   # smooth out spikes


def dip_near(db, want, window, lo_t, hi_t):
    """
    Find the breath nearest to `want`, searching only between lo_t and hi_t.

    A faint, short breath between two phrases is easy to miss if you go looking
    for silence across the whole recording. But we already have a good idea of
    where each stop mark falls, so we look right there, and only have to spot a
    dip relative to the words either side of it.
    """
    import numpy as np

    n = len(db)
    lo = max(0, int(max(lo_t, want - window) / HOP))
    hi = min(n, int(min(hi_t, want + window) / HOP))
    if hi - lo < 4:
        return None
    seg = db[lo:hi]
    k = int(seg.argmin())
    quietest = float(seg[k])

    pad = int(1.5 / HOP)
    around = float(np.percentile(db[max(0, lo - pad):min(n, hi + pad)], 65))
    if around - quietest < MIN_DIP_DB:
        return None

    limit = quietest + min(3.5, (around - quietest) * 0.5)
    a = b = k
    while a > 0 and seg[a - 1] <= limit:
        a -= 1
    while b < len(seg) - 1 and seg[b + 1] <= limit:
        b += 1
    return (lo + (a + b) / 2.0) * HOP


def find_pauses(path):
    """
    Every clear gap in the recording, as (middle, how_long, how_deep).

    Used to tell the ayahs apart. Within an ayah we go looking in a known place
    instead - see dip_near.
    """
    import numpy as np

    db = loudness(path)
    if db is None:
        return []
    count, hop = len(db), HOP
    floor = float(np.percentile(db, 2))
    limit = floor + PAUSE_ABOVE_FLOOR
    quiet = db < limit

    pauses, i = [], 0
    need = int(PAUSE_MIN / hop)
    while i < count:
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j < count and quiet[j]:
            j += 1
        if j - i >= need:
            mid = (i + j) / 2.0 * hop
            depth = limit - float(db[i:j].min())
            pauses.append((mid, (j - i) * hop, depth))
        i = j
    return pauses


def speech_bounds(db, total):
    """When the reciting actually starts and stops, ignoring silence at the ends."""
    import numpy as np
    if db is None:
        return 0.0, total
    loud = db > (float(np.percentile(db, 65)) - 11.0)
    idx = np.flatnonzero(loud)
    if idx.size == 0:
        return 0.0, total
    return (max(0.0, float(idx[0]) * HOP - 0.25),
            min(total, float(idx[-1]) * HOP + 0.5))


def plan_timings(begin, finish, ayahs, arabic, pauses):
    """Work out when each ayah starts. Pauses first, even spacing as backup."""
    n = len(ayahs)
    total = finish - begin
    if n == 1:
        return [(begin, finish)]

    # where each boundary ought to land, if the pace were steady
    weights = [beats(arabic[(a[0], a[1])]) for a in ayahs]
    run_sum, cum = 0, []
    for w in weights:
        run_sum += w
        cum.append(run_sum)
    expected = [begin + total * c / run_sum for c in cum[:-1]]

    # ignore pauses right at the start or the end
    pauses = [p for p in pauses if begin + 0.6 < p[0] < finish - 0.6]

    window = max(3.0, total * 0.18)
    chosen, used, found = [], set(), 0
    for want in expected:
        best, best_cost = None, None
        for i, (mid, length, depth) in enumerate(pauses):
            if i in used or abs(mid - want) > window:
                continue
            # close to where it should be, long, and deep all count in its favour
            cost = abs(mid - want) / window - 0.45 * min(length, 1.2) - 0.02 * depth
            if best_cost is None or cost < best_cost:
                best, best_cost = i, cost
        if best is None:
            chosen.append(want)
        else:
            used.add(best)
            found += 1
            chosen.append(pauses[best][0])
    print(f"  heard {len(pauses)} pause{'s' if len(pauses) != 1 else ''}, "
          f"matched {found} of {len(expected)} ayah change"
          f"{'s' if len(expected) != 1 else ''}")

    chosen = sorted(chosen)
    for i in range(1, len(chosen)):           # never let one overtake the next
        chosen[i] = max(chosen[i], chosen[i - 1] + 0.4)
    chosen = [min(c, finish - 0.4) for c in chosen]

    bounds = [begin] + chosen + [finish]
    return [(bounds[i], bounds[i + 1]) for i in range(n)]


def build_parts(ayahs, arabic, english, spans, db):
    """
    Turn each ayah into the pieces you recite between breaths.

    An ayah is cut at its mushaf stop marks - those are the places a reciter
    stops, and they match where you split by hand. Where a breath can be heard
    near a mark the cut lands on it exactly; otherwise it lands where the pace
    of the recitation says it should. The translation is cut to match, so each
    piece carries its own English.
    """
    parts, snapped, guessed = [], 0, 0
    english_for = EnglishForWords(ayahs, arabic, english)
    first_word = 0
    for (surah, num), (start, end) in zip(ayahs, spans):
        phrases = split_phrases(mushaf_arabic(arabic[(surah, num)]))
        weights = [beats(p) for p in phrases]
        englishes, k = [], first_word
        for p in phrases:
            n = len(p.split())
            englishes.append(english_for(k, k + n - 1))
            k += n
        first_word = k

        run_sum, cum = 0, []
        for w in weights:
            run_sum += w
            cum.append(run_sum)
        expect = [start + (end - start) * c / run_sum for c in cum[:-1]]

        times = []
        for i, want in enumerate(expect):
            before = times[-1] if times else start
            after = expect[i + 1] if i + 1 < len(expect) else end
            window = min(2.5, max(0.8, (after - before) * 0.45))
            found = (dip_near(db, want, window, before + 0.35, after - 0.2)
                     if db is not None else None)
            if found is None:
                times.append(max(want, before + 0.5))
                guessed += 1
            else:
                times.append(max(found, before + 0.5))
                snapped += 1

        starts = [start] + times
        ends = times + [end]
        for g in range(len(phrases)):
            parts.append({
                "ayah": num,
                "part": g + 1,
                "of": len(phrases),
                "last": g == len(phrases) - 1,
                "arabic": phrases[g],
                "english": englishes[g],
                "start": starts[g],
                "end": ends[g],
            })
    parts, extra = split_long_parts(parts, db)
    parts = drop_tiny_parts(parts)
    if snapped or guessed:
        print(f"  {snapped} split{'s' if snapped != 1 else ''} landed on a breath "
              f"I could hear, {guessed} placed by the pace of the reciting")
    if extra:
        print(f"  {extra} more split{'s' if extra != 1 else ''} added where you "
              f"took a breath the mushaf does not mark")
    return parts


def split_long_parts(parts, db):
    """
    Cut up any piece that stays on screen too long.

    The mushaf does not mark a stop in the middle of a long sentence, but you
    still have to breathe. So for a piece that runs long we go looking for the
    clearest breath inside it and cut there too.
    """
    if db is None:
        return parts, 0
    out, added = [], 0
    queue = list(parts)
    while queue:
        p = queue.pop(0)
        span = p["end"] - p["start"]
        if span <= MAX_PART_SECONDS or len(p["arabic"].split()) < 4:
            out.append(p)
            continue
        middle = p["start"] + span / 2
        t = dip_near(db, middle, span * 0.35,
                     p["start"] + MIN_PART_SECONDS, p["end"] - MIN_PART_SECONDS)
        if t is None:
            out.append(p)
            continue
        f = (t - p["start"]) / span
        halves = cut_words_at(p["arabic"], f)
        if halves is None:
            out.append(p)
            continue
        eng = split_english(p["english"], [max(1, beats(halves[0])),
                                           max(1, beats(halves[1]))])
        added += 1
        first = dict(p, arabic=halves[0], english=eng[0], end=t, last=False)
        second = dict(p, arabic=halves[1], english=eng[1], start=t)
        queue.insert(0, second)
        queue.insert(0, first)
        if len(out) + len(queue) > 400:          # safety net, never hit in practice
            break
    return renumber(out), added


def drop_tiny_parts(parts):
    """A piece too short to read gets folded into the one before it."""
    out = []
    for p in parts:
        too_short = p["end"] - p["start"] < MIN_PART_SECONDS
        if too_short and out and out[-1]["ayah"] == p["ayah"]:
            out[-1]["arabic"] += " " + p["arabic"]
            out[-1]["english"] = (out[-1]["english"] + " " + p["english"]).strip()
            out[-1]["end"] = p["end"]
            out[-1]["last"] = p["last"]
        elif too_short and out:
            out[-1]["end"] = p["start"] = max(p["start"] - MIN_PART_SECONDS,
                                              out[-1]["start"] + MIN_PART_SECONDS)
            out.append(p)
        else:
            out.append(p)
    return renumber(out)


# ------------------------------------------------------- splitting by listening
BREATH_DB = 10.0            # a real breath drops at least this far
BREATH_QUIET = 0.40         # and stays quiet at least this long (seconds)
STOP_MARK_DB = 7.0          # at a mushaf stop mark, a lighter breath is enough


def has_stop_mark(word):
    return any(ord(c) in WAQF_MARKS for c in word)


def dip_at(db, t, window):
    """The quietest moment near t: (middle of the quiet, how deep, how long)."""
    import numpy as np
    n = len(db)
    lo, hi = max(0, int((t - window) / HOP)), min(n, int((t + window) / HOP))
    if hi - lo < 3:
        return None
    i = lo + int(db[lo:hi].argmin())
    look = int(1.5 / HOP)
    depth = float(np.percentile(db[max(0, i - look):min(n, i + look)], 65)) - float(db[i])
    limit = db[i] + depth * 0.75
    a = b = i
    while a > 0 and db[a - 1] <= limit:
        a -= 1
    while b < n - 1 and db[b + 1] <= limit:
        b += 1
    return (a + b) / 2.0 * HOP, depth, (b - a + 1) * HOP


def strong_breaths(db, begin, finish):
    """
    Every clear breath in the recording.

    A breath is both deep and long. A dip inside a word can be just as deep,
    but it is over in a moment, so asking for both keeps only the real ones.
    """
    import numpy as np
    n = len(db)
    look, half = int(1.5 / HOP), int(0.2 / HOP)
    found = []
    for i in range(half, n - half):
        t = i * HOP
        if not (begin + 0.6 < t < finish - 0.6):
            continue
        if db[i] != db[i - half:i + half + 1].min():
            continue
        depth = float(np.percentile(db[max(0, i - look):min(n, i + look)], 65)) - float(db[i])
        if depth < BREATH_DB:
            continue
        limit = db[i] + depth * 0.75
        a = b = i
        while a > 0 and db[a - 1] <= limit:
            a -= 1
        while b < n - 1 and db[b + 1] <= limit:
            b += 1
        if (b - a + 1) * HOP >= BREATH_QUIET:
            found.append(((a + b) / 2.0 * HOP, depth))
    found.sort(key=lambda x: -x[1])
    keep = []
    for t, _ in found:
        if all(abs(t - k) >= 1.0 for k in keep):
            keep.append(t)
    return sorted(keep)


def voice_check(db):
    """A test for 'is someone reciting between these two times?'"""
    import numpy as np
    if db is None:
        return None
    quiet, loud = float(np.percentile(db, 25)), float(np.percentile(db, 75))
    level = quiet + 0.5 * (loud - quiet)

    def has_voice(start, end):
        seg = db[int(start / HOP):int(end / HOP)]
        return len(seg) > 0 and float((seg > level).sum()) * HOP >= 0.6
    return has_voice


class EnglishForWords:
    """
    The English for any run of Arabic words, even across ayahs.

    Each ayah gets its own map from Arabic words to the words of the
    translation (see english_map.py). A part that spans two ayahs gets the
    end of one and the start of the next.
    """

    def __init__(self, ayahs, arabic, english):
        import english_map
        self.join = english_map.join_ayahs
        self.maps, self.where = {}, []
        for key in ayahs:
            words = mushaf_arabic(arabic[key]).split()
            self.maps[key[1]] = english_map.AyahMap(
                key[0], key[1], words, clean_english(english.get(key, "")))
            self.where.extend((key[1], k) for k in range(len(words)))

    def gap_quality(self, k):
        """How good a place the gap before word k is to break the English."""
        if k <= 0 or k >= len(self.where):
            return 3.0
        ayah, x = self.where[k]
        return self.maps[ayah].gap_quality(x)

    def __call__(self, lo, hi):
        lo, hi = max(0, lo), min(hi, len(self.where) - 1)
        texts, k = [], lo
        while k <= hi:
            ayah, x0 = self.where[k]
            end = k
            while end + 1 <= hi and self.where[end + 1][0] == ayah:
                end += 1
            texts.append(self.maps[ayah].between(x0, self.where[end][1] + 1))
            k = end + 1
        return self.join(texts)


def cut_between_words(s, e, heard, where, text, db, english_for):
    """
    Where to split a long stretch said in one breath: (time, k), where heard
    word k is the first one after the cut.

    There is no breath to cut at, so cut between two words. The quiet moment
    in the middle of a word (before a letter like ك) is no good: the next
    screen would show up late, halfway through the word.

    Every gap between two words said one after the other gets points for:
    a stop mark in the mushaf, a clean break in the English (a full stop or a
    comma), a little dip in the sound - and loses points the further it is
    from the middle. The screen changes just before the next word starts.
    """
    said = [(k, h, j) for k, (h, j) in enumerate(zip(heard, where))
            if j is not None and s <= (h["start"] + h["end"]) / 2 < e]
    middle, best = (s + e) / 2, None
    for (_, h1, j1), (k2, h2, j2) in zip(said, said[1:]):
        if j2 != j1 + 1:
            continue                       # not two words in a row
        t0 = h2["start"]
        edge = max(MIN_PART_SECONDS, 0.3 * (e - s))    # no tiny screen either side
        if not (s + edge <= t0 <= e - edge):
            continue
        score = english_for.gap_quality(j2)
        if score is None:
            # an ayah the translator rebuilt as a whole: both screens would
            # show the same English, so only split it if it's really long
            if e - s < 1.5 * MAX_PART_SECONDS:
                continue
            score = 0.0
        if has_stop_mark(text[j1][1]):
            score += 3.0
        found = dip_at(db, t0, 0.25)
        when = t0
        if found:
            score += min(found[1], 15.0) / 15.0      # a small say only: inside one
            if t0 - 0.3 <= found[0] < t0:           # breath, dips are mostly letters
                when = found[0]            # the gap is a little before Whisper's guess
        score -= 3.0 * abs(t0 - middle) / (e - s)
        when = max(h1["start"] + 0.1, when - 0.1)   # a moment early, never late
        if best is None or score > best[0]:
            best = (score, when, k2)
    return best[1:] if best else None     # (when, the first heard word after it)


def build_parts_heard(audio, ayahs, arabic, english, db, total, fresh=False,
                      info=None, progress=None):
    """
    Split the recitation where you breathe, and show what you actually said.

    1. Listen, and line up every heard word with the mushaf text - repeats too.
    2. Cut the recording at each clear breath (and at a lighter breath, if a
       stretch would otherwise stay on screen too long).
    3. Each stretch shows exactly the words heard in it.
    """
    import listen

    begin, finish = speech_bounds(db, total)
    cuts = strong_breaths(db, begin, finish)

    heard = listen.transcribe(audio, fresh=fresh, has_voice=voice_check(db),
                              breaths=list(cuts), total=total, progress=progress)
    text = []                                   # (ayah, word) for the whole range
    for key in ayahs:
        for w in mushaf_arabic(arabic[key]).split():
            text.append((key[1], w))
    where = listen.align(heard, [w for _, w in text])
    english_for = EnglishForWords(ayahs, arabic, english)

    # Where a word carries a stop mark, a lighter breath after it counts too.
    # It still has to last a moment: the silent instant before a hard letter
    # like ق is just as deep, but it is over almost at once.
    for h, j in zip(heard, where):
        if j is None or not has_stop_mark(text[j][1]):
            continue
        found = dip_at(db, h["end"], 0.7)
        if not found:
            continue
        t, depth, quiet = found
        if (depth >= STOP_MARK_DB and quiet >= BREATH_QUIET
                and begin + 0.6 < t < finish - 0.6
                and all(abs(t - c) >= 1.0 for c in cuts)):
            cuts.append(t)
    cuts.sort()

    # A stretch that is still too long gets cut between two words - the best
    # place to break it, near the middle (see cut_between_words).
    edges = [0.0] + cuts + [total]
    word_cuts = {}                  # cut time -> first heard word after it
    i = 0
    while i < len(edges) - 1:
        s, e = edges[i], edges[i + 1]
        if e - s > MAX_PART_SECONDS:
            found = cut_between_words(s, e, heard, where, text, db, english_for)
            heard_here = sum(1 for h, j in zip(heard, where)
                             if j is not None and s <= h["start"] < e)
            if found:
                t, word_cuts[found[0]] = found
            elif heard_here < 2:      # hardly any words heard: go by the sound
                t = dip_near(db, (s + e) / 2, (e - s) * 0.35,
                             s + MIN_PART_SECONDS, e - MIN_PART_SECONDS)
            else:
                t = None
            if t is not None:
                edges.insert(i + 1, t)
                continue
        i += 1

    # Which stretch each heard word belongs to. Most words sit plainly between
    # two breaths. But Whisper stretches words over the silence next to them -
    # sometimes the word before a breath, sometimes the one after - so a word
    # can seem to span a breath. Then the mushaf decides: a word with a stop
    # mark comes before the breath, a word right after a stop mark comes after
    # it, and so does the first word of a repeat.
    groups = [[] for _ in range(len(edges) - 1)]
    last_j = -1
    for k, (h, j) in enumerate(zip(heard, where)):
        if j is None:
            continue
        t = (h["start"] + h["end"]) / 2
        inside = [e for e in edges[1:-1] if h["start"] + 0.05 < e < h["end"] - 0.05]
        # a cut made between two words already knows which side each is on
        for e, first_after in word_cuts.items():
            if k < first_after and t >= e:
                t = e - 0.01
            elif k >= first_after and t < e:
                t = e + 0.01
        if any(e in word_cuts for e in inside):
            pass
        elif inside:
            e = inside[0]
            # Only a word that ends a phrase - it has a stop mark, or it is the
            # last word of its ayah - belongs before the breath (unless it starts
            # a repeat). Everything else goes after it.
            ends_ayah = j == len(text) - 1 or text[j + 1][0] != text[j][0]
            before = (has_stop_mark(text[j][1]) or ends_ayah) and j > last_j
            t = e - 0.01 if before else e + 0.01
        last_j = j
        for g in range(len(edges) - 1):
            if edges[g] <= t < edges[g + 1] or (g == len(edges) - 2 and t >= edges[g]):
                groups[g].append(j)
                if h.get("two"):
                    groups[g].append(j - 1)      # it was this word and the one before
                break

    # stretches with nothing heard in them, or too short to read, join the one before
    spans = []
    for g, js in enumerate(groups):
        start = edges[g]
        if not js:
            continue
        if spans and edges[g + 1] - start < MIN_PART_SECONDS:
            spans[-1][2] = max(spans[-1][2], max(js))
            continue
        spans.append([start, min(js), max(js)])
    if not spans:
        return None
    spans[0][0] = 0.0

    # words nobody heard still get shown: they go with the next part
    reach = -1
    for sp in spans:
        if sp[1] > reach + 1:
            sp[1] = reach + 1
        reach = max(reach, sp[2])
    spans[-1][2] = len(text) - 1

    finals = {}
    for k, (ay, _) in enumerate(text):
        finals[ay] = k                           # index of each ayah's last word

    parts, borrowed = [], []
    for n, (start, lo, hi) in enumerate(spans):
        shown = []
        for k in range(lo, hi + 1):
            shown.append(text[k][1])
            if finals[text[k][0]] == k:          # end of an ayah: its number
                shown.append(ayah_marker(text[k][0]))
        eng = english_for(lo, hi)
        if not eng.strip():
            # The English put these words' meaning somewhere else (يُحَاسِبۡكُم
            # بِهِ ٱللَّهُ is "Allah will call you to account for it"). Rather than
            # a blank screen, show the English of this part and its neighbour.
            if n > 0:
                eng = english_for(spans[n - 1][1], hi)
            elif n + 1 < len(spans):
                eng = english_for(lo, spans[n + 1][2])
            borrowed.append(start)
        parts.append({"ayah": text[hi][0], "start": start, "lo": lo, "hi": hi,
                      "arabic": " ".join(shown), "english": eng})

    repeats = sum(1 for a, b in zip(spans, spans[1:]) if b[1] <= a[2])
    print(f"  listened: {len(heard)} words heard, {len(cuts)} clear breaths, "
          f"{len(parts)} parts" + (f", {repeats} repeat{'s' if repeats != 1 else ''} found"
                                  if repeats else ""))
    notes = report_doubts(heard, where, text, parts, borrowed)
    if info is not None:          # the app keeps these for its screen editor
        info.update(heard=heard, where=where, text=text, doubts=notes,
                    english_for=english_for, finals=finals)
    return parts


# things Whisper writes into silence that nobody said
MADE_UP = {"اشتركوا", "القناة", "شكرا", "لكم", "للمشاهدة", "موسيقى", "ترجمة", "نانسي", "قنقر"}


def clock(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def report_doubts(heard, where, text, parts, borrowed):
    """
    Say what is worth a look, so you don't have to watch every video.

    - two or more words in a row that were never heard: they are still on
      screen (with the next part), but their timing is a guess
    - a word heard clearly that isn't in these ayahs at all
    - a screen whose English had to be shared with the one before it
    """
    import listen
    notes = []
    got = {j for j in where if j is not None}
    got |= {j - 1 for h, j in zip(heard, where) if j is not None and h.get("two")}
    k = 0
    while k < len(text):
        if k in got:
            k += 1
            continue
        run = k
        while run < len(text) and run not in got:
            run += 1
        if run - k >= 2:
            after = [h["start"] for h, j in zip(heard, where) if j is not None and j >= run]
            at = min(after) if after else (heard[-1]["end"] if heard else 0.0)
            notes.append((at, "couldn't hear " + " ".join(w for _, w in text[k:run])))
        k = run
    for k, (h, j) in enumerate(zip(heard, where)):
        word = listen.plain(h["word"])
        if not (j is None and h["sure"] >= 0.75 and len(word) >= 3
                and word not in MADE_UP and len(set(word)) > 1):
            continue
        # a piece of a word Whisper split in two ("ليسجنوا النهو" for
        # لَيَسۡجُنُنَّهُۥ) sits between two words that follow on from each other
        before = next((x for x in reversed(where[:k]) if x is not None), None)
        after = next((x for x in where[k + 1:] if x is not None), None)
        if before is not None and after is not None and after - before in (0, 1):
            continue
        notes.append((h["start"], f"heard \"{h['word']}\", which isn't in these ayahs"))
    for at in borrowed:
        notes.append((at, "this screen shares its English with the one before"))
    if not notes:
        print("  check: nothing looked doubtful")
        return []
    print("  check these:")
    for at, what in sorted(notes):
        print(f"    {clock(at)}  {what}")
    return sorted(notes)


def has_ayah_number(text):
    return any("٠" <= c <= "٩" for c in text)


def listening_ready():
    try:
        import listen
        return listen.available()
    except Exception:
        return False


def settle_parts(parts, total):
    """
    Fill in everything that can be worked out from the list itself.

    Each part ends when the next one starts, and the last one ends with the
    audio. The ayah number goes on the last part of each ayah. So in the saved
    file you only ever need to touch "start", and adding or removing a part
    never means renumbering anything.
    """
    parts = sorted(parts, key=lambda p: float(p["start"]))
    for i, p in enumerate(parts):
        p["start"] = 0.0 if i == 0 else float(p["start"])
        p["end"] = float(parts[i + 1]["start"]) if i + 1 < len(parts) else total
    for i, p in enumerate(parts):
        nxt = parts[i + 1]["ayah"] if i + 1 < len(parts) else None
        p["last"] = nxt != p["ayah"]
    return renumber(parts)


def renumber(parts):
    counts = {}
    for p in parts:
        counts[p["ayah"]] = counts.get(p["ayah"], 0) + 1
    seen = {}
    for p in parts:
        seen[p["ayah"]] = seen.get(p["ayah"], 0) + 1
        p["part"], p["of"] = seen[p["ayah"]], counts[p["ayah"]]
    return parts


# ---------------------------------------------------------------------- video
def background_clip():
    if not BACKGROUND_DIR.is_dir():
        return None
    clips = sorted(p for p in BACKGROUND_DIR.iterdir()
                   if not p.name.startswith("_")
                   and p.suffix.lower() in (".mov", ".mp4", ".m4v", ".jpg", ".png"))
    return clips[0] if clips else None


def seamless_loop(clip):
    """
    A short clip looped end to end shows a jump every time it restarts.
    Playing it forwards then backwards makes the join invisible. Built once
    and kept, so later videos reuse it.
    """
    if clip.suffix.lower() in (".jpg", ".png"):
        return clip
    looped = BACKGROUND_DIR / "_seamless.mp4"
    if looped.exists() and looped.stat().st_mtime > clip.stat().st_mtime:
        return looped
    print("  preparing the background loop (one time only) ...")
    res = run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(clip),
               "-filter_complex",
               f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
               f"crop={W}:{H},setsar=1,fps={FPS},split[a][b];"
               f"[b]reverse[r];[a][r]concat=n=2:v=1[v]",
               "-map", "[v]", "-an"] + loop_codec() + [str(looped)])
    if res.returncode != 0:
        print("  (could not build the smooth loop, using the clip as it is)")
        return clip
    return looped


def loop_codec():
    """A sharper setting of the same codec, for the background loop."""
    if VIDEO_CODEC[:2] == ["-c:v", "libx264"]:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    return list(VIDEO_CODEC)


def build(audio, slides, spans, out_path, background=None, progress=None, cancel=None,
          size=None):
    """
    Lay every ayah over the background at its own moment.

    Each one is held on screen a little past its turn, and fades in and out, so
    one ayah dissolves into the next instead of snapping.
    """
    W, H = size or (globals()["W"], globals()["H"])
    total = spans[-1][1]
    part = out_path.with_name(out_path.stem + ".part" + out_path.suffix)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]

    if background and background.suffix.lower() in (".jpg", ".png"):
        cmd += ["-loop", "1", "-framerate", str(FPS), "-i", str(background)]
    elif background:
        cmd += ["-stream_loop", "-1", "-i", str(background)]
    else:
        cmd += ["-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}"]

    cmd += ["-i", str(audio)]

    # Each ayah fades up at its start and fades away at its end. They do not
    # overlap on purpose: two lines of text dissolving through each other is
    # unreadable, so one clears before the next arrives.
    windows = []
    for start, end in spans:
        fade = min(FADE, max(0.05, (end - start) / 3))
        windows.append((start, end - start, fade))

    for s, (_, dur, _) in zip(slides, windows):
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(s)]

    blur = f",gblur=sigma={BACKGROUND_BLUR}" if (background and BACKGROUND_BLUR) else ""
    chain = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
             f"crop={W}:{H},setsar=1,fps={FPS}{blur}[bg]"]

    last = "bg"
    for i, (at, dur, fade) in enumerate(windows):
        src, tag = f"s{i}", f"v{i}"
        chain.append(
            f"[{i + 2}:v]format=rgba,"
            f"fade=t=in:st=0:d={fade:.3f}:alpha=1,"
            f"fade=t=out:st={max(0.0, dur - fade):.3f}:d={fade:.3f}:alpha=1,"
            f"setpts=PTS-STARTPTS+{at:.3f}/TB[{src}]")
        chain.append(f"[{last}][{src}]overlay=0:0:"
                     f"eof_action=pass:repeatlast=0[{tag}]")
        last = tag

    cmd += ["-filter_complex", ";".join(chain),
            "-map", f"[{last}]", "-map", "1:a",
            ] + VIDEO_CODEC + [
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            "-shortest", str(part)]

    # Make it under a temporary name, and only give it its real name once it's
    # finished. Then if a render gets cut off (the Mac sleeps, you press
    # Ctrl-C), there's no broken video left that --skip-done would think is done.
    if progress is None and cancel is None:
        res = run(cmd)
        ok, err = res.returncode == 0, res.stderr
    else:
        ok, err = run_watched(cmd, total, progress, cancel)
    if not ok:
        try:
            part.unlink()
        except OSError:
            pass
        die("ffmpeg failed:\n" + err[-1500:])
    part.replace(out_path)


def run_watched(cmd, total, progress=None, cancel=None):
    """
    Run ffmpeg while reporting how far along it is (0 to 1), and stop it
    straight away if cancel() says so. Used by the app.
    """
    import threading
    cmd = tool(cmd)
    cmd = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", **HIDDEN)
    err = []
    t = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
    t.start()
    stopped = False
    for line in proc.stdout:
        if cancel and cancel():
            proc.kill()
            stopped = True
            break
        if progress and line.startswith("out_time_us=") and total:
            try:
                progress(min(1.0, int(line.split("=")[1]) / 1e6 / total))
            except ValueError:
                pass
    proc.wait()
    t.join(timeout=2)
    if stopped:
        return False, "stopped"
    return proc.returncode == 0, "".join(err)


# ----------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Make a Quran video from a recitation.")
    ap.add_argument("audio", nargs="+",
                    help="one or more recordings, or a folder of them")
    ap.add_argument("--ayahs", help="override, e.g. '97:1-5' or 'Mulk 7-12'")
    ap.add_argument("--retime", action="store_true",
                    help="throw away the saved timings and listen again")
    ap.add_argument("--only", choices=["guess", "zizo"], help="make just one of the two")
    ap.add_argument("--preview", action="store_true",
                    help="just draw the text as pictures so you can check the look")
    ap.add_argument("--skip-done", action="store_true",
                    help="pass over any recording whose videos are already made "
                         "(in videos/ or videos/Published)")
    ap.add_argument("--no-listen", action="store_true",
                    help="split at the mushaf stop marks instead of listening")
    ap.add_argument("--name", help="name for the output files")
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            die(f"{tool} is not installed on this Mac.\n"
                f"  Double-click setup.command in this folder, then try again.")
    try:
        import numpy  # noqa: F401
    except ImportError:
        die("numpy is missing.\n"
            "  Double-click setup.command in this folder, then try again.")
    if not arabic_text.AVAILABLE and not SHAPING_BUILT_IN and not HAVE_RESHAPER:
        die("Nothing here can join up Arabic letters yet.\n"
            "  Double-click setup.command in this folder, then try again.")

    files = gather_audio(args.audio)
    if not files:
        die("No recordings found.")
    if len(files) > 1 and (args.name or args.ayahs):
        die("--name and --ayahs only work on one recording at a time.")

    quran = load_quran()
    done, failed = [], []
    for i, audio in enumerate(files, 1):
        if len(files) > 1:
            print(f"\n{'=' * 60}\n[{i} of {len(files)}]  {audio.name}")
        try:
            made = make_one(audio, args, quran)
            done.extend(made)
        except SystemExit as stop:
            if len(files) == 1:
                raise
            failed.append((audio.name, str(stop).strip()))
            print(f"  skipped: {str(stop).strip()}")

    if len(files) > 1:
        print(f"\n{'=' * 60}\n  made {len(done)} video{'s' if len(done) != 1 else ''} "
              f"from {len(files) - len(failed)} of {len(files)} recordings")
        for name, why in failed:
            print(f"    skipped {name} - {why.splitlines()[0]}")
        print()


AUDIO_KINDS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus", ".aiff"}


def gather_audio(given):
    """Turn what was typed into a list of recordings, folders included."""
    out = []
    for item in given:
        p = Path(item).expanduser()
        if p.is_dir():
            out += sorted(f for f in p.iterdir()
                          if f.suffix.lower() in AUDIO_KINDS and not f.name.startswith("."))
        elif p.exists():
            out.append(p)
        else:
            matches = sorted(Path().glob(item))
            if matches:
                out += [m for m in matches if m.suffix.lower() in AUDIO_KINDS]
            else:
                die(f"No such file: {p}")
    seen, unique = set(), []
    for f in out:
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def already_made(name):
    """Is this video already there - in videos/, or moved into videos/Published?"""
    return (OUT_DIR / name).exists() or (OUT_DIR / "Published" / name).exists()


def make_one(audio, args, quran):
    arabic, english, counts = quran
    stem = args.name or audio.stem

    # --skip-done: check this first, so a finished recording is passed over
    # straight away - no reading the ayahs, timings or audio
    if args.skip_done and not args.preview:
        wanted = []
        if args.only != "zizo":
            wanted.append(f"{stem}_guess.mp4")
        if args.only != "guess" and background_clip():
            wanted.append(f"{stem}.mp4")
        if wanted and all(already_made(w) for w in wanted):
            print(f"\n  {audio.name}: already made, skipping")
            return []

    ref = args.ayahs or audio.stem
    surah, first, last = parse_reference(ref)
    if not surah:
        die(f"I can't tell which surah '{ref}' is.\n"
            f"  Try:  python3 quranvid.py \"{audio.name}\" --ayahs \"Mulk 7-12\"")

    if first is None:
        first, last = 1, counts[surah]
    last = min(last, counts[surah])
    ayahs = [(surah, a) for a in range(first, last + 1)]
    for key in ayahs:
        if key not in arabic:
            die(f"Surah {surah} has no ayah {key[1]}.")

    label = f"{SURAHS[surah - 1]} {first}" + (f"-{last}" if last != first else "")
    print(f"\n  {label}   ({len(ayahs)} ayah{'s' if len(ayahs) > 1 else ''})")
    print(f"  audio: {audio.name}")

    # --- timings, saved so you can nudge them and run again
    TIMINGS_DIR.mkdir(exist_ok=True)
    timing_file = TIMINGS_DIR / f"{stem}.json"
    saved = None
    if timing_file.exists() and not args.retime:
        try:
            saved = json.loads(timing_file.read_text())
        except ValueError:
            saved = None

    total = audio_length(audio)
    if saved and all("arabic" in s and "start" in s for s in saved):
        # only these four matter - anything else in an older file is ignored
        parts = [{"ayah": int(s["ayah"]), "start": float(s["start"]),
                  "arabic": s["arabic"], "english": s.get("english", "")}
                 for s in saved]
        print(f"  using your saved timings ({timing_file.name})")
    else:
        db = loudness(audio)
        parts = None
        if not args.no_listen and listening_ready():
            print("  listening to what you recite ...")
            parts = build_parts_heard(audio, ayahs, arabic, english, db, total)
        if parts is None:
            if not args.no_listen:
                print("  (listening is not set up - splitting at the stop marks instead)")
            begin, finish = speech_bounds(db, total)
            pauses = sorted(find_pauses(audio), key=lambda p: p[0])
            spans = plan_timings(begin, finish, ayahs, arabic, pauses)
            parts = build_parts(ayahs, arabic, english, spans, db)

    numbered = any(has_ayah_number(p["arabic"]) for p in parts)
    parts = settle_parts(parts, total)
    if not numbered:            # older files: the number goes on each ayah's last part
        for p in parts:
            if p["last"]:
                p["arabic"] += " " + ayah_marker(p["ayah"])
    timing_file.write_text(json.dumps(
        [{"ayah": p["ayah"], "start": round(p["start"], 2),
          "arabic": p["arabic"], "english": p["english"]} for p in parts],
        indent=2, ensure_ascii=False))

    print("\n  what shows, and when:")
    for p in parts:
        tag = f"ayah {p['ayah']}" + (f" part {p['part']}/{p['of']}" if p["of"] > 1 else "")
        print(f"    {tag:<22} {p['start']:6.2f}s -> {p['end']:6.2f}s   "
              f"{p['english'][:46]}")

    # --- draw the text
    check_fonts()
    if args.preview:
        work = ROOT / "_preview"
        work.mkdir(exist_ok=True)
        for old in work.glob("*.png"):          # clear the last preview first
            try:
                old.unlink()
            except OSError:
                pass
    else:
        work = Path(tempfile.mkdtemp(prefix="quranvid-"))   # outside your folder
    slides = []
    spans = [(p["start"], p["end"]) for p in parts]
    for i, part in enumerate(parts):
        img = render_slide(part["arabic"], part["english"])
        p = work / f"{i:03d}.png"
        if args.preview:                      # flatten onto black so you can see it
            img = Image.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 255)), img)
        img.save(p)
        slides.append(p)

    if args.preview:
        print(f"\n  drew {len(slides)} picture(s) in {work}\n"
              f"  open them, then change the settings at the top of quranvid.py.\n")
        return []

    # --- render
    OUT_DIR.mkdir(exist_ok=True)
    made = []
    if args.only != "zizo":
        out = OUT_DIR / f"{stem}_guess.mp4"
        if args.skip_done and already_made(out.name):
            print(f"  {out.name} already there, leaving it")
        else:
            print(f"\n  rendering {out.name} ...")
            build(audio, slides, spans, out, background=None)
            made.append(out)
    if args.only != "guess":
        bg = background_clip()
        if not bg:
            print("\n  no background video in maker/background/ - skipping the "
                  "zizorecites version.")
        else:
            out = OUT_DIR / f"{stem}.mp4"
            if args.skip_done and already_made(out.name):
                print(f"  {out.name} already there, leaving it")
            else:
                bg = seamless_loop(bg)
                print(f"  rendering {out.name} ...")
                build(audio, slides, spans, out, background=bg)
                made.append(out)

    shutil.rmtree(work, ignore_errors=True)

    print("\n  done:")
    for m in made:
        print(f"    {m.name}")
    print(f"  timing off? edit timings/{timing_file.name} and run it again.")
    return made


if __name__ == "__main__":
    main()
