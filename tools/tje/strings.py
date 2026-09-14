"""Locate every referenced text string in the ROM.

Two reference kinds exist:
  abs32  - a 32-bit big-endian pointer (pointer tables, `pea abs.l`, `move.l #imm`)
  pcrel  - `pea (d16,pc)` / `lea (d16,pc),An` whose target is the string
"""
import csv
from dataclasses import dataclass, field

from .rom import RANK_NAMES, be16, be32, in_text_window, s16

MAX_LEN = 64

# Code addresses that happen to decode as short printable runs ("Hx" = pea,
# "NV" = link a6) and are referenced by jump tables inside the text windows.
FALSE_POSITIVES = frozenset((0x21323, 0x236AA, 0x23D6A, 0x26F8C))


@dataclass
class Ref:
    addr: int      # where the reference lives
    kind: str      # "abs32" or "pcrel"


@dataclass
class Entry:
    addr: int
    text: str
    refs: list = field(default_factory=list)

    @property
    def key(self):
        return f"{self.addr:06X}"


def string_at(rom, addr):
    """Return the ASCII string starting at addr, or None if it is not text."""
    if not in_text_window(addr) or addr in FALSE_POSITIVES:
        return None
    end = rom.find(b"\0", addr, addr + MAX_LEN)
    if end < 0 or end == addr:
        return None
    raw = rom[addr:end]
    ligatures = RANK_NAMES[0] <= addr < RANK_NAMES[1]          # codes 1..6 draw ligature glyphs
    if not all(0x20 <= c < 0x7F or (ligatures and 1 <= c <= 6) for c in raw):
        return None
    if sum(chr(c).isalpha() for c in raw) < 2:
        return None
    return raw.decode("ascii")


def clean_start(rom, addr):
    """The byte before a string is another string's NUL or an `rts`."""
    return rom[addr - 1] == 0x00 or rom[addr - 2:addr] == b"\x4e\x75"


CODE_IMMEDIATE_OPS = {0x4879, 0x2F3C, 0x203C, 0x223C, 0x243C, 0x263C, 0x283C, 0x2A3C}


def abs32_ref_context_ok(rom, off, target):
    """An abs32 hit is trusted when the string starts cleanly, when the
    pointer is an instruction immediate, or when it sits in a table beside
    other text pointers."""
    if clean_start(rom, target):
        return True
    if be16(rom, off - 2) in CODE_IMMEDIATE_OPS:
        return True
    if 0x20 <= rom[target - 1] < 0x7F:      # mid-string: only code may point here
        return False
    for k in (-8, -6, -4, 4, 6, 8):
        neighbour = be32(rom, off + k)
        if neighbour != target and in_text_window(neighbour) and string_at(rom, neighbour) \
                and clean_start(rom, neighbour):
            return True
    return False


def scan_refs(rom):
    refs = {}
    for off in range(0x200, len(rom) - 3, 2):
        target = be32(rom, off)
        if in_text_window(target) and string_at(rom, target) and abs32_ref_context_ok(rom, off, target):
            refs.setdefault(target, []).append(Ref(off, "abs32"))
        op = be16(rom, off)
        if op == 0x487A or (op & 0xF1FF) == 0x41FA:
            target = off + 2 + s16(rom, off + 2)
            if in_text_window(target) and string_at(rom, target):
                refs.setdefault(target, []).append(Ref(off, "pcrel"))
    return refs


def extract(rom):
    """Return entries sorted by address."""
    refs = scan_refs(rom)
    return [Entry(addr, string_at(rom, addr), sorted(r, key=lambda x: x.addr))
            for addr, r in sorted(refs.items())]


def write_csv(entries, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "en", "ko", "refs"])
        for e in entries:
            w.writerow([e.key, e.text, "",
                        " ".join(f"{r.kind}@{r.addr:06X}" for r in e.refs)])


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


if __name__ == "__main__":
    import sys
    from .rom import read_rom
    entries = extract(read_rom())
    if len(sys.argv) > 1:
        write_csv(entries, sys.argv[1])
    for e in entries:
        print(f"{e.key} [{len(e.refs)}] {e.text!r}")
