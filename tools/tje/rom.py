"""ROM-level constants and helpers for ToeJam & Earl (U) REV00."""
import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORIGINAL_ROM = os.path.join(ROOT, "Toejam & Earl (U) (REV00) [!].gen")
ORIGINAL_MD5 = "0a6af20d9c5b3ec4e23c683f083b92cd"

# Text is stored as NUL-terminated ASCII inside these data windows
# (item/menu/dialog, intro, credits, "press and hold start").
TEXT_WINDOWS = ((0x20000, 0x27000), (0x2A000, 0x2C000),
                (0x37900, 0x38100), (0x3AB00, 0x3AC00),
                (0xA19C, 0xA1AC),          # " pts"
                (0xA730, 0xA760),          # debug/present HUD labels
                (0xA9F40, 0xA9F82),        # rank names (RANK_NAMES)
                (0xABA00, 0xABE00),        # present names (13-char fields)
                (0xB710, 0xB730))          # "is on vacation"
RANK_NAMES = (0xA9F40, 0xA9F82)
TEXT_START = TEXT_WINDOWS[0][0]
TEXT_END = TEXT_WINDOWS[-1][1]


def in_text_window(addr):
    return any(lo <= addr < hi for lo, hi in TEXT_WINDOWS)

FONT_BASE = 0xAFB40          # 46 uncompressed 4bpp 8x8 glyph tiles
FONT_TILE_COUNT = 46
SPRITE_DEF_TEXT = 0xAFA98    # two 8-piece sprite definitions used by text objects
SPRITE_DEF_BUBBLE = 0xAFA6C  # tail piece + three 4-tile pieces (12 columns)
BUBBLE_PRINT = 0x1DFDC       # creates a speech-bubble text object (12 columns)
CHAR_TO_GLYPH = 0x9E0E       # ASCII -> glyph index
PRINT_ROUTINES = (0x27E16, 0x27EF0, 0x27FC6)
GLYPH_RENDERERS = (0x27BF6, 0x27CE4)
BUBBLE_RENDERER = 0x1DED8
PLANE_TEXT = 0x9F6A          # writes one name-table word per char at a preset VDP address
MENU_DRAW = 0x23A44          # draws every item of a menu table
VRAM_ALLOC_LIMIT = 0xD680    # cmpi.w #$50,d3 : number of 8-tile blocks in the sprite pool


def read_rom(path=ORIGINAL_ROM):
    with open(path, "rb") as fh:
        return fh.read()


def be32(data, off):
    return struct.unpack_from(">I", data, off)[0]


def be16(data, off):
    return struct.unpack_from(">H", data, off)[0]


def s16(data, off):
    return struct.unpack_from(">h", data, off)[0]
