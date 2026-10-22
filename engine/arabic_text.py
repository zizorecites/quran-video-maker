"""
Draw Arabic properly, on any machine.

Arabic letters change shape depending on what sits either side of them, and a
Quranic font stacks vowel marks in places only the font itself knows about.
Pillow can do this, but only when it was built with a library called raqm, and
most Macs do not have that build. The usual stand-in (arabic-reshaper) swaps
letters for old "presentation form" characters, which the King Fahd mushaf font
does not contain - so the text comes out blank.

So this module asks the font to lay itself out, using the same engine every
browser and word processor uses (HarfBuzz), and then draws the shapes it hands
back. No guessing, and it works the same everywhere.
"""

from pathlib import Path

from PIL import Image

try:
    import freetype
    import uharfbuzz as hb
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


class ArabicFont:
    """One font file, ready to lay out and draw text at any size."""

    _cache = {}

    def __init__(self, path):
        self.path = str(path)
        data = Path(path).read_bytes()
        self.face = hb.Face(hb.Blob(data))
        self.ft = freetype.Face(self.path)

    @classmethod
    def get(cls, path):
        key = str(path)
        if key not in cls._cache:
            cls._cache[key] = cls(path)
        return cls._cache[key]

    def _shape(self, text, size):
        font = hb.Font(self.face)
        font.scale = (size * 64, size * 64)
        hb.ot_font_set_funcs(font)
        buf = hb.Buffer()
        buf.add_str(text)
        buf.direction = "rtl"
        buf.script = "Arab"
        buf.language = "ar"
        hb.shape(font, buf)
        return list(zip(buf.glyph_infos, buf.glyph_positions))

    def width(self, text, size):
        shaped = self._shape(text, size)
        return sum(p.x_advance for _, p in shaped) / 64.0

    def draw(self, img, text, size, center_x, baseline_y, fill=(255, 255, 255, 255)):
        """Draw `text` on `img`, centred on center_x, sitting on baseline_y."""
        shaped = self._shape(text, size)
        total = sum(p.x_advance for _, p in shaped) / 64.0
        pen_x = center_x - total / 2.0
        pen_y = float(baseline_y)

        self.ft.set_char_size(int(round(size * 64)))
        colour = Image.new("RGBA", img.size, fill[:3] + (0,))
        alpha = Image.new("L", img.size, 0)

        for info, pos in shaped:
            self.ft.load_glyph(info.codepoint,
                               freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
            slot = self.ft.glyph
            bmp = slot.bitmap
            if bmp.width and bmp.rows:
                rows = [bytes(bmp.buffer[r * bmp.pitch:r * bmp.pitch + bmp.width])
                        for r in range(bmp.rows)]
                glyph_img = Image.frombytes("L", (bmp.width, bmp.rows), b"".join(rows))
                x = int(round(pen_x + pos.x_offset / 64.0 + slot.bitmap_left))
                y = int(round(pen_y - pos.y_offset / 64.0 - slot.bitmap_top))
                # keep the darkest of what is already there and this glyph,
                # so overlapping marks do not wash each other out
                patch = alpha.crop((x, y, x + bmp.width, y + bmp.rows))
                glyph_img = Image.composite(
                    glyph_img, patch,
                    glyph_img.point(lambda v, p=0: 255 if v else 0).convert("1"))
                alpha.paste(glyph_img, (x, y))
            pen_x += pos.x_advance / 64.0
            pen_y -= pos.y_advance / 64.0

        if fill[3] != 255:
            alpha = alpha.point(lambda v: v * fill[3] // 255)
        colour.putalpha(alpha)
        img.alpha_composite(colour)


def ascent_descent(path, size):
    """How far the tallest mark rises and the lowest dips, in pixels."""
    f = ArabicFont.get(path)
    f.ft.set_char_size(int(round(size * 64)))
    m = f.ft.size
    return m.ascender / 64.0, -m.descender / 64.0
