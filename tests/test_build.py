import os
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


def test_original_sprite_piece_lists_are_untouched(sample_rom, original):
    for table in build.SPRITE_LISTS:
        end = table + 4 + build.SPRITE_PIECES * build.SPRITE_PIECE_SIZE
        assert sample_rom[table:end] == original[table:end]


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


def test_sprite_vram_pool_keeps_its_full_size(sample_rom):
    from tools.tje.rom import VRAM_ALLOC_LIMIT
    assert sample_rom[VRAM_ALLOC_LIMIT:VRAM_ALLOC_LIMIT + 4] == b"\x0c\x43\x00\x50"


def test_hud_strings_stay_english_when_hud_korean_is_off(original, monkeypatch):
    monkeypatch.setattr(build, "HUD_KOREAN", False)
    rom = build.build({"0A9F48": "위너", "0ABC42": "이카루스 날개", "0ABBB6": "보너스 하이탑"}, original)
    assert rom[0xA9F48:0xA9F4E] == b"wiener"
    assert rom[0xA536:0xA556] == original[0xA536:0xA556]        # present-name loop untouched
    assert rom[0xABBB6:0xABBC3] == original[0xABBB6:0xABBC3]    # pre-mapped glyph string intact


def test_present_list_reads_korean_name_table(original):
    from tools.tje.rom import PRESENT_NAMES_ASCII, PRESENT_NAMES_KO, PRESENT_UNKNOWN_ASCII
    assert build.HUD_KOREAN
    rom = build.build({"0ABC42": "이카루스 날개", "0ABBB6": "보너스 하이탑"}, original)
    assert struct.unpack_from(">I", rom, 0xA52C + 2)[0] == PRESENT_NAMES_KO
    assert struct.unpack_from(">I", rom, 0xA51E + 2)[0] == PRESENT_UNKNOWN_ASCII
    assert rom[build.PRESENT_LOOP:build.PRESENT_LOOP + 2] == b"\x48\x50"           # pea (a0)
    assert rom[build.PRESENT_LOOP + 10:build.PRESENT_LOOP + 12] == b"\x60\x00"    # bra.w
    table = [struct.unpack_from(">I", rom, PRESENT_NAMES_KO + i * 4)[0] for i in range(28)]
    # entry 1 untouched: still the original ASCII string; entries 0 and 27 relocated
    assert table[1] == struct.unpack_from(">I", original, PRESENT_NAMES_ASCII + 4)[0]
    wide = encode.collect_wide_chars(["이카루스 날개", "보너스 하이탑"])
    assert encode.decode(rom[table[0]:table[0] + 20], wide) == "이카루스 날개"
    assert encode.decode(rom[table[27]:table[27] + 20], wide) == "보너스 하이탑"
    with pytest.raises(build.BuildError):
        build.build({"0ABC42": "열세 열을 넘는 선물 이름"}, original)


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


def test_internal_branch_to_global_symbol_is_resolved(original):
    """plane_text_pad13 calls plane_text with bsr; the displacement must not be 0."""
    code, symbols = build.assemble(build.NARROW_ADDR, build.WIDE_ADDR, 0x110000, build.BLANK_ADDR)
    at = symbols["plane_text_pad13"] + 4              # after move.l 4(sp),-(sp)
    assert code[at:at + 2] == b"\x61\x00"             # bsr.w
    disp = struct.unpack_from(">h", code, at + 2)[0]
    assert disp != 0 and at + 2 + disp == symbols["plane_text"]


def test_plane_text_uses_its_own_palette_tables(sample_rom):
    from tools.tje import font
    wide = encode.collect_wide_chars(["안녕,", "로켓 앞유리"])
    sprite_tbl = font.wide_table(wide)
    plane_tbl = font.wide_table(wide, plane=True)
    assert sample_rom.find(sprite_tbl) == build.WIDE_ADDR
    plane_at = sample_rom.find(plane_tbl)
    assert plane_at > build.WIDE_ADDR
    # the Korean plane renderer must add the plane table address, the sprite one the sprite table
    assert sample_rom.find(b"\x06\x80" + struct.pack(">I", plane_at), build.CODE_ADDR, build.CODE_ADDR + build.CODE_LIMIT) > 0
    assert sample_rom.find(b"\x06\x80" + struct.pack(">I", build.WIDE_ADDR), build.CODE_ADDR, build.CODE_ADDR + build.CODE_LIMIT) > 0


def test_hud_glyph_uploads_go_through_the_staging_queue(original):
    """The HUD path must not touch the VDP control port; it stages tiles via 0xCAFC."""
    code, symbols = build.assemble(build.NARROW_ADDR, build.WIDE_ADDR, 0x110000, build.BLANK_ADDR)
    hud = code[symbols["plane_text"]:symbols["pt_korean"]]
    assert b"\x00\xc0\x00\x04" not in hud                       # no $C00004 writes
    assert b"\x4e\xb9\x00\x00\xca\xfc" in code[symbols["stage_glyph"]:symbols["flush_pending"]]


def test_inline_bubbles_are_extracted_and_translated(original):
    """Bubbles that sit inline in code, not in the dialog tables.

    They were invisible to the extractor until their addresses were added to
    TEXT_WINDOWS, so every one of them stayed English in the built ROM.
    """
    inline = {0x9318: "Thanks a lot", 0x9CFA: "Got it!", 0x9D02: "Need Bucks",
              0xF8B6: "Bummer", 0x111B2: "Bye Toejam", 0x111BE: "Bye Earl",
              0x11FFE: "Awesome!!", 0x152C0: "yummm", 0x155B2: "I'm stuffed",
              0x168AC: "Bogus", 0x1721A: "Uh oh?!?", 0x17468: "rosebushes!",
              0x19CF2: "shut up!!", 0x1B2CE: "Youch!", 0x1B57C: "Hubba hubba",
              0x1BB14: "I feel sick"}
    found = {e.addr: e.text for e in strings.extract(original)}
    translations = build.load_translations(os.path.join(build.ROOT, "translations", "strings.csv"))
    for addr, text in inline.items():
        assert found.get(addr) == text, f"{addr:06X} is not extracted"
        ko = translations.get(f"{addr:06X}", "")
        assert ko, f"{addr:06X} {text!r} has no translation"
        assert encode.columns(ko) <= build.BUBBLE_COLUMNS
    # the second, plain-ASCII rank table (pointer table at 0xA9FEC)
    for addr in (0xA9FB1, 0xA9FB7, 0xA9FC2, 0xA9FC9, 0xA9FCE, 0xA9FD2, 0xA9FD8, 0xA9FE2):
        assert translations.get(f"{addr:06X}", ""), f"{addr:06X} has no translation"


def test_in_place_translation_keeps_room_for_the_terminator(original):
    """A translation that exactly fills its slot must relocate, not lose its NUL."""
    entry = next(e for e in strings.extract(original) if e.addr == 0x9CFA)   # "Got it!"
    assert build.slot_size(original, entry) == len(entry.text) + 1


def test_bubble_strip_carries_both_tile_and_column_counts():
    """`|` is a comment in gas: BUBBLE_STRIP must still hold 12 in its low word.

    With a zero column count the bubble skips its padding, stages fewer tiles
    than it queues and leaves stale VRAM after the text (and desyncs the DMA
    queue for every strip behind it).
    """
    code, symbols = build.assemble(build.NARROW_ADDR, build.WIDE_ADDR, 0x110000, build.BLANK_ADDR)
    entry = code[symbols["render_bubble"]:symbols["render_body"]]
    at = entry.find(b"&<")                            # move.l #imm,d3
    assert at >= 0
    assert struct.unpack_from(">HH", entry, at + 2) == (25, 12)


def test_graphic_labels_are_rewritten(sample_rom, original):
    from tools.tje import labels
    for label in labels.DEFERRED_LABELS:          # untouched until the copy routine is handled
        for idx in label.rows[0]:
            at = label.asset + idx * 32
            assert sample_rom[at:at + 32] == original[at:at + 32]
    for label in labels.LABELS:
        tiles = labels.render_label(label)
        for idx, data in tiles.items():
            at = label.asset + idx * 32
            assert sample_rom[at:at + 32] == data
            assert any(original[at:at + 32])
    # rendering still works for the deferred labels (palette stays within the declared indices)
    for label in labels.DEFERRED_LABELS:
        tiles = labels.render_label(label)
        nibbles = {b >> 4 for d in tiles.values() for b in d} | {b & 15 for d in tiles.values() for b in d}
        allowed = {label.bg, label.ink} | ({label.outline} if label.outline is not None else set())
        assert nibbles <= allowed


def test_vram_allocator_hook_bumps_strip_cache_generation(sample_rom):
    from tools.tje.rom import VRAM_ALLOC
    assert sample_rom[VRAM_ALLOC:VRAM_ALLOC + 2] == b"\x4e\xf9"
    target = struct.unpack_from(">I", sample_rom, VRAM_ALLOC + 2)[0]
    code = sample_rom[target:target + 20]
    assert code[:6] == b"\x52\x79\x00\xff\xef\xf4"          # addq.w #1,ALLOC_GEN
    assert code[6:10] == b"\x48\xe7\x38\x00"                    # displaced movem
    assert code[14:20] == b"\x4e\xf9\x00\x00\xd6\x18"          # jmp back


def test_renderer_refuses_unallocated_vram_slots(original):
    code, symbols = build.assemble(build.NARROW_ADDR, build.WIDE_ADDR, 0x110000, build.BLANK_ADDR)
    body = code[symbols["render_body"]:symbols["render_skip"]]
    assert b"\x04\x40\x02\x80" in body                  # subi.w #0x280,d0
    assert b"\x00\xff\xd9\x76" in body                  # VRAM allocator bitmap
    assert build.POOL_BLOCKS == 0x50
    alloc = code[symbols["alloc_glyph"]:symbols["ag_hit"]]
    assert b"\x3a\x3c\x06\x00" in alloc and b"\x3a\x3c\x06\x40" in alloc   # rings at tiles 0x600 / 0x640


def test_leaving_menu_mode_clears_the_spilled_rows(original):
    code, symbols = build.assemble(build.NARROW_ADDR, build.WIDE_ADDR, 0x110000, build.BLANK_ADDR)
    routine = code[symbols["leave_menu"]:symbols["menu_begin"]]
    assert b"\x58\x82\x00\x03" in routine                    # window row 17, column 1
    assert struct.pack(">I", 0x800000 * 2) in routine          # two rows down per step
