"""Build an IPS patch so the translation can be distributed without the ROM.

The patched ROM is twice the size of the original, so every byte past the
original 1MB has to be written out; long runs of zeros go into RLE records to
keep the patch small.
"""
import hashlib
import os
import struct

from .rom import ORIGINAL_MD5, ORIGINAL_ROM, ROOT, read_rom

MAX_RECORD = 0xFFFF
MAX_OFFSET = 0x1000000        # IPS offsets are 3 bytes
EOF_OFFSET = 0x454F46         # "EOF": a record may not start here
RLE_MIN = 9                   # an RLE record costs 8 bytes, a plain one 5 + n


class PatchError(Exception):
    pass


def _runs(original, patched):
    """Yield (offset, data) spans of patched that the original does not have."""
    start = None
    for i in range(len(patched)):
        same = i < len(original) and original[i] == patched[i]
        if same:
            if start is not None:
                yield start, patched[start:i]
                start = None
        elif start is None:
            start = i
    if start is not None:
        yield start, patched[start:]


def _records(offset, data):
    """Split one span into IPS records, using RLE where it pays off."""
    i = 0
    while i < len(data):
        run = 1
        while run < len(data) - i and data[i + run] == data[i] and run < MAX_RECORD:
            run += 1
        if run >= RLE_MIN:
            yield offset + i, None, run, data[i]
            i += run
            continue
        # plain record: take bytes until a worthwhile run starts
        end = i
        while end < len(data) and end - i < MAX_RECORD:
            run = 1
            while run < len(data) - end and data[end + run] == data[end]:
                run += 1
            if run >= RLE_MIN and end > i:
                break
            end += max(1, run if run < RLE_MIN else 1)
        yield offset + i, data[i:end], None, None
        i = end


def build_patch(original, patched):
    """Return an IPS patch turning original into patched."""
    if len(patched) >= MAX_OFFSET:
        raise PatchError("patched ROM is too big for the IPS format")
    out = bytearray(b"PATCH")
    for offset, data in _runs(original, patched):
        for off, chunk, count, value in _records(offset, data):
            if off == EOF_OFFSET:             # nudge the record back one byte
                off -= 1
                if chunk is None:
                    chunk, count, value = bytes([value]) * (count + 1), None, None
                else:
                    chunk = patched[off:off + len(chunk) + 1]
            if chunk is None:
                out += struct.pack(">I", off)[1:] + b"\x00\x00" + struct.pack(">HB", count, value)
            else:
                out += struct.pack(">I", off)[1:] + struct.pack(">H", len(chunk)) + chunk
    return bytes(out + b"EOF")


def apply_patch(original, patch):
    """Apply an IPS patch; used by the tests to prove the patch round-trips."""
    if patch[:5] != b"PATCH":
        raise PatchError("not an IPS patch")
    out = bytearray(original)
    i = 5
    while True:
        if patch[i:i + 3] == b"EOF":
            break
        offset = int.from_bytes(patch[i:i + 3], "big")
        size = struct.unpack_from(">H", patch, i + 3)[0]
        i += 5
        if size:
            data, i = patch[i:i + size], i + size
        else:
            count, value = struct.unpack_from(">HB", patch, i)
            data, i = bytes([value]) * count, i + 3
        if offset + len(data) > len(out):
            out += bytes(offset + len(data) - len(out))
        out[offset:offset + len(data)] = data
    return bytes(out)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="write an IPS patch for the Korean ROM")
    ap.add_argument("--original", default=ORIGINAL_ROM)
    ap.add_argument("--patched", default=os.path.join(ROOT, "build", "tje_ko.gen"))
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "tje_ko.ips"))
    args = ap.parse_args()
    original = read_rom(args.original)
    if hashlib.md5(original).hexdigest() != ORIGINAL_MD5:
        raise PatchError("original ROM checksum mismatch")
    patched = read_rom(args.patched)
    patch = build_patch(original, patched)
    if apply_patch(original, patch) != patched:
        raise PatchError("patch does not reproduce the ROM")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "wb") as fh:
        fh.write(patch)
    print(f"wrote {args.out} ({len(patch)} bytes)")
    print(f"  original md5 {hashlib.md5(original).hexdigest()}")
    print(f"  patched  md5 {hashlib.md5(patched).hexdigest()}")


if __name__ == "__main__":
    main()
