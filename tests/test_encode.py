import pytest

from tools.tje import encode


def test_columns_counts_ascii_as_one_and_hangul_as_two():
    assert encode.columns("ab 1") == 4
    assert encode.columns("가나") == 4
    assert encode.columns("a가") == 3


def test_wide_code_never_contains_nul_and_roundtrips():
    for idx in (0, 1, 254, 255, 256, 1000, encode.MAX_WIDE - 1):
        code = encode.wide_code(idx)
        assert code[0] >= 0x80 and code[1] != 0
        assert encode.wide_index(code) == idx
    with pytest.raises(ValueError):
        encode.wide_code(encode.MAX_WIDE)


def test_encode_decode_roundtrip():
    text = "뭘 가져왔어? 12"
    chars = encode.collect_wide_chars([text])
    wide_map = {ch: i for i, ch in enumerate(chars)}
    data = encode.encode(text, wide_map)
    assert data[-1] == 0 and data.count(0) == 1
    assert len(data) == encode.columns(text) + 1
    assert encode.decode(data, chars) == text


def test_encode_rejects_strings_over_32_columns():
    wide_map = {"가": 0}
    encode.encode("가" * 16, wide_map)
    with pytest.raises(ValueError):
        encode.encode("가" * 16 + "a", wide_map)


def test_collect_wide_chars_is_sorted_and_unique():
    assert encode.collect_wide_chars(["나가", "가!"]) == ["가", "나"]
