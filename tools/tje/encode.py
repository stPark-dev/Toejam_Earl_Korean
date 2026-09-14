"""Text encoding for the patched renderer.

ASCII 0x20..0x7E is one byte and one column (8px). Every other character
is a two-byte code — lead 0x80|hi, trail 1..255 — indexing the wide glyph
table, and takes two columns (16px). Strings are NUL-terminated and the
renderer centres them inside a 32-column strip.
"""
MAX_COLUMNS = 32
TRAIL_RANGE = 255
MAX_WIDE = 127 * TRAIL_RANGE


def is_narrow(ch):
    return 0x20 <= ord(ch) < 0x7F


def columns(text):
    return sum(1 if is_narrow(ch) else 2 for ch in text)


def wide_code(index):
    if not 0 <= index < MAX_WIDE:
        raise ValueError(f"wide glyph index out of range: {index}")
    return bytes((0x80 | (index // TRAIL_RANGE), index % TRAIL_RANGE + 1))


def wide_index(code):
    return (code[0] & 0x7F) * TRAIL_RANGE + code[1] - 1


def collect_wide_chars(texts):
    """Sorted list of every non-ASCII character used."""
    return sorted({ch for t in texts for ch in t if not is_narrow(ch)})


def encode(text, wide_map):
    """Encode text; wide_map maps a wide character to its glyph index."""
    if columns(text) > MAX_COLUMNS:
        raise ValueError(f"too wide ({columns(text)} columns): {text!r}")
    out = bytearray()
    for ch in text:
        if is_narrow(ch):
            out.append(ord(ch))
        else:
            out += wide_code(wide_map[ch])
    out.append(0)
    return bytes(out)


def decode(data, wide_chars):
    text = []
    i = 0
    while data[i] != 0:
        b = data[i]
        if b < 0x80:
            text.append(chr(b))
            i += 1
        else:
            text.append(wide_chars[wide_index(data[i:i + 2])])
            i += 2
    return "".join(text)
