import struct

from tools.tje import patch


def records(data):
    assert data[:5] == b"PATCH" and data[-3:] == b"EOF"
    i = 5
    while data[i:i + 3] != b"EOF":
        offset = int.from_bytes(data[i:i + 3], "big")
        size = struct.unpack_from(">H", data, i + 3)[0]
        i += 5
        if size:
            yield offset, size
            i += size
        else:
            count = struct.unpack_from(">H", data, i)[0]
            yield offset, count
            i += 3


def test_patch_round_trips_a_grown_file():
    original = bytes(range(256)) * 8
    patched = bytearray(original) + bytes(4096)
    patched[100:110] = b"korean...."
    patched[3000:3000 + 40] = b"\x00" * 40
    result = patch.apply_patch(original, patch.build_patch(original, bytes(patched)))
    assert result == bytes(patched)
    assert len(result) == len(patched)


def test_identical_files_produce_an_empty_patch():
    data = bytes(range(256))
    assert patch.build_patch(data, data) == b"PATCHEOF"


def test_no_record_starts_at_the_eof_marker_offset():
    original = bytes(patch.EOF_OFFSET + 64)
    patched = bytearray(original)
    patched[patch.EOF_OFFSET:patch.EOF_OFFSET + 8] = b"12345678"
    data = patch.build_patch(original, bytes(patched))
    assert all(offset != patch.EOF_OFFSET for offset, _ in records(data))
    assert patch.apply_patch(original, data) == bytes(patched)


def test_long_runs_become_rle_records():
    original = bytes(64)
    patched = bytes(64) + b"\xff" * 5000
    data = patch.build_patch(original, patched)
    assert len(data) < 200                      # 5000 bytes must not be spelled out
    assert patch.apply_patch(original, data) == patched


def test_records_stay_inside_the_ips_limits():
    original = bytes(16)
    patched = bytes(16) + bytes(range(256)) * 600      # 153600 varied bytes
    data = patch.build_patch(original, patched)
    for offset, size in records(data):
        assert 0 <= offset < patch.MAX_OFFSET
        assert 0 < size <= patch.MAX_RECORD
    assert patch.apply_patch(original, data) == patched
