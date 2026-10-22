"""
Which English words go with which Arabic words.

The translation is written as flowing sentences, not word by word, so cutting
it up by length goes wrong: words get dropped, and lines end up under the wrong
Arabic. Instead, every Arabic word comes with its own short meaning
(data/glosses.json, from the quran.com word-by-word translation). Where a
meaning matches a word in the translation - "forgive" and "forgives" - that
pins the two together. Between those pins, a cut goes on the most natural break
nearby: a full stop, a comma, or a word like "and", "who" or "in".

Cuts are fixed points between words, shared by the screens on either side, so a
word can only move from one screen to its neighbour - it can never be lost.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GLOSS_FILE = ROOT / "data" / "glosses.json"
_GLOSS = None

# words too common to pin anything down
STOP = set("""
a an the of to in into on onto at by for from with without and or but nor so
then than that this these those who whom whose which what when where while as
is are was were be been being am it its he him his she her they them
their you your yours we us our ours i me my will
shall would should can could may might must do does did done has have had
there here up out o such very also only just even one ones any anyone
anything everyone everything thing things all none every each some
if whether surely indeed certainly truly verily rather yet still
upon against between over about among through during within towards
toward until unless because since beside besides near around
across beyond behind above below like unto
""".split())
# ("if", "surely" and the like turn up in the word meanings all over an ayah,
# so they pin English to the wrong copy - checked across the whole Quran.
# "himself" and "before" are left out of this list on purpose: نَفۡسِهِۦ and
# قَبۡلِ always mean those, so they make good pins.)

# words that pin weakly, because they turn up everywhere
LIGHT = {"allah": 0.5, "lord": 0.6, "not": 0.5, "no": 0.5, "say": 0.8}

# words that start a new piece of a sentence - a good place to cut before
STARTERS = set("""
and or but so then who whom which that until except unless for in on to
before after if when while as from by with upon because since lest whether
nor yet indeed surely say whoever whatever those like
""".split())

# little words that lean on the word after them - "the | Straight Path" or
# "their | hearts" is a bad place to cut
LEANS_FORWARD = set("""
the a an of in into to for with from by on at and or his her their its my
your our
""".split())
LEAN = 1.5

EMPTY_WORD = 0.8   # nudge against an Arabic word getting no English

END_PUNCT = ".?!"
MID_PUNCT = ";:—"
CLOSERS = "\"”’')"


def glosses_for(surah, ayah, n_words):
    """The word-by-word meanings for one ayah, or None if they don't line up."""
    global _GLOSS
    if _GLOSS is None:
        try:
            _GLOSS = json.loads(GLOSS_FILE.read_text(encoding="utf-8"))
        except Exception:
            _GLOSS = {}
    g = _GLOSS.get(f"{surah}:{ayah}")
    if not g or len(g) != n_words:
        return None
    return g


# ----------------------------------------------------------- comparing words
def stem(word):
    """Strip a word's ending so "forgives" and "forgive" look the same.
    Only when enough is left: "under" must not become "und"."""
    w = re.sub(r"[^a-z]", "", word.lower())
    for end in ("ingly", "edly", "ness", "ment", "ings", "ing", "ers",
                "ies", "ied", "ed", "es", "er", "ly", "s"):
        keep = 3 if end == "s" else 4
        if w.endswith(end) and len(w) - len(end) >= keep:
            return w[:-len(end)] + ("y" if end in ("ies", "ied") else "")
    return w


def alike(a, b):
    if a == b:
        return True
    n = min(len(a), len(b))
    return n >= 4 and (a.startswith(b) or b.startswith(a))


# The word meanings and the translation sometimes use different words for the
# same thing - names especially. Each meaning word also counts as these.
SAME_AS = {
    "musa": "moses", "isa": "jesus", "maryam": "mary", "ibrahim": "abraham",
    "nuh": "noah", "firaun": "pharaoh", "fir'aun": "pharaoh", "harun": "aaron",
    "haroon": "aaron", "yusuf": "joseph", "yaqub": "jacob", "ishaq": "isaac",
    "ismail": "ishmael", "dawud": "david", "dawood": "david",
    "sulaiman": "solomon", "taurat": "torah", "injeel": "gospel",
    "jibreel": "gabriel", "lut": "lot", "zakariya": "zachariah",
    "yahya": "john", "ayyub": "job", "yunus": "jonah", "ilyas": "elias",
    "shaitaan": "satan", "shaitan": "satan", "shaitaans": "devils",
    "shayateen": "devils", "iblees": "iblis", "makkah": "mecca",
    "masih": "messiah", "israil": "israel",
    "fear": "mindful", "pious": "mindful", "righteous": "mindful",
    "garden": "paradise", "gardens": "paradise", "hellfire": "hell",
    "spend": "donate", "disbelieve": "deny", "disbelieved": "denied",
    "torment": "punishment", "punishment": "torment",
    "messengers": "messenger", "ease": "prosperity", "hardship": "adversity",
}


def content_stems(text):
    out = []
    for w in re.findall(r"[A-Za-z']+", text):
        low = w.lower().strip("'")
        if low and low not in STOP and len(low) >= 2:
            out.append(stem(low))
            if low in SAME_AS:
                out.append(stem(SAME_AS[low]))
    return out


# ------------------------------------------------------------- the English
class Token:
    __slots__ = ("text", "glue", "low", "stem", "weight", "dash_before")

    def __init__(self, text, glue):
        self.text = text
        self.glue = glue                      # no space before it
        self.low = re.sub(r"[^a-z']", "", text.lower()).strip("'")
        # "All-Forgiving" is matched by its last part, "forgiving"
        core = re.sub(r"[^a-z']", "", text.lower().split("-")[-1]).strip("'")
        self.stem = stem(core) if core and core not in STOP else None
        self.weight = LIGHT.get(self.low, 1.0)
        self.dash_before = False


def tokenize(text):
    tokens = []
    for raw in text.split():
        pieces = [p for p in re.split(r"(?<=—)", raw) if p]   # "sin—and"
        for k, p in enumerate(pieces):
            tokens.append(Token(p, glue=k > 0))
    return tokens


def ends_with(token, chars):
    t = token.text.rstrip(CLOSERS)
    return bool(t) and t[-1] in chars


def rebuild(tokens):
    out = ""
    for t in tokens:
        text = t.text
        if t.dash_before and out:
            out = out.rstrip().rstrip("—,").rstrip() + " — "
            text = text.lstrip("—")
        elif out and not t.glue:
            out += " "
        out += text
    return tidy(out)


def tidy(text):
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("—").strip()
    return text


# ------------------------------------------------------------- one ayah
class AyahMap:
    """
    The English of one ayah, lined up against its Arabic words.

    between(x0, x1) gives the English for Arabic words x0 .. x1-1.
    """

    def __init__(self, surah, ayah, arabic_words, english_text):
        self.n = len(arabic_words)
        tokens = tokenize(english_text)
        gl = glosses_for(surah, ayah, self.n)
        self.meanings = [content_stems(g) for g in gl] if gl else [[] for _ in range(self.n)]
        # how many English words each Arabic word usually takes - فِي is just
        # "in", وَٱلضَّرَّآءِ is "and the hardship"
        self.size = ([max(1, len(re.findall(r"[A-Za-z']+", g))) for g in gl]
                     if gl else [1] * self.n)
        self.moved = False
        self.tokens = self._put_in_arabic_order(tokens) if gl else tokens
        self.m = len(self.tokens)
        self.free = self._is_free()
        self.cut = self._cuts()

    # -- where does a token's meaning appear in the Arabic?
    def _hits(self, token):
        if not token.stem:
            return []
        return [i for i, ms in enumerate(self.meanings)
                if any(alike(token.stem, s) for s in ms)]

    def _put_in_arabic_order(self, tokens):
        """
        Swap two neighbouring clauses that the translation put the other way
        round from the Arabic.

        This only happens when it is certain. The later clause has to be a
        side-remark the translator set off with a dash ("...persist in sin—and
        who forgives sins except Allah"), it has to match three or more Arabic
        words in a row (يَغۡفِرُ ٱلذُّنُوبَ إِلَّا ٱللَّهُ), and the clause before it
        has to match at least two words - and most of its matches - after that
        run. Freer moving was tried across the whole Quran: it scrambled good
        sentences in a dozen ayahs, so it is not done.
        """
        units, start = [], 0
        for k in range(1, len(tokens)):
            prev, cur = tokens[k - 1], tokens[k]
            if ends_with(prev, END_PUNCT + MID_PUNCT + ",") or cur.low in ("and", "or", "but"):
                units.append((start, k))
                start = k
        units.append((start, len(tokens)))

        def hits_of(unit):
            a, b = unit
            return [self._hits(t) for t in tokens[a:b] if self._hits(t)]

        def longest_run(hit_lists):
            """Longest stretch of Arabic words matched one after another."""
            best = (0, None, None)
            for s in range(len(hit_lists)):
                for p in hit_lists[s]:
                    length, pos = 1, p
                    for h in hit_lists[s + 1:]:
                        if pos + 1 in h:
                            length, pos = length + 1, pos + 1
                        else:
                            break
                    if length > best[0]:
                        best = (length, p, pos)
            return best

        order = list(range(len(units)))
        swapped = []
        k = 0
        while k < len(order) - 1:
            first, second = units[order[k]], units[order[k + 1]]
            # only a side-remark the translator set off with a dash may move
            aside = ends_with(tokens[first[1] - 1], "\u2014")
            run, r0, r1 = longest_run(hits_of(second)) if aside else (0, None, None)
            if run >= 3:
                after = [h for h in hits_of(first) if any(i > r1 for i in h)]
                if len(after) >= 2 and len(after) * 3 >= len(hits_of(first)) * 2:
                    order[k], order[k + 1] = order[k + 1], order[k]
                    swapped.extend([k, k + 1, k + 2])
                    k += 2
                    continue
            k += 1
        if not swapped:
            return tokens

        out, dash_at = [], []
        for pos, u in enumerate(order):
            a, b = units[u]
            if pos in swapped and pos > 0 and b > a:
                dash_at.append(len(out))
            out.extend(tokens[a:b])
        for k in dash_at:
            out[k].dash_before = True
            out[k].glue = False
        self.moved = True
        return out

    # -- pin English words to Arabic words, keeping both in order
    def _anchors(self, tokens=None, banned=frozenset(), depth=0):
        tokens = self.tokens if tokens is None else tokens
        n, m = self.n, len(tokens)
        score = [[0.0] * m for _ in range(n)]
        for j, t in enumerate(tokens):
            for i in self._hits(t):
                if (i, j) in banned:
                    continue
                # when a word could pin to two copies, prefer the copy at the
                # same place in the sentence (a small nudge, only settles ties)
                score[i][j] = t.weight - 0.15 * abs((i + 0.5) / n - (j + 0.5) / m)
        best = [[0.0] * (m + 1) for _ in range(n + 1)]
        how = [[0] * (m + 1) for _ in range(n + 1)]
        for i in range(n + 1):
            for j in range(m + 1):
                if i == 0 and j == 0:
                    continue
                opts = []
                if i > 0:
                    opts.append((best[i - 1][j], 1))
                if j > 0:
                    opts.append((best[i][j - 1], 2))
                if i > 0 and j > 0 and score[i - 1][j - 1]:
                    opts.append((best[i - 1][j - 1] + score[i - 1][j - 1], 3))
                    # one Arabic word may take a second English word ("And
                    # hasten"), but it counts for less, so that two far-apart
                    # copies of "Allah" don't both land on the same word
                    opts.append((best[i][j - 1] + 0.6 * score[i - 1][j - 1], 4))
                best[i][j], how[i][j] = max(opts)
        pins, i, j = [], n, m
        while i > 0 or j > 0:
            h = how[i][j]
            if h == 1:
                i -= 1
            elif h == 2:
                j -= 1
            else:
                pins.append((i - 1, j - 1))
                if h == 3:
                    i, j = i - 1, j - 1
                else:
                    j -= 1
        pins.sort()
        # A second match on one Arabic word must sit close to the first. If
        # it doesn't, one of the two is wrong ("forgiveness" and "All-Forgiving"
        # both on غَفُورٞ, when "forgiveness" belongs to وَٱسۡتَغۡفِرُواْ). Try
        # without each one, and keep whichever lines up better.
        for (i1, j1), (i2, j2) in zip(pins, pins[1:]):
            if i1 == i2 and j2 - j1 > 3:
                if depth >= 4:
                    break
                tries = [self._anchors(tokens, banned | {(i1, jj)}, depth + 1)
                         for jj in (j1, j2)]
                return max(tries, key=lambda r: r[1])
        return pins, best[n][m]

    def _quality(self, b):
        if b <= 0 or b >= self.m:
            return 0.0
        q = 0.0
        prev, cur = self.tokens[b - 1], self.tokens[b]
        if ends_with(prev, ",:") and cur.text[:1] in "\u201c\"":
            return -3.0     # never split "The believers pray," from its quote
        if ends_with(prev, END_PUNCT):
            q += 3.0
        elif ends_with(prev, MID_PUNCT):
            q += 2.0
        elif ends_with(prev, ","):
            q += 1.5
        elif prev.low in LEANS_FORWARD:
            q -= LEAN
        if cur.low in STARTERS:
            q += 1.0
        if cur.dash_before:
            q += 2.0
        return q

    def _cuts(self):
        """For every gap between Arabic words, the gap in the English."""
        n, m = self.n, self.m
        pins = self._anchors()[0]
        # Arabic words whose meaning shows up somewhere in the English. Such a
        # word may fairly end up with no English of its own here - its words
        # are elsewhere, because English puts them in a different order.
        found = [False] * n
        for t in self.tokens:
            for i in self._hits(t):
                found[i] = True
        cut = [0] * (n + 1)
        cut[n] = m
        for x in range(1, n):
            before = [p for p in pins if p[0] < x]
            after = [p for p in pins if p[0] >= x]
            j0 = before[-1][1] + 1 if before else 0
            j1 = min(j for _, j in after) if after else m
            i0 = before[-1][0] + 1 if before else 0
            i1 = after[0][0] if after else n
            # how far through the unpinned stretch this gap is, counting by
            # the length of each word's meaning rather than one per word
            f = sum(self.size[i0:x]) / max(1, sum(self.size[i0:i1]))
            guess = j0 + f * (j1 - j0)
            lo = max(j0, cut[x - 1])
            hi = max(j1, lo)
            prev_cut = cut[x - 1]

            def score(b):
                s = self._quality(b) - 0.5 * abs(b - guess)
                if b == prev_cut and not found[x - 1]:
                    s -= EMPTY_WORD            # would leave that word with no English
                return (s, -b)

            cut[x] = max(range(lo, hi + 1), key=score)
        return cut

    def _is_free(self):
        """
        Did the translator rebuild this ayah in a different order?

        If most of the English words that match a meaning can't be lined up
        in order with the Arabic, the sentence was reordered as a whole ("It
        was not until this clear proof came... that they became divided" for
        وَمَا تَفَرَّقَ ... إِلَّا مِنۢ بَعۡدِ مَا جَآءَتۡهُمُ ٱلۡبَيِّنَةُ). Then
        no split inside a sentence can be right.
        """
        # counted in Arabic words, using only meanings that point at a single
        # word (so "became divided" counts once, and "Allah", which turns up
        # all over, doesn't count at all)
        matched = set()
        for t in self.tokens:
            h = self._hits(t)
            if len(h) == 1:
                matched.add(h[0])
        kept = {i for i, _ in self._anchors()[0]} & matched
        return len(matched) >= 3 and len(kept) < 0.5 * len(matched)

    def _sentences(self):
        """Each sentence of the English, with the stretch of Arabic it covers."""
        ends = [k + 1 for k, t in enumerate(self.tokens) if ends_with(t, END_PUNCT)]
        if not ends or ends[-1] != self.m:
            ends.append(self.m)
        total = float(sum(self.size)) or 1.0
        cum = [0.0]
        for s in self.size:
            cum.append(cum[-1] + s)
        out, start = [], 0
        for end in ends:
            a = cum[-1] * start / self.m       # spread by meaning length
            b = cum[-1] * end / self.m
            out.append((a, b, start, end))
            start = end
        return out, cum

    def gap_quality(self, x):
        """How good a place the gap before Arabic word x is to break the English."""
        if x <= 0 or x >= self.n:
            return 3.0                     # the end of an ayah
        if self.free:
            return None                    # no good place: it all shows anyway
        return self._quality(self.cut[x])

    def between(self, x0, x1):
        x0, x1 = max(0, x0), min(self.n, x1)
        if x1 <= x0:
            return ""
        if not self.free:
            return rebuild(self.tokens[self.cut[x0]:self.cut[x1]])
        # a reordered ayah: show every whole sentence this stretch touches
        sentences, cum = self._sentences()
        lo, hi = cum[x0], cum[x1]
        picked = [rebuild(self.tokens[s:e]) for a, b, s, e in sentences
                  if min(b, hi) > max(a, lo)]
        return " ".join(p for p in picked if p)


# --------------------------------------------------------- several ayahs
DIVINE = {"He", "His", "Him", "Himself", "Allah", "We", "Our", "Us", "I", "Me", "My"}


def join_ayahs(texts):
    """
    Put the English of neighbouring ayahs side by side.

    The translation often leaves an ayah without a full stop because its
    sentence carries on. If the next ayah starts a new sentence anyway, a dash
    keeps the two from running together. (Words like He and Allah are written
    with a capital mid-sentence, so they don't count as a new sentence.)
    """
    out = ""
    for text in texts:
        if not text:
            continue
        if out:
            first = text.split()[0].strip("“\"'(")
            new_sentence = first[:1].isupper() and first not in DIVINE
            if new_sentence and out.rstrip()[-1:] not in ".?!,;:—–\"”’)":
                out = out.rstrip() + " —"
            out += " "
        out += text
    return out.strip()
