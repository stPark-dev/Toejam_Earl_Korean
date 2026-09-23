"""Korean replacements for text that the game stores as graphics tiles.

Each label names an uncompressed tile asset, the tile indices its letters
occupy (in reading order, one list per 8px row) and the palette indices of
the original lettering. New tiles are rendered from the HUD font (8px rows)
or the wide font (two rows = 16px letters) and written over those slots.
"""
from dataclasses import dataclass

from . import font

HUD_ASSET = 0xA839E        # bottom panel: "toEJaM iS A", "EaRL iS", font
PRESENTS_ASSET = 0xABF0A   # present list: "OPEN" title


@dataclass(frozen=True)
class Label:
    asset: int
    rows: tuple           # tuple of tuples of tile indices, top row first
    text: str
    bg: int
    ink: int
    outline: int = None   # 16px labels only


# Active label replacements. The HUD panel labels went back to Korean once the
# 8x8 Hangul became legible (Galmuri7 has to be rendered at 8px, not 7 -- see
# font.HUD_FONT); at 7px every syllable with a final consonant was a blob.
# Tile numbering: tile 31 is the "t" of "toEJaM". Tiles 10-30 are the purple
# border decoration (bg 0xD, yellow 0x5) -- writing labels there scatters
# Hangul through the panel frame.
LABELS = (
    # "toEJaM iS A" (the rank name follows at run time); asset loads at VRAM 0x588
    Label(HUD_ASSET, ((31, 32, 33, 34, 35, 36, 37),), "토잼 등급", bg=0xF, ink=0x9),
    # "EaRL iS" ("휴가 / 중" follows at run time). Earl's panel draws five tiles
    # in this order; 36 is shared with Toejam's label and both blank it.
    Label(HUD_ASSET, ((38, 39, 40, 46, 36),), "얼은", bg=0xF, ink=0x9),
    # "BUCKS": the S lives apart, at tile 45. The count is drawn to the right of
    # the label, so the syllable sits in the last tile before it.
    Label(HUD_ASSET, ((1, 2, 3, 4, 45),), "   돈 ", bg=0xF, ink=0x5),
    # "POiNTS": the count is drawn to its left, so the syllable leads.
    Label(HUD_ASSET, ((5, 6, 7, 8, 9, 10),), "점     ", bg=0xF, ink=0x5),
)

# The present list's "OPEN" title (asset 0xABF0A, tiles 1-18) is animated by
# copying pixel rows, not whole tiles, so replacing its tiles scrambles it.
# Kept here for a later pass that rewrites the copy routine.
DEFERRED_LABELS = (
    Label(PRESENTS_ASSET, ((1, 2, 3, 4, 5, 6, 7, 8, 9), (10, 11, 12, 13, 14, 15, 16, 17, 18)),
          "선물 열기", bg=0xF, ink=0xC, outline=0x1),
)


def _pack(cell, x0, y0, bg):
    data = bytearray()
    for r in range(y0, y0 + 8):
        for c in range(x0, x0 + 8, 2):
            data.append((cell[r][c] << 4) | cell[r][c + 1])
    return bytes(data)


def render_label(label):
    """Return {tile index: 32 bytes} for every cell the label occupies."""
    tiles = {}
    if len(label.rows) == 1:                      # 8px lettering
        cells = label.rows[0]
        for i, idx in enumerate(cells):
            ch = label.text[i] if i < len(label.text) else " "
            if ch == " ":
                tiles[idx] = bytes([label.bg * 17]) * 32
                continue
            glyph = font.hud_glyph(ch)
            cell = [[(label.ink if v == font.HUD_INK else label.bg)
                     for v in ((b >> 4, b & 15)[k] for b in glyph[r * 4:r * 4 + 4] for k in (0, 1))]
                    for r in range(8)]
            tiles[idx] = _pack(cell, 0, 0, label.bg)
        return tiles
    top, bottom = label.rows                      # 16px lettering, 2 tiles per Hangul
    col = 0
    for ch in label.text:
        width = font.WIDE_W if not font.is_narrow(ch) else font.NARROW_W
        if ch == " ":
            cell = [[label.bg] * width for _ in range(font.CELL_H)]
        else:
            mask = font.ink_mask(ch, width)
            painted = font.paint_cell(mask)
            remap = {font.COLOR_INK: label.ink, font.COLOR_OUTLINE: label.outline, 0: label.bg}
            cell = [[remap[v] for v in row] for row in painted]
        for x0 in range(0, width, 8):
            if col >= len(top):
                raise ValueError(f"label {label.text!r} does not fit in {len(top)} tiles")
            tiles[top[col]] = _pack(cell, x0, 0, label.bg)
            tiles[bottom[col]] = _pack(cell, x0, 8, label.bg)
            col += 1
    for c in range(col, len(top)):                # pad the rest
        tiles[top[c]] = tiles[bottom[c]] = bytes([label.bg * 17]) * 32
    return tiles


def columns_needed(label):
    return sum(1 if font.is_narrow(ch) else (1 if len(label.rows) == 1 else 2) for ch in label.text)
