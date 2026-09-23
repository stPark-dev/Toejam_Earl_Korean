"""Build 4bpp glyph tiles for the text renderer.

Cells are 16px tall. ASCII glyphs are 8px wide (2 tiles: top, bottom);
Hangul and other wide glyphs are 16px wide (4 tiles: TL, BL, TR, BR — the
column-major order the Mega Drive uses for a 2x2 sprite).

Palette convention matches the original font so the game's copy routine
(0x27B54) remaps it: 0x8 = ink (becomes colour 15, black), 0xB = outline
(becomes colour 1, white), 0 = transparent. The last column of every cell
stays transparent as letter spacing.
"""
import os

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
# Hangul: Galmuri14 fills the 16px cell and keeps every vowel stroke visible
# under the 1px outline (Galmuri11 draws some strokes 1px wide and they vanish).
WIDE_FONT = (os.path.join(FONT_DIR, "Galmuri14.ttf"), 14, 0)      # path, px, top row
# ASCII: Galmuri11's Latin glyphs fit the 7 usable columns of a narrow cell.
NARROW_FONT = (os.path.join(FONT_DIR, "Galmuri11.ttf"), 11, 2)
# HUD: the in-game panel uses one row of 8x8 tiles, so Hangul there is a
# 7px Galmuri7 glyph in an 8x8 tile, drawn in the original HUD font's colours.
HUD_FONT = (os.path.join(FONT_DIR, "Galmuri7.ttf"), 7, 0)
HUD_BG = 0xF                # opaque box, as the original 8x8 HUD font
HUD_INK = 0x5
CELL_H = 16
NARROW_W = 8
WIDE_W = 16
COLOR_BG = 0x0
COLOR_OUTLINE = 0xB
COLOR_INK = 0x8
# Plane text (menus, level messages) copies tiles verbatim, so it uses the
# palette of the original 8x8 menu font: yellow ink, brown shade, black box.
PLANE_BG = 0xF
PLANE_SHADE = 0x8
PLANE_INK = 0x5
# Style: thicken strokes to 2px and let each glyph sit 0 or 1px lower, so
# lines get the hand-drawn wobble of the original lettering.
BOLD = True
JITTER = True
NARROW_FIRST = 0x20
NARROW_COUNT = 95           # 0x20..0x7E
TILE_BYTES = 32

_fonts = {}


def font(wide):
    spec = WIDE_FONT if wide else NARROW_FONT
    if spec not in _fonts:
        _fonts[spec] = ImageFont.truetype(spec[0], spec[1])
    return _fonts[spec]


def jitter(ch):
    """Deterministic 0/1 px drop per character (Python's hash is randomised)."""
    return (ord(ch) * 2654435761 >> 7) & 1 if JITTER else 0


def ink_mask(ch, width):
    """Return a width x CELL_H matrix of 0/1 ink pixels, glyph centred."""
    wide = width > NARROW_W
    f = font(wide)
    glyph_y = (WIDE_FONT if wide else NARROW_FONT)[2] + jitter(ch)
    left, top, right, bottom = f.getbbox(ch)
    glyph_w = right - left + (1 if BOLD else 0)
    usable = width - 1                      # last column is spacing
    x = max(0, (usable - glyph_w) // 2) - left
    img = Image.new("1", (width, CELL_H), 0)
    ImageDraw.Draw(img).text((x, glyph_y), ch, font=f, fill=1)
    px = img.load()
    rows = [[1 if px[c, r] else 0 for c in range(width)] for r in range(CELL_H)]
    if BOLD:                                # dilate one pixel to the right
        rows = [[1 if (r[c] or (c and r[c - 1])) else 0 for c in range(width)] for r in rows]
    for r in rows:
        r[width - 1] = 0
    return rows


def paint_cell(mask):
    """Turn an ink mask into palette indices: ink plus a 1px outline."""
    h, w = len(mask), len(mask[0])
    out = [[COLOR_BG] * w for _ in range(h)]
    for r in range(h):
        for c in range(w):
            if mask[r][c]:
                out[r][c] = COLOR_INK
                continue
            if any(mask[rr][cc]
                   for rr in range(max(0, r - 1), min(h, r + 2))
                   for cc in range(max(0, c - 1), min(w, c + 2))):
                out[r][c] = COLOR_OUTLINE
    for r in range(h):
        out[r][w - 1] = 0
    return out


def tile_bytes(cell, x0, y0):
    """Pack the 8x8 block at (x0, y0) of a cell into 32 bytes of 4bpp."""
    data = bytearray()
    for r in range(y0, y0 + 8):
        for c in range(x0, x0 + 8, 2):
            data.append((cell[r][c] << 4) | cell[r][c + 1])
    return bytes(data)


def cell_tiles(cell):
    """Column-major tile order: for each 8px column, top then bottom."""
    w = len(cell[0])
    out = b""
    for x0 in range(0, w, 8):
        out += tile_bytes(cell, x0, 0) + tile_bytes(cell, x0, 8)
    return out


def paint_plane_cell(mask):
    """Plane-text palette: ink with a 1px drop shadow on an opaque box."""
    h, w = len(mask), len(mask[0])
    out = [[PLANE_BG] * w for _ in range(h)]
    for r in range(h):
        for c in range(w):
            if mask[r][c]:
                out[r][c] = PLANE_INK
            elif (r and c and mask[r - 1][c - 1]) or (r and mask[r - 1][c]) or (c and mask[r][c - 1]):
                out[r][c] = PLANE_SHADE
    return out


def glyph(ch, wide, plane=False):
    width = WIDE_W if wide else NARROW_W
    if ch == " ":
        return bytes(TILE_BYTES * (width // 8) * 2)
    mask = ink_mask(ch, width)
    return cell_tiles(paint_plane_cell(mask) if plane else paint_cell(mask))


def narrow_table(plane=False):
    """95 glyphs for ASCII 0x20..0x7E, 64 bytes each."""
    return b"".join(glyph(chr(c), wide=False, plane=plane)
                    for c in range(NARROW_FIRST, NARROW_FIRST + NARROW_COUNT))


def wide_table(chars, plane=False):
    """128 bytes per glyph in the given order."""
    return b"".join(glyph(ch, wide=True, plane=plane) for ch in chars)


def preview(chars, wide, scale=4):
    """Render glyphs to a PIL image for eyeballing."""
    pal = {COLOR_BG: (0, 140, 0), COLOR_OUTLINE: (255, 255, 255), COLOR_INK: (0, 0, 0)}
    width = WIDE_W if wide else NARROW_W
    img = Image.new("RGB", (width * len(chars), CELL_H))
    for i, ch in enumerate(chars):
        cell = paint_cell(ink_mask(ch, width)) if ch != " " else [[0] * width for _ in range(CELL_H)]
        for r in range(CELL_H):
            for c in range(width):
                img.putpixel((i * width + c, r), pal[cell[r][c]])
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def hud_glyph(ch):
    """One 8x8 tile (32 bytes) for the single-row HUD text."""
    path, size, top = HUD_FONT
    if HUD_FONT not in _fonts:
        _fonts[HUD_FONT] = ImageFont.truetype(path, size)
    f = _fonts[HUD_FONT]
    left, _t, right, bottom = f.getbbox(ch)
    x = max(0, (7 - (right - left)) // 2) - left
    y = top + (jitter(ch) if bottom + top < 8 else 0)     # wobble when there is a spare row
    img = Image.new("1", (8, 8), 0)
    ImageDraw.Draw(img).text((x, y), ch, font=f, fill=1)
    px = img.load()
    cell = [[HUD_INK if px[c, r] else HUD_BG for c in range(8)] for r in range(8)]
    return tile_bytes(cell, 0, 0)


def hud_table(chars):
    return b"".join(hud_glyph(ch) for ch in chars)
