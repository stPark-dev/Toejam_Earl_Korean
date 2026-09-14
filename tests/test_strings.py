import pytest

from tools.tje import strings
from tools.tje.rom import read_rom


@pytest.fixture(scope="module")
def rom():
    return read_rom()


@pytest.fixture(scope="module")
def entries(rom):
    return strings.extract(rom)


def by_addr(entries):
    return {e.addr: e for e in entries}


def test_dialog_string_found_with_pointer_table_ref(entries):
    e = by_addr(entries)[0x26890]
    assert e.text == "achoo"
    assert any(r.addr == 0x2687A and r.kind == "abs32" for r in e.refs)


def test_intro_string_found_via_pc_relative_pea(entries):
    e = by_addr(entries)[0x2A1E6]
    assert e.text == "Greetings,"
    assert [(r.addr, r.kind) for r in e.refs] == [(0x29DC4, "pcrel")]


def test_credits_and_press_start_found(entries):
    table = by_addr(entries)
    assert table[0x37E9A].text == "game design -- greg johnson"
    assert table[0x3AB8E].text == "press and hold start to exit"


def test_menu_strings_after_struct_entries_are_found(entries):
    table = by_addr(entries)
    assert table[0x2425E].text == "Two Player -- Toejam an' Earl"
    assert table[0x242D8].text == "Play New Game -- Random World"
    assert table[0x24372].text == "standard    A....Action"
    assert table[0x2418A].text == "no accompaniment"


def test_all_entries_are_clean_ascii(entries):
    for e in entries:
        assert e.text == e.text.strip("\0")
        assert all(0x20 <= ord(c) < 0x7F or 1 <= ord(c) <= 6 for c in e.text)
        assert e.refs, e.key


def test_no_duplicate_addresses(entries):
    addrs = [e.addr for e in entries]
    assert len(addrs) == len(set(addrs))


def test_string_at_rejects_mid_string_and_binary(rom):
    assert strings.string_at(rom, 0x0300FF) is None     # outside text window
    assert strings.string_at(rom, 0x26890) == "achoo"
    assert strings.string_at(rom, 0x236AA) is None      # code that reads "Hx"


def test_mid_string_hits_are_not_entries(entries):
    addrs = {e.addr for e in entries}
    assert 0x20444 not in addrs        # "perfunk thruster"
    assert 0x2426A not in addrs        # "- Toejam an' Earl"
    assert 0x235CE in addrs            # "bogus ... game over" (code immediate)
    assert 0x26C00 not in addrs        # "'re" inside "Earl, you're"
    assert 0x20612 not in addrs        # "s on earl's level"
    assert 0x2001F not in addrs        # code bytes with control characters


def test_csv_roundtrip(entries, tmp_path):
    path = tmp_path / "s.csv"
    strings.write_csv(entries, path)
    rows = strings.read_csv(path)
    assert len(rows) == len(entries)
    assert rows[0]["id"] == entries[0].key
    assert set(rows[0]) == {"id", "en", "ko", "refs"}


def test_hud_and_present_strings_are_found(entries):
    table = by_addr(entries)
    assert table[0xA9F48].text == "wiener"
    assert table[0xA9F55].text == "p\x01n\x02r"          # poindexter with ligature glyphs
    assert table[0xB716].text == "vacation"
    assert table[0xABC42].text == "icarus wings "
    assert table[0xA1A0].text == " pts"
