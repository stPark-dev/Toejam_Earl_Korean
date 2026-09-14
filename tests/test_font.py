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
