"""
Listen to a recitation and work out which words of the mushaf were said, and
when - including words said twice.

It uses Whisper, a speech recogniser, which writes down what it hears in plain
Arabic. That is never exactly the mushaf spelling, so we then line its words up
against the real text, allowing for words it mishears, words it misses, and
places where you go back and say something again.
"""

import json
import subprocess
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models" / "whisper-small"
CACHE_DIR = ROOT / "transcripts"

try:
    from faster_whisper import WhisperModel
    _HAVE_WHISPER = True
except Exception:
    _HAVE_WHISPER = False


def available():
    return _HAVE_WHISPER and (MODEL_DIR / "model.bin").exists()


# ------------------------------------------------------------------ hearing
FFMPEG = "ffmpeg"  # the app points this at its own copy
RATE = 16000       # Whisper listens at 16,000 samples a second


def load_sound(audio):
    """
    The recording as plain numbers, read once by ffmpeg.

    Whisper can open files itself, but how it does that keeps changing between
    versions - this way works the same everywhere.
    """
    import numpy as np
    kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(audio), "-ac", "1",
                          "-ar", str(RATE), "-f", "f32le", "-"],
                         capture_output=True, **kw).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


VERSION = 4        # bump when listening changes, so old transcripts are redone
HOLE = 1.2         # this long with voice but no words heard = listen again


def _hear(model, audio, clip=None):
    kw = {"clip_timestamps": [clip[0], clip[1]]} if clip else {}
    segments, info = model.transcribe(
        audio, language="ar", word_timestamps=True, beam_size=5,
        vad_filter=False, condition_on_previous_text=False, **kw)
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"word": text, "start": round(w.start, 2),
                              "end": round(w.end, 2), "sure": round(w.probability, 2)})
    return words, info.duration


def _holes(words, duration, has_voice):
    """Stretches where something was said but no words came back."""
    edges = [0.0] + [x for w in words for x in (w["start"], w["end"])] + [duration]
    out = []
    for k in range(0, len(edges) - 1, 2):
        a, b = edges[k], edges[k + 1]
        if b - a >= HOLE and has_voice(a, b):
            out.append((a, b))
    return out


def transcribe(audio, fresh=False, has_voice=None, breaths=None, total=None,
               progress=None):
    """
    Every word heard, with when it started and ended.

    It listens one breath at a time (`breaths` = the times you breathe).
    Listening to the whole recording in one go, Whisper often writes a
    repeated phrase down only once - "ذكروا الله ذكروا الله" came out as one
    "ذكروا الله". Each breath on its own can't be mixed up with the one before.

    Whisper also now and then skips a stretch, so any stretch where there is
    clearly a voice but no words came back gets listened to again.

    Kept in transcripts/ so the same recording is only listened to once.
    """
    audio = Path(audio)
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"{audio.stem}.json"
    breaths = [round(float(t), 2) for t in (breaths or [])]
    stamp = {"size": audio.stat().st_size, "mtime": int(audio.stat().st_mtime),
             "v": VERSION, "breaths": breaths}

    if cache.exists() and not fresh:
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if saved.get("audio") == stamp:
                return saved["words"]
        except (ValueError, KeyError):
            pass

    model = WhisperModel(str(MODEL_DIR), device="cpu", compute_type="int8")
    sound = load_sound(audio)
    if sound.size == 0:
        sound = str(audio)                 # let Whisper try to open it itself
    if breaths and total:
        words, duration = [], total
        edges = [0.0] + breaths + [total]
        for n, (a, b) in enumerate(zip(edges, edges[1:])):
            if progress:
                progress(n / (len(edges) - 1))      # how far along, 0 to 1
            heard, _ = _hear(model, sound, clip=(a, b))
            # keep only words that really sit inside this breath
            heard = [w for w in heard if a - 0.05 <= (w["start"] + w["end"]) / 2 < b + 0.05]
            for k, w in enumerate(heard):
                w["after_breath"] = k        # 0 = first word after a breath
            words += heard
    else:
        words, duration = _hear(model, sound)

    refilled = 0
    if has_voice:
        tried = set()
        for _ in range(3):
            holes = [h for h in _holes(words, duration, has_voice)
                     if (round(h[0], 1), round(h[1], 1)) not in tried]
            if not holes:
                break
            for a, b in holes:
                tried.add((round(a, 1), round(b, 1)))
                extra, _ = _hear(model, sound, clip=(max(0.0, a - 0.3), min(duration, b + 0.3)))
                extra = [w for w in extra if w["start"] >= a - 0.35 and w["end"] <= b + 0.35]
                refilled += len(extra)
                words.extend(extra)
            words.sort(key=lambda w: w["start"])
    if refilled:
        print(f"  heard {refilled} more word{'s' if refilled != 1 else ''} "
              f"on a second listen to bits Whisper skipped")

    cache.write_text(json.dumps({"audio": stamp, "words": words},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    return words


# --------------------------------------------------------------- comparing
ALEFS = "ٱأإآ"          # ٱ أ إ آ  -> ا


def plain(word):
    """
    Strip a word down to bare letters so the mushaf spelling and the plain
    spelling Whisper writes can be compared.
    """
    w = word.replace("ٰ", "ا")       # small alef above -> full alef
    for a in ALEFS:
        w = w.replace(a, "ا")
    w = (w.replace("ى", "ي")         # ى -> ي
          .replace("ة", "ه")         # ة -> ه
          .replace("ؤ", "و")         # ؤ -> و
          .replace("ئ", "ي")         # ئ -> ي
          .replace("ء", ""))              # ء dropped
    return "".join(c for c in w if unicodedata.category(c) == "Lo")


def alike(a, b):
    """How alike two plain words are, from 0 to 1."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    best = SequenceMatcher(None, a, b).ratio()
    # Whisper often drops or adds the "ال" at the front
    for x, y in ((a, b[2:] if b.startswith("ال") else b),
                 (a[2:] if a.startswith("ال") else a, b)):
        if x and y:
            best = max(best, SequenceMatcher(None, x, y).ratio())
    return best


# --------------------------------------------------------------- lining up
MATCH = 2.2        # cost scale for a poor match
JUNK = 1.3         # a heard word that is not in the text at all
SKIP = 0.9         # a word in the text that was not heard
BACK = 1.6         # going back to say something again...
BACK_AT_BREATH = 0.4   # ...but right after a breath, that's where repeats happen
BACK_MAX = 14      # furthest back a repeat can reach, in words
PAIR = 0.3         # one heard word that is two words of the text run together
#                    ("الفشار" for "أَلۡفِ شَهۡرٖ") - a small extra cost
EARLY = 0.002      # tiny nudge: if two places fit equally well, pick the earlier
#                    (when Whisper hears a phrase said twice in a row, like
#                    "لَيۡلَةُ ٱلۡقَدۡرِ لَيۡلَةُ ٱلۡقَدۡرِ", it often writes it once;
#                    the copy it heard is the first, the second is hidden in
#                    the stretched-out word after it)


def align(heard, text_words):
    """
    For every heard word, which word of the text it was - or None. A heard
    word that was two words run together gets "two" set, and points at the
    second of them.

    Works through the heard words in order, keeping the cheapest explanation
    of how the reciting moved through the text. Moving on one word is free,
    jumping ahead means words were not heard, and jumping back means a repeat.
    """
    H = [plain(h["word"]) for h in heard]
    T = [plain(t) for t in text_words]
    n, m = len(H), len(T)
    if n == 0 or m == 0:
        return [None] * n

    INF = float("inf")
    NOWHERE = m                     # the state before any word has matched
    sim = [[alike(H[i], T[j]) for j in range(m)] for i in range(n)]
    # Whisper sometimes writes two words as one, so also compare each heard
    # word with every pair of words next to each other
    pair = [[0.0] + [alike(H[i], T[j - 1] + T[j]) for j in range(1, m)] for i in range(n)]

    # cost[i][j] = cheapest story for heard words 0..i that ends with heard
    # word i sitting on text word j (or still NOWHERE).
    cost = [[INF] * (m + 1) for _ in range(n)]
    came = [[None] * (m + 1) for _ in range(n)]      # (previous j, what happened)

    for j in range(m):              # the first heard word: words before it unheard
        cost[0][j] = SKIP * j + MATCH * (1 - sim[0][j]) + EARLY * j
        came[0][j] = (None, "match")
        if j >= 1:
            c = SKIP * (j - 1) + MATCH * (1 - pair[0][j]) + PAIR + EARLY * j
            if c < cost[0][j]:
                cost[0][j], came[0][j] = c, (None, "pair")
    cost[0][NOWHERE] = JUNK
    came[0][NOWHERE] = (None, "junk")

    for i in range(1, n):
        prev = cost[i - 1]
        here = cost[i]
        # you only ever go back right after taking a breath, so a repeat that
        # starts there is cheap (the first word or two, in case Whisper
        # misheard the very first one)
        back = BACK_AT_BREATH if heard[i].get("after_breath", 9) <= 1 else BACK
        # Moving forward from k to j costs SKIP for every word jumped over.
        # Track the best "prev[k] - SKIP*k" seen so far so this is quick.
        best, best_k = prev[NOWHERE] + SKIP, NOWHERE     # NOWHERE acts like k = -1
        best2, best2_k = best, best_k                     # the same, one word earlier
        for j in range(m):
            mc = MATCH * (1 - sim[i][j]) + EARLY * j
            c = best + SKIP * (j - 1) + mc
            if c < here[j]:
                here[j], came[i][j] = c, (best_k, "match")
            if j >= 1:              # heard word i was words j-1 and j together
                c = best2 + SKIP * (j - 2) + MATCH * (1 - pair[i][j]) + PAIR + EARLY * j
                if c < here[j]:
                    here[j], came[i][j] = c, (best2_k, "pair")
            best2, best2_k = best, best_k
            # going back to j from somewhere at or after it: a repeat
            for k in range(j, min(m, j + BACK_MAX + 1)):
                if prev[k] < INF:
                    c = prev[k] + back + 0.04 * (k - j) + mc
                    if c < here[j]:
                        here[j], came[i][j] = c, (k, "match")
            if prev[j] - SKIP * j < best:
                best, best_k = prev[j] - SKIP * j, j
        # this heard word is not in the text at all: stay put
        for j in range(m + 1):
            c = prev[j] + JUNK
            if c < here[j]:
                here[j], came[i][j] = c, (j, "junk")

    # words never reached at the very end count as unheard
    finish = [cost[n - 1][j] + SKIP * (m - 1 - j) for j in range(m)]
    finish.append(cost[n - 1][NOWHERE] + SKIP * m)
    j = min(range(m + 1), key=lambda x: finish[x])

    out = [None] * n
    for i in range(n - 1, -1, -1):
        k, what = came[i][j]
        out[i] = j if (what != "junk" and j != NOWHERE) else None
        # mark a heard word that was two words of the text run together
        heard[i]["two"] = what == "pair" and j != NOWHERE
        if k is None:
            break
        j = k
    return out
