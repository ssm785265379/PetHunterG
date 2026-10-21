"""Dump AS3 string-pool entries from a SWF's DoABC tags.

The mount code does `getDefinition("m" + horse)` (ExploreUI.as:182). mounts.swf
exports its symbols as `00001`..`00007`, so the lookup asks for `m1` and gets
null, which throws before the explore page can animate and route to the battle
screen. Rewriting the one-character constant is only safe if the concatenation
really uses a standalone "m" entry, so this prints the pool around it.

    python tools/swf_abc_strings.py <file.swf> [--find m] [--list]
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import swf_symbol_list as L  # noqa: E402


def read_u30(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    for i in range(5):
        byte = data[pos + i]
        result |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            return result, pos + i + 1
    return result, pos + 5


def string_pool(body: bytes) -> list[str]:
    """Parse the ABC string pool out of one DoABC tag body.

    DoABC layout is a UI32 flags field, a null-terminated name, then the ABC
    block itself (u16 minor, u16 major, then the integer/uint/double/string
    pools).
    """
    pos = 4  # UI32 flags
    end = body.find(b"\x00", pos)
    abc = body[end + 1 :]
    pos = 4  # minor_version, major_version
    ints, pos = read_u30(abc, pos)
    for _ in range(ints - 1 if ints else 0):
        _, pos = read_u30(abc, pos)
    uints, pos = read_u30(abc, pos)
    for _ in range(uints - 1 if uints else 0):
        _, pos = read_u30(abc, pos)
    doubles, pos = read_u30(abc, pos)
    pos += 8 * (doubles - 1 if doubles else 0)
    count, pos = read_u30(abc, pos)
    out: list[str] = []
    for _ in range(count):
        if pos >= len(abc):
            break
        length, pos = read_u30(abc, pos)
        if length == 0 and abc[pos] == 0:
            out.append("")
            pos += 1
            continue
        out.append(abc[pos : pos + length].decode("utf-8", "replace"))
        pos += length + 1
    return out


def main(argv: list[str]) -> int:
    path = pathlib.Path(argv[1])
    data = L.inflate_body(path.read_bytes())
    pools: list[str] = []
    for code, body in L.walk(data):
        if code == 82:
            try:
                pools.extend(string_pool(body))
            except Exception as exc:  # noqa: BLE001
                print(f"  (skipped one DoABC: {exc})")
    print(f"{path.name}: {len(pools)} string-pool entries")

    if "--list" in argv:
        for i, s in enumerate(pools):
            if s:
                print(f"  [{i}] {s!r}")
        return 0

    needle = "m"
    if "--find" in argv:
        needle = argv[argv.index("--find") + 1]
    hits = [(i, s) for i, s in enumerate(pools) if s == needle]
    print(f"exact matches for {needle!r}: {len(hits)}")
    for i, _ in hits:
        lo = max(0, i - 3)
        hi = min(len(pools), i + 4)
        around = ", ".join(f"{j}:{pools[j]!r}" for j in range(lo, hi))
        print(f"  [{i}] context -> {around}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))