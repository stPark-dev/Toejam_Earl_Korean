"""Assemble the Korean ROM.

Layout of the expansion area (ROM grows from 1MB to 2MB):
  0x100000  renderer code (from asm/text.s)
  0x100C00  sprite piece lists for text strips of 1..8 pieces (two flag variants)
  0x101200  64 zero bytes: the blank column glyph
  0x101300  narrow (ASCII) font, 95 glyphs x 64 bytes
  0x101180  Korean present-name pointer table (28 entries)
  0x103000  wide (Hangul) font, N glyphs x 128 bytes
  after     8x8 HUD glyphs (N x 32), plane-palette narrow/wide fonts, relocated strings
"""
import hashlib
import os
import shutil
import struct
import subprocess
import tempfile

from . import encode, font, labels, strings
from .rom import (BONUS_HITOPS_GLYPH, BUBBLE_PRINT, BUBBLE_RENDERER, GLYPH_RENDERERS,
                  MENU_DRAW, ORIGINAL_MD5, ORIGINAL_ROM, PLANE_TEXT, PRESENT_NAMES_ASCII,
                  PRESENT_NAMES_GLYPH, PRESENT_NAMES_KO, PRESENT_UNKNOWN_ASCII,
                  PRESENT_UNKNOWN_GLYPH,
                  PRINT_ROUTINES, ROOT, SPRITE_DEF_BUBBLE, SPRITE_DEF_TEXT,
                  VRAM_ALLOC, VRAM_ALLOC_LIMIT, read_rom)

ROM_SIZE = 0x200000
CODE_ADDR = 0x100000
CODE_LIMIT = 0xC00
PIECE_LISTS_ADDR = 0x100C00
PIECE_LIST_SIZE = 84
BLANK_ADDR = 0x101200
NARROW_ADDR = 0x101300
WIDE_ADDR = 0x103000
ASM_SOURCE = os.path.join(ROOT, "tools", "tje", "asm", "text.s")

# Instructions inside each print routine whose immediate we change
# (searched within PRINT_SPAN bytes of the routine start): object height
# $2a 8 -> 16, VRAM tiles $2b $20 -> $40. $2e is the hardware sprite count
# (8 pieces) and must stay as it is.
PRINT_PATCHES = ((b"\x15\x7c\x00\x08\x00\x2a", 0x10),
                 (b"\x15\x7c\x00\x20\x00\x2b", 0x40))
PRINT_SPAN = 0xE0
SPRITE_PIECE_SIZE = 10
SPRITE_PIECES = 8
SPRITE_LISTS = (SPRITE_DEF_TEXT, SPRITE_DEF_TEXT + 4 + SPRITE_PIECES * SPRITE_PIECE_SIZE)
SPRITE_Y = 0xF4            # was 0xF8: keep the taller cell centred on the old row
# Speech bubble: piece 0 is the 1x1 tail, pieces 1-3 hold the 12 text columns.
BUBBLE_TILES_PATCH = (b"\x15\x7c\x00\x0d\x00\x2b", 0x19)   # 13 -> 25 tiles
BUBBLE_TEXT_Y = 0xC8       # was 0xD0: grow upwards so the tail stays put

# `pea #y` sites of two-line texts drawn 10-13px apart; 16px glyphs need
# more room. Keyed by the address of the `pea (d16,pc)` / `pea abs.l`
# string reference; values are (old y, new y).
LINE_SPACING = {
    0x29E38: (72, 68), 0x29E48: (84, 86),      # And this here is my Bro / Big Rappin Earl.
    0x29EFE: (72, 68), 0x29F0E: (84, 86),      # Earl and myself are / highly funky aliens
    0x2A074: (72, 68), 0x2A084: (84, 86),      # we are from / the Planet Funkotron.
    0x2A69A: (72, 68), 0x2A6AE: (84, 86),      # Recently, we ran into / a small problem
    0x2A96E: (30, 26), 0x2A982: (40, 44),      # When big Earl said / he'd like a shot
    0x2B8B6: (72, 68), 0x2B8C6: (84, 86),      # chillin' out on / the most insane planet
    0x2BA82: (72, 68), 0x2BA92: (84, 86),      # is find the 10 pieces / of our Rocketship,
    0x2BB10: (72, 68), 0x2BB20: (84, 86),      # and we can / Jet Outta here.
    0x37D14: (35, 32), 0x37D24: (48, 50),      # credits pairs
    0x37D46: (35, 32), 0x37D56: (45, 50),
    0x37D74: (35, 32), 0x37D84: (48, 50),
    0x37D96: (35, 32), 0x37DA6: (45, 50),
    0x37DB8: (35, 32), 0x37DC8: (45, 50),
    0x37DDC: (35, 32), 0x37DEC: (45, 50),
    0x37E0C: (35, 32), 0x37E1C: (48, 50),
    0x37E32: (35, 32),
}

# Plane text: every `move.l ..., $C00004` that positions a text write is
# redirected to a set_cmd stub (see asm/text.s). (site, form, mode):
# form d0/d1 = 6-byte register write, imm = 10-byte immediate write;
# mode 0 keeps the original 8x8 HUD font, 1/2 render Korean two-row text.
CMD_HOOKS = (
    (0x23A70, "d1", 1),                                   # menu items
    (0x2034E, "d1", 2),                                   # centred level message
    (0x204BE, "imm", 2), (0x204D6, "imm", 2), (0x204E8, "imm", 2),
    (0x2050E, "imm", 2), (0x20524, "imm", 2), (0x20536, "imm", 2),
    (0x2054A, "imm", 2),                                  # missing-pieces count
    (0x234F0, "imm", 2),                                  # game over
    (0x2391E, "imm", 2),                                  # need two controllers
    (0xA056, "d0", 0), (0xA08E, "d0", 0), (0xA106, "d0", 0), (0xA152, "d0", 0),
    (0xA128, "imm", 0), (0xA178, "imm", 0),               # HUD points / rank
    (0xA4E4, "d0", 0), (0xA69A, "d0", 0),                 # present list HUD
    (0xB64A, "imm", 0), (0xB688, "imm", 0), (0xB6A2, "imm", 0), (0xB6B6, "imm", 0),
    (0xB6C8, "imm", 0), (0xB6E4, "imm", 0), (0xB6F8, "imm", 0),   # "is on vacation"
)
# 8x8 Korean HUD text (rank names, present list). Glyph tiles now travel
# through the game's staging buffer / VBlank DMA queue instead of being
# written mid-row, which removed the dependence on tracking the VDP address.
HUD_KOREAN = True
# Sprite VRAM pool keeps all 0x50 blocks: the intro alone uses up to 69.
# Glyph rings for HUD/message text live in the unused VRAM at 0xC000.
POOL_BLOCKS = 0x50
# Strings drawn by the legacy HUD path; ignored unless HUD_KOREAN.
HUD_RANGES = ((0xA19C, 0xA1AC), (0xA730, 0xA760), (0xA9F40, 0xA9F82),
              (0xABA00, 0xABE00), (0xB710, 0xB730))
PRESENT_LOOP = 0xA536       # 32-byte loop writing 13 pre-mapped glyph words
PRESENT_LOOP_END = 0xA5C4
PRESENT_FIELD = 13
PRESENT_NAME_RANGE = (0xABC42, 0xABDBC)
VDP_CTRL = b"\x00\xc0\x00\x04"
VDP_DATA = b"\x00\xc0\x00\x00"

HEADER_ROM_END = 0x1A4
HEADER_CHECKSUM = 0x18E


# Speech bubbles (strings in the dialog tables) are capped at 12 columns by
# the game; the prompt strings near 0x21000-0x24000 go through the same path.
BUBBLE_RANGES = ((0x26890, 0x26DE0), (0x21000, 0x24000),
                 # one-off bubbles that live inline in code
                 (0x9318, 0x9325), (0x9CFA, 0x9D0D), (0xF8B6, 0xF8BD),
                 (0x111B2, 0x111C7), (0x11FFE, 0x12008), (0x152C0, 0x152C6),
                 (0x155B2, 0x155BE), (0x168AC, 0x168B2), (0x1721A, 0x17223),
                 (0x17468, 0x17474), (0x19CF2, 0x19CFC), (0x1B2CE, 0x1B2D5),
                 (0x1B57C, 0x1B588), (0x1BB14, 0x1BB20))
BUBBLE_COLUMNS = 12
NOT_BUBBLES = frozenset((0x235CE, 0x23A1E))     # game over / two controllers: plane text


class BuildError(Exception):
    pass


def toolchain(tool):
    prefix = os.environ.get("M68K_BIN", "")
    return os.path.join(prefix, "m68k-linux-gnu-" + tool) if prefix else "m68k-linux-gnu-" + tool


def piece_list(pieces, flag):
    """Sprite piece list (game format) for a centred strip of 4x2-tile pieces."""
    data = bytes((pieces, 0, 0, 0))          # piece count lives in the first byte
    for i in range(pieces):
        x = -(pieces * 32) // 2 + i * 32
        data += bytes((4, 2)) + struct.pack(">bB", x, SPRITE_Y) + bytes((0, flag, 0, 0, 0, 0))
    return data + bytes(PIECE_LIST_SIZE - len(data))


def piece_lists():
    """Lists 1..8 with flag 1 (as 0xAFA98) then 1..8 with flag 3 (as 0xAFAEC)."""
    return b"".join(piece_list(n, flag) for flag in (1, 3) for n in range(1, 9))


def assemble(narrow, wide, hud, blank, narrow_plane=0, wide_plane=0):
    """Assemble and link text.s at CODE_ADDR; returns (binary, symbols).

    Linking matters: gas leaves branches to .globl symbols as relocations,
    so an unlinked objcopy would drop them and leave zero displacements.
    """
    with tempfile.TemporaryDirectory() as tmp:
        obj = os.path.join(tmp, "text.o")
        elf = os.path.join(tmp, "text.elf")
        binary = os.path.join(tmp, "text.bin")
        subprocess.run([toolchain("as"), "-m68000",
                        f"--defsym=NARROW_FONT={narrow}", f"--defsym=WIDE_FONT={wide}",
                        f"--defsym=HUD_FONT={hud}",
                        f"--defsym=NARROW_PLANE={narrow_plane}", f"--defsym=WIDE_PLANE={wide_plane}",
                        f"--defsym=BLANK_GLYPH={blank}", f"--defsym=PIECE_LISTS={PIECE_LISTS_ADDR}",
                        "-o", obj, ASM_SOURCE], check=True)
        subprocess.run([toolchain("ld"), f"-Ttext={CODE_ADDR:#x}", "-e", "render_remap",
                        "-o", elf, obj], check=True)
        subprocess.run([toolchain("objcopy"), "-O", "binary", "-j", ".text", elf, binary], check=True)
        nm = subprocess.run([toolchain("nm"), elf], check=True, capture_output=True, text=True).stdout
        symbols = {}
        for line in nm.splitlines():
            value, kind, name = line.split()
            if kind in "Tt":
                symbols[name] = int(value, 16) - CODE_ADDR
        return open(binary, "rb").read(), symbols


def expect(rom, addr, original):
    if rom[addr:addr + len(original)] != original:
        raise BuildError(f"unexpected bytes at {addr:06X}: {rom[addr:addr + len(original)].hex()}")


def patch(rom, addr, data, original=None):
    if original is not None:
        expect(rom, addr, original)
    rom[addr:addr + len(data)] = data


def patch_engine(rom, code, symbols):
    """Install the renderer, taller text objects and 16px sprite pieces."""
    if len(code) > CODE_LIMIT:
        raise BuildError("renderer code too large")
    patch(rom, CODE_ADDR, code)
    for hook, symbol in zip(GLYPH_RENDERERS, ("render_remap", "render_raw")):
        patch(rom, hook, b"\x4e\xf9" + struct.pack(">I", CODE_ADDR + symbols[symbol]),
              original=b"\x48\xe7\x3f\x20\x26\x2f\x00\x20")
    lists = piece_lists()
    assert PIECE_LISTS_ADDR + len(lists) <= BLANK_ADDR
    rom[PIECE_LISTS_ADDR:PIECE_LISTS_ADDR + len(lists)] = lists
    for base in PRINT_ROUTINES:
        for pattern, value in PRINT_PATCHES:
            at = rom.find(pattern, base, base + PRINT_SPAN)
            if at < 0:
                raise BuildError(f"print routine at {base:06X} lacks {pattern.hex()}")
            rom[at + 3] = value
        # move.l #list,$22(a2) -> jsr fixup_text_object[_alt] ; nop
        for sprite_def, fixup in ((SPRITE_LISTS[0], "fixup_text_object"), (SPRITE_LISTS[1], "fixup_text_object_alt")):
            store = b"\x25\x7c" + struct.pack(">I", sprite_def) + b"\x00\x22"
            at = rom.find(store, base, base + PRINT_SPAN)
            if at >= 0:
                break
        else:
            raise BuildError(f"print routine at {base:06X} lacks the piece list store")
        rom[at:at + 8] = jsr(symbols, fixup) + b"\x4e\x71"
        # pea #list (argument of the sprite setup call) -> move.l $22(a2),-(a7) ; nop
        at = rom.find(b"\x48\x79" + struct.pack(">I", sprite_def), base, base + PRINT_SPAN)
        if at < 0:
            raise BuildError(f"print routine at {base:06X} lacks the piece list argument")
        rom[at:at + 6] = b"\x2f\x2a\x00\x22\x4e\x71"
    # The original 8-piece lists at 0xAFA98/0xAFAEC stay untouched: text
    # objects now get their own lists from fixup_text_object, and other
    # objects (the intro's space scene among them) still use the originals.
    for table in SPRITE_LISTS:
        expect(rom, table, b"\x08\x00\x00\x00")
    # speech bubbles
    patch(rom, BUBBLE_RENDERER, b"\x4e\xf9" + struct.pack(">I", CODE_ADDR + symbols["render_bubble"]),
          original=b"\x48\xe7\x3f\x30\x26\x2f\x00\x24")
    pattern, value = BUBBLE_TILES_PATCH
    at = rom.find(pattern, BUBBLE_PRINT, BUBBLE_PRINT + 0x200)
    if at < 0:
        raise BuildError("bubble print routine lacks the tile-count immediate")
    rom[at + 3] = value
    expect(rom, SPRITE_DEF_BUBBLE, b"\x04\x00\x00\x00\x01\x01\x08\xd8")
    for i in range(1, 4):
        piece = SPRITE_DEF_BUBBLE + 4 + i * SPRITE_PIECE_SIZE
        patch(rom, piece + 1, b"\x02", original=b"\x01")
        patch(rom, piece + 3, bytes((BUBBLE_TEXT_Y,)), original=b"\xd0")


def jsr(symbols, name):
    return b"\x4e\xb9" + struct.pack(">I", CODE_ADDR + symbols[name])


def jmp(symbols, name):
    return b"\x4e\xf9" + struct.pack(">I", CODE_ADDR + symbols[name])


def patch_plane_text(rom, symbols):
    """Route menu and message text through the two-row plane renderer."""
    patch(rom, PLANE_TEXT, jmp(symbols, "plane_text"), original=b"\x2f\x0a\x24\x6f\x00\x08")
    patch(rom, MENU_DRAW, jmp(symbols, "menu_begin"), original=b"\x48\xe7\x38\x20\x24\x6f\x00\x14")
    for site, form, mode in CMD_HOOKS:
        stub = jsr(symbols, f"set_cmd_{form}_m{mode}")
        if form == "imm":
            expect(rom, site, b"\x23\xfc")
            expect(rom, site + 6, VDP_CTRL)
            patch(rom, site, stub + rom[site + 2:site + 6])
        else:
            reg = int(form[1])
            patch(rom, site, stub, original=bytes((0x23, 0xC0 | reg)) + VDP_CTRL)
    expect(rom, VRAM_ALLOC_LIMIT, b"\x0c\x43\x00\x50")
    patch(rom, VRAM_ALLOC, jmp(symbols, "vram_alloc_hook"), original=b"\x48\xe7\x38\x00\x32\x2f\x00\x12")


def patch_present_list(rom, symbols):
    """Present list: draw names from the Korean pointer table via plane_text."""
    patch(rom, 0xA51E + 2, struct.pack(">I", PRESENT_UNKNOWN_ASCII),
          original=struct.pack(">I", PRESENT_UNKNOWN_GLYPH))
    patch(rom, 0xA52C + 2, struct.pack(">I", PRESENT_NAMES_KO),
          original=struct.pack(">I", PRESENT_NAMES_GLYPH))
    expect(rom, PRESENT_LOOP, b"\x42\x41\x10\x18")               # clr.w d1 ; move.b (a0)+,d0
    expect(rom, PRESENT_LOOP + 0x1E, b"\x60\xe2")                 # bra.b back to the loop
    code = b"\x48\x50" + jsr(symbols, "plane_text_pad13") + b"\x58\x8f"    # pea (a0); jsr; addq.l #4,sp
    branch = PRESENT_LOOP_END - (PRESENT_LOOP + len(code) + 2)
    code += b"\x60\x00" + struct.pack(">h", branch)                # bra.w PRESENT_LOOP_END
    code += b"\x4e\x71" * ((0x20 - len(code)) // 2)
    rom[PRESENT_LOOP:PRESENT_LOOP + 0x20] = code
    table = b"".join(struct.pack(">I", struct.unpack_from(">I", rom, PRESENT_NAMES_ASCII + i * 4)[0])
                     for i in range(27)) + struct.pack(">I", BONUS_HITOPS_GLYPH)
    rom[PRESENT_NAMES_KO:PRESENT_NAMES_KO + len(table)] = table


def add_present_table_refs(rom, entries):
    """Present names are also pointed to by the new table; relocation must update it."""
    targets = {struct.unpack_from(">I", rom, PRESENT_NAMES_ASCII + i * 4)[0]: i for i in range(27)}
    for entry in entries:
        if entry.addr in targets:
            entry.refs.append(strings.Ref(PRESENT_NAMES_KO + targets[entry.addr] * 4, "abs32"))


def patch_labels(rom):
    """Overwrite graphic text tiles (HUD labels, present-list title) with Korean."""
    for label in labels.LABELS:
        if labels.columns_needed(label) > len(label.rows[0]):
            raise BuildError(f"label {label.text!r} needs more tiles than it has")
        for idx, data in labels.render_label(label).items():
            at = label.asset + idx * 32
            if not any(rom[at:at + 32]):
                raise BuildError(f"label tile {idx} of asset {label.asset:06X} is empty; wrong slot?")
            rom[at:at + 32] = data


def patch_line_spacing(rom):
    """Move the y immediates of stacked two-line texts apart."""
    for site, (old, new) in LINE_SPACING.items():
        patch(rom, site - 8, b"\x48\x78" + struct.pack(">H", new),
              original=b"\x48\x78" + struct.pack(">H", old))


def slot_size(rom, entry):
    """Bytes available in place: the text plus its terminator(s)."""
    end = entry.addr + len(entry.text)
    while rom[end] == 0 and end < entry.addr + len(entry.text) + 2:
        end += 1
    return end - entry.addr


def place_strings(rom, entries, translations, wide_map, free_addr):
    """Write translated strings, in place when they fit, else relocated.

    Absolute pointers are rewritten. A `pea (d16,pc)` reference is turned
    into `pea abs.l`, which needs the `nop` the compiler left after it.
    Returns the next free address.
    """
    for entry in entries:
        ko = translations.get(entry.key, "")
        if not ko:
            continue
        if not HUD_KOREAN and any(lo <= entry.addr < hi for lo, hi in HUD_RANGES):
            continue
        if any(lo <= entry.addr < hi for lo, hi in BUBBLE_RANGES) \
                and encode.columns(ko) > BUBBLE_COLUMNS and entry.addr not in NOT_BUBBLES:
            raise BuildError(f"{entry.key} {ko!r} is {encode.columns(ko)} columns; bubbles allow {BUBBLE_COLUMNS}")
        if (PRESENT_NAME_RANGE[0] <= entry.addr < PRESENT_NAME_RANGE[1] or entry.addr == BONUS_HITOPS_GLYPH) \
                and encode.columns(ko) > PRESENT_FIELD:
            raise BuildError(f"{entry.key} {ko!r} is {encode.columns(ko)} columns; present names allow {PRESENT_FIELD}")
        data = encode.encode(ko, wide_map)
        size = slot_size(rom, entry)
        if len(data) < size:            # < , not <=: the terminator needs a byte
            rom[entry.addr:entry.addr + size] = data + bytes(size - len(data))
            continue
        free_addr += free_addr & 1
        rom[free_addr:free_addr + len(data)] = data
        for ref in entry.refs:
            if ref.kind == "abs32":
                expect(rom, ref.addr, struct.pack(">I", entry.addr))
                rom[ref.addr:ref.addr + 4] = struct.pack(">I", free_addr)
            else:
                expect(rom, ref.addr, b"\x48\x7a")
                if rom[ref.addr + 4:ref.addr + 6] != b"\x4e\x71":
                    raise BuildError(f"{entry.key}: pcrel ref at {ref.addr:06X} has no nop to absorb")
                rom[ref.addr:ref.addr + 6] = b"\x48\x79" + struct.pack(">I", free_addr)
        free_addr += len(data)
    return free_addr


def checksum(rom):
    total = 0
    for off in range(0x200, len(rom), 2):
        total += struct.unpack_from(">H", rom, off)[0]
    return total & 0xFFFF


def fix_header(rom):
    struct.pack_into(">I", rom, HEADER_ROM_END, len(rom) - 1)
    struct.pack_into(">H", rom, HEADER_CHECKSUM, checksum(rom))


def build(translations, original=None):
    """Return the patched 2MB ROM as bytes. translations: {id: korean}."""
    original = original if original is not None else read_rom(ORIGINAL_ROM)
    if hashlib.md5(original).hexdigest() != ORIGINAL_MD5:
        raise BuildError("original ROM checksum mismatch")
    rom = bytearray(original) + bytes(ROM_SIZE - len(original))
    entries = strings.extract(original)
    wide_chars = encode.collect_wide_chars(translations.values())
    wide_map = {ch: i for i, ch in enumerate(wide_chars)}
    wide = font.wide_table(wide_chars)
    hud = font.hud_table(wide_chars)
    hud_addr = WIDE_ADDR + len(wide)
    narrow_plane = font.narrow_table(plane=True)
    wide_plane = font.wide_table(wide_chars, plane=True)
    narrow_plane_addr = hud_addr + len(hud)
    wide_plane_addr = narrow_plane_addr + len(narrow_plane)
    code, symbols = assemble(NARROW_ADDR, WIDE_ADDR, hud_addr, BLANK_ADDR, narrow_plane_addr, wide_plane_addr)
    patch_engine(rom, code, symbols)
    patch_plane_text(rom, symbols)
    if HUD_KOREAN:
        patch_present_list(rom, symbols)
        add_present_table_refs(rom, entries)
    patch_line_spacing(rom)
    if HUD_KOREAN:
        patch_labels(rom)
    rom[BLANK_ADDR:BLANK_ADDR + 64] = bytes(64)
    narrow = font.narrow_table()
    assert NARROW_ADDR + len(narrow) <= WIDE_ADDR
    rom[NARROW_ADDR:NARROW_ADDR + len(narrow)] = narrow
    rom[WIDE_ADDR:WIDE_ADDR + len(wide)] = wide
    rom[hud_addr:hud_addr + len(hud)] = hud
    rom[narrow_plane_addr:narrow_plane_addr + len(narrow_plane)] = narrow_plane
    rom[wide_plane_addr:wide_plane_addr + len(wide_plane)] = wide_plane
    place_strings(rom, entries, translations, wide_map, wide_plane_addr + len(wide_plane))
    fix_header(rom)
    return bytes(rom)


def load_translations(csv_path):
    return {row["id"]: row["ko"] for row in strings.read_csv(csv_path) if row["ko"]}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(ROOT, "translations", "strings.csv"))
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "tje_ko.gen"))
    args = ap.parse_args()
    translations = load_translations(args.csv)
    rom = build(translations)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "wb") as fh:
        fh.write(rom)
    print(f"wrote {args.out} ({len(rom)} bytes, {len(translations)} translated strings)")


if __name__ == "__main__":
    main()
