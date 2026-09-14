import shutil
import struct

import pytest

from tools.tje import build, encode, strings
from tools.tje.rom import (BUBBLE_RENDERER, GLYPH_RENDERERS, MENU_DRAW,
                           PLANE_TEXT, PRINT_ROUTINES, SPRITE_DEF_BUBBLE,
                           SPRITE_DEF_TEXT, read_rom)

pytestmark = pytest.mark.skipif(shutil.which(build.toolchain("as")) is None,
                                reason="m68k binutils not available")


@pytest.fixture(scope="module")
def original():
    return read_rom()


@pytest.fixture(scope="module")
def sample_rom(original):
    return build.build({"02A1E6": "안녕,", "020376": "로켓 앞유리"}, original)


def test_rom_is_2mb_with_valid_header(sample_rom):
    assert len(sample_rom) == build.ROM_SIZE
    assert struct.unpack_from(">I", sample_rom, build.HEADER_ROM_END)[0] == build.ROM_SIZE - 1
    assert struct.unpack_from(">H", sample_rom, build.HEADER_CHECKSUM)[0] == build.checksum(sample_rom)


def test_renderer_hooks_point_into_expansion(sample_rom):
    for hook in GLYPH_RENDERERS:
        assert sample_rom[hook:hook + 2] == b"\x4e\xf9"
        target = struct.unpack_from(">I", sample_rom, hook + 2)[0]
        assert build.CODE_ADDR <= target < build.CODE_ADDR + build.CODE_LIMIT
        assert sample_rom[target:target + 4] == b"\x48\xe7\x3f\x30"   # movem.l d2-d7/a2-a3


def test_print_routines_use_16px_and_64_tiles(sample_rom, original):
    for base in PRINT_ROUTINES:
        for pattern, value in build.PRINT_PATCHES:
            at = original.find(pattern, base, base + build.PRINT_SPAN)
            assert at > 0
            assert sample_rom[at:at + 6] == pattern[:3] + bytes((value,)) + pattern[4:]
        sprites = original.find(b"\x15\x7c\x00\x08\x00\x2e", base, base + build.PRINT_SPAN)
        assert sample_rom[sprites:sprites + 6] == original[sprites:sprites + 6]   # 8 hardware sprites


def test_sprite_pieces_are_two_tiles_tall(sample_rom):
    for table in build.SPRITE_LISTS:
        for i in range(build.SPRITE_PIECES):
            piece = table + 4 + i * build.SPRITE_PIECE_SIZE
            assert sample_rom[piece] == 4 and sample_rom[piece + 1] == 2
            assert sample_rom[piece + 3] == build.SPRITE_Y


def test_fonts_are_installed(sample_rom):
    assert sample_rom[build.BLANK_ADDR:build.BLANK_ADDR + 64] == bytes(64)
    assert sample_rom[build.NARROW_ADDR + 64 * (ord("A") - 0x20):][:64] != bytes(64)
    assert sample_rom[build.WIDE_ADDR:build.WIDE_ADDR + 128] != bytes(128)


def test_short_translation_is_written_in_place(sample_rom):
    wide = encode.collect_wide_chars(["안녕,", "로켓 앞유리"])
    wide_map = {ch: i for i, ch in enumerate(wide)}
    data = encode.encode("안녕,", wide_map)
    assert sample_rom[0x2A1E6:0x2A1E6 + len(data)] == data
    assert sample_rom[0x2A1E6 + len(data):0x2A1F2] == bytes(0x2A1F2 - 0x2A1E6 - len(data))
    assert sample_rom[0x2A1F2:0x2A1F4] == b"My"      # neighbour untouched


def test_long_translation_is_relocated_and_pointer_rewritten(original):
    long_ko = "아주 긴 문자열입니다 정말로"      # 15 wide chars = 31 bytes > "rear leg"
    rom = build.build({"0203F2": long_ko}, original)
    entry = [e for e in strings.extract(original) if e.addr == 0x203F2][0]
    new_addr = struct.unpack_from(">I", rom, entry.refs[0].addr)[0]
    assert new_addr >= build.WIDE_ADDR
    wide = encode.collect_wide_chars([long_ko])
    assert encode.decode(rom[new_addr:new_addr + 40], wide) == long_ko
    assert rom[0x203F2:0x203F2 + 8] == b"rear leg"   # original left alone


def test_long_pcrel_string_becomes_pea_absolute(original):
    ko = "너무 길어서 안 들어가는 인사말"
    rom = build.build({"02A1E6": ko}, original)
    assert original[0x29DC4:0x29DCA] == b"\x48\x7a\x04\x20\x4e\x71"
    assert rom[0x29DC4:0x29DC6] == b"\x48\x79"
    new_addr = struct.unpack_from(">I", rom, 0x29DC6)[0]
    assert new_addr >= build.WIDE_ADDR
    assert encode.decode(rom[new_addr:new_addr + 64], encode.collect_wide_chars([ko])) == ko
    assert rom[0x29DCA:0x29DCC] == b"\x4e\x94"           # jsr (a4) untouched


def test_wrong_original_is_rejected(original):
    with pytest.raises(build.BuildError):
        build.build({}, original[:-1] + b"\x00")


def test_two_line_texts_are_spaced_at_least_16px(sample_rom, original):
    for site, (old, new) in build.LINE_SPACING.items():
        assert struct.unpack_from(">H", original, site - 6)[0] == old
        assert struct.unpack_from(">H", sample_rom, site - 6)[0] == new
    assert build.LINE_SPACING[0x29E48][1] - build.LINE_SPACING[0x29E38][1] >= 16


def test_speech_bubble_path_is_patched(sample_rom, original):
    assert sample_rom[BUBBLE_RENDERER:BUBBLE_RENDERER + 2] == b"\x4e\xf9"
    target = struct.unpack_from(">I", sample_rom, BUBBLE_RENDERER + 2)[0]
    assert build.CODE_ADDR <= target < build.CODE_ADDR + build.CODE_LIMIT
    at = original.find(build.BUBBLE_TILES_PATCH[0], 0x1DFDC, 0x1DFDC + 0x200)
    assert sample_rom[at + 3] == 25
    tail = SPRITE_DEF_BUBBLE + 4
    assert sample_rom[tail:tail + 4] == original[tail:tail + 4]          # tail piece unchanged
    for i in range(1, 4):
        piece = SPRITE_DEF_BUBBLE + 4 + i * build.SPRITE_PIECE_SIZE
        assert sample_rom[piece + 1] == 2 and sample_rom[piece + 3] == build.BUBBLE_TEXT_Y


def test_plane_text_hooks(sample_rom, original):
    for hook in (PLANE_TEXT, MENU_DRAW):
        assert sample_rom[hook:hook + 2] == b"\x4e\xf9"
        target = struct.unpack_from(">I", sample_rom, hook + 2)[0]
        assert build.CODE_ADDR <= target < build.CODE_ADDR + build.CODE_LIMIT
    for site, form, mode in build.CMD_HOOKS:
        assert sample_rom[site:site + 2] == b"\x4e\xb9"
        if form == "imm":
            assert sample_rom[site + 6:site + 10] == original[site + 2:site + 6]   # command kept inline
            assert sample_rom[site + 10:site + 12] == original[site + 10:site + 12]
        else:
            assert sample_rom[site + 6:site + 8] == original[site + 6:site + 8]


def test_sprite_vram_pool_is_shrunk_for_hud_glyphs(sample_rom):
    from tools.tje.rom import VRAM_ALLOC_LIMIT
    assert sample_rom[VRAM_ALLOC_LIMIT:VRAM_ALLOC_LIMIT + 4] == b"\x0c\x43\x00\x40"


def test_text_strip_piece_lists_and_fixup(sample_rom, original):
    from tools.tje.rom import PRINT_ROUTINES
    lists = sample_rom[build.PIECE_LISTS_ADDR:build.PIECE_LISTS_ADDR + 16 * build.PIECE_LIST_SIZE]
    three = lists[2 * build.PIECE_LIST_SIZE:3 * build.PIECE_LIST_SIZE]
    assert three[:4] == b"\x03\x00\x00\x00"
    xs = [struct.unpack_from(">b", three, 4 + i * 10 + 2)[0] for i in range(3)]
    assert xs == [-48, -16, 16]                        # centred, 32px apart
    assert all(three[4 + i * 10:4 + i * 10 + 2] == b"\x04\x02" for i in range(3))
    alt = lists[10 * build.PIECE_LIST_SIZE:11 * build.PIECE_LIST_SIZE]   # 3 pieces, flag 3
    assert alt[4 + 5] == 3 and three[4 + 5] == 1
    for base, sprite_def in zip(PRINT_ROUTINES, (0xAFA98, 0xAFA98, 0xAFAEC)):
        at = original.find(b"\x25\x7c" + struct.pack(">I", sprite_def) + b"\x00\x22", base, base + build.PRINT_SPAN)
        assert sample_rom[at:at + 2] == b"\x4e\xb9" and sample_rom[at + 6:at + 8] == b"\x4e\x71"
        at = original.find(b"\x48\x79" + struct.pack(">I", sprite_def), base, base + build.PRINT_SPAN)
        assert sample_rom[at:at + 6] == b"\x2f\x2a\x00\x22\x4e\x71"


def test_bubble_translation_over_12_columns_is_rejected(original):
    with pytest.raises(build.BuildError):
        build.build({"026890": "너무 길어서 말풍선에 안 맞아요"}, original)
    build.build({"026890": "여섯글자까지만"[:6]}, original)


def test_all_csv_translations_build(original):
    import os
    translations = build.load_translations(os.path.join(build.ROOT, "translations", "strings.csv"))
    rom = build.build(translations, original)
    assert len(rom) == build.ROM_SIZE
