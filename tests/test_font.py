from tools.tje import font


def test_narrow_glyph_is_two_tiles_and_wide_is_four():
    assert len(font.glyph("A", wide=False)) == 64
    assert len(font.glyph("한", wide=True)) == 128


def test_space_is_fully_transparent():
    assert font.glyph(" ", wide=False) == bytes(64)


def test_letter_has_ink_and_outline_on_transparent_background():
    cell = font.paint_cell(font.ink_mask("A", font.NARROW_W))
    flat = [v for row in cell for v in row]
    assert font.COLOR_INK in flat and font.COLOR_OUTLINE in flat and 0 in flat
    assert all(row[-1] == 0 for row in cell)
    assert set(flat) <= {0, font.COLOR_OUTLINE, font.COLOR_INK}
    assert (font.COLOR_INK, font.COLOR_OUTLINE) == (0x8, 0xB)   # game remaps 8->15, B->1


def test_outline_surrounds_every_ink_pixel():
    cell = font.paint_cell(font.ink_mask("ㅣ", font.WIDE_W))
    for r in range(font.CELL_H):
        for c in range(font.WIDE_W - 1):
            if cell[r][c] == font.COLOR_BG:
                for rr in range(max(0, r - 1), min(font.CELL_H, r + 2)):
                    for cc in range(max(0, c - 1), min(font.WIDE_W, c + 2)):
                        assert cell[rr][cc] != font.COLOR_INK


def test_tile_packing_order_is_column_major():
    cell = [[0] * 16 for _ in range(16)]
    cell[0][0] = 1     # TL
    cell[8][0] = 2     # BL
    cell[0][8] = 3     # TR
    cell[8][8] = 4     # BR
    tiles = font.cell_tiles(cell)
    assert tiles[0] >> 4 == 1 and tiles[32] >> 4 == 2 and tiles[64] >> 4 == 3 and tiles[96] >> 4 == 4


def test_narrow_table_size():
    assert len(font.narrow_table()) == 95 * 64


def test_wide_table_size_and_determinism():
    a = font.wide_table(["가", "나"])
    assert len(a) == 256
    assert a == font.wide_table(["가", "나"])


def test_hangul_vowel_stroke_survives_outline():
    # Galmuri11 drew the ㅏ bar of 한 one pixel wide; the outline swallowed it
    # and 한 looked like 힌. The wide font must keep an ink pixel to the right
    # of the vertical stem in the middle rows.
    cell = font.paint_cell(font.ink_mask("한", font.WIDE_W))
    stem = max(c for r in range(1, 4) for c in range(font.WIDE_W) if cell[r][c] == font.COLOR_INK)
    assert any(cell[r][stem + 1] == font.COLOR_INK for r in range(4, 9)), "ㅏ bar missing"


def test_narrow_latin_fits_seven_columns():
    for ch in "AWMg1":
        cell = font.paint_cell(font.ink_mask(ch, font.NARROW_W))
        assert all(row[-1] == 0 for row in cell)
        assert any(v == font.COLOR_INK for row in cell for v in row)


def test_hud_glyph_is_one_opaque_tile_with_ink():
    tile = font.hud_glyph("위")
    assert len(tile) == 32
    nibbles = {b >> 4 for b in tile} | {b & 15 for b in tile}
    assert nibbles == {font.HUD_BG, font.HUD_INK}
    assert len(font.hud_table(["위", "너"])) == 64


def test_bold_widens_strokes_and_stays_inside_cell():
    cell = font.paint_cell(font.ink_mask("ㅣ", font.WIDE_W))
    widths = [sum(1 for v in row if v == font.COLOR_INK) for row in cell]
    assert max(widths) >= 2                       # 1px stem became 2px
    assert all(row[-1] == 0 for row in cell)


def test_jitter_is_deterministic_and_at_most_one_pixel():
    assert font.jitter("가") == font.jitter("가")
    assert {font.jitter(ch) for ch in "가나다라마바사아자차카타파하"} == {0, 1}
    top = lambda ch: min(r for r, row in enumerate(font.ink_mask(ch, font.WIDE_W)) if any(row))
    assert top("가") - top("나") in (-1, 0, 1)


def test_plane_glyph_uses_menu_font_palette():
    tile = font.glyph("가", wide=True, plane=True)
    nibbles = {b >> 4 for b in tile} | {b & 15 for b in tile}
    assert nibbles == {font.PLANE_BG, font.PLANE_INK, font.PLANE_SHADE}
    assert font.glyph(" ", wide=True, plane=True) == bytes(128)
    assert len(font.narrow_table(plane=True)) == 95 * 64
