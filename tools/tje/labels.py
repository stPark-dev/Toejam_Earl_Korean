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


# Active label replacements. The HUD panel labels ("toEJaM iS A", "EaRL iS")
# are kept in the original lettering: 7px Hangul in 8x8 tiles turned out too
# hard to read next to the original artwork.
LABELS = ()

# The present list's "OPEN" title (asset 0xABF0A, tiles 1-18) is animated by
# copying pixel rows, not whole tiles, so replacing its tiles scrambles it.
# Kept here for a later pass that rewrites the copy routine.
DEFERRED_LABELS = (
    # "toEJaM iS A" (rank name follows at run time); the asset loads at VRAM 0x588
    Label(HUD_ASSET, ((23, 24, 25, 26, 27, 28, 29),), "토잼 등급", bg=0xD, ink=0x5),
    # "EaRL iS" ("휴가 / 중" follows at run time); tile 28 is shared and stays blank
    Label(HUD_ASSET, ((30, 31, 32, 38),), "얼은", bg=0xF, ink=0x9),
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
