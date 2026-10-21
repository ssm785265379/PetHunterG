"""List every exported symbol in a SWF with the tag kind that defines it.

`swf_symbols.py` only answers "does this name appear somewhere in the file".
For the explore battle page the question is sharper: ExplorePveUI.as:386-392
assigns `new map_<iconId>()` straight into a `Bitmap.bitmapData`, which only
works when the symbol is a Bitmap class. This prints name -> kind for every
symbol so a wrong kind can be spotted.

    python tools/swf_symbol_list.py <file.swf> [--names map_1 map_2]
"""

from __future__ import annotations

import pathlib
import re
import struct
import sys
import zlib

TAG_NAMES = {
    6: "DefineBits",
    20: "DefineBitsLossless",
    21: "DefineBitsJPEG2",
    35: "DefineBitsLossless2",
    36: "DefineBitsJPEG4",
    90: "DefineBitsJPEG4",
    39: "DefineSprite",
    76: "SymbolClass",
    56: "ExportAssets",
    43: "FrameLabel",
    1: "ShowFrame",
    4: "PlaceObject",
    26: "PlaceObject2",
    2: "DefineShape",
    32: "DefineShape3",
    10: "DefineFont",
    11: "DefineText",
    12: "DoAction",
    82: "DoABC",
    13: "DefineFontInfo",
    48: "DefineFont2",
    14: "DefineSound",
    69: "FileAttributes",
}


def inflate_body(raw: bytes) -> bytes:
    if raw[:3] == b"CWS":
        return raw[:8] + zlib.decompress(raw[8:])
    if raw[:3] == b"ZWS":
        return raw[:12] + zlib.decompress(raw[12:], -15)
    return raw


def walk(data: bytes):
    """Yield (tag code, body) pairs.

    The body does not start with tags: a SWF header is followed by a RECT for
    the stage size and a fixed/float frame rate, so the first tag offset has to
    be derived from those rather than assumed.
    """
    bits = data[8]
    offset = 9
    for _ in range(5):
        if not bits & 0x80:
            break
        bits >>= 1
        offset += 1
    nbits = bits >> 3
    offset += (nbits + 4) // 5  # RECT total bit count field
    offset += (nbits + 4 * nbits + 3) // 8  # RECT contents
    offset += 4  # frame rate (8.8 fixed)
    offset += 2  # frame count
    while offset + 2 <= len(data):
        header = struct.unpack("<H", data[offset : offset + 2])[0]
        offset += 2
        code = header >> 6
        size = header & 0x3F
        if size == 0x3F:
            if offset + 4 > len(data):
                return
            size = struct.unpack("<I", data[offset : offset + 4])[0]
            offset += 4
        body = data[offset : offset + size]
        offset += size
        yield code, body
        if code == 0:
            return


def symbol_classes(data: bytes) -> dict[str, int]:
    """SymbolClass tags give the authoritative export name -> character id."""
    found: dict[str, int] = {}
    for code, body in walk(data):
        if code == 76 and len(body) >= 2:
            count = struct.unpack("<H", body[:2])[0]
            pos = 2
            for _ in range(count):
                if pos + 4 > len(body):
                    break
                sid = struct.unpack("<H", body[pos : pos + 2])[0]
                pos += 2
                end = body.find(b"\x00", pos)
                if end < 0:
                    break
                found[body[pos:end].decode("utf-8", "replace")] = sid
                pos = end + 1
    return found


def export_assets(data: bytes) -> dict[str, int]:
    """ExportAssets tags carry export names for assets without SymbolClass."""
    found: dict[str, int] = {}
    for code, body in walk(data):
        if code == 56 and len(body) >= 2:
            count = struct.unpack("<H", body[:2])[0]
            pos = 2
            for _ in range(count):
                if pos + 2 > len(body):
                    break
                sid = struct.unpack("<H", body[pos : pos + 2])[0]
                pos += 2
                end = body.find(b"\x00", pos)
                if end < 0:
                    break
                found[body[pos:end].decode("utf-8", "replace")] = sid
                pos = end + 1
    return found


def defining_kinds(data: bytes) -> dict[int, str]:
    """Character id -> the tag kind that defines it.

    Bitmap tags matter most: client code such as ExploreUI.as:173 assigns
    `new <symbol>()` straight into `Bitmap.bitmapData`, which only works when the
    exported class wraps a bitmap.
    """
    bitmap_tags = (6, 20, 21, 35, 36, 90)
    kinds: dict[int, str] = {}
    for code, body in walk(data):
        if code in bitmap_tags + (39,) and len(body) >= 2:
            kinds[struct.unpack("<H", body[:2])[0]] = TAG_NAMES.get(code, f"tag{code}")
    return kinds


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = pathlib.Path(argv[1])
    raw = path.read_bytes()
    data = inflate_body(raw)
    classes = symbol_classes(data)
    exports = export_assets(data)
    kinds = defining_kinds(data)

    names = set(classes) | set(exports)
    print(f"{path.name}: {len(names)} exported names")
    bitmap = [n for n in names if kinds.get(classes.get(n, exports.get(n, -1)), "").startswith("DefineBits")]
    print(f"  bitmap-backed symbols: {len(bitmap)}")
    for name in sorted(bitmap)[:20]:
        print(f"    {name}")

    if "--names" in argv:
        pos = argv.index("--names")
        for name in argv[pos + 1 :]:
            sid = classes.get(name, exports.get(name))
            if sid is None:
                print(f"  MISSING  {name}")
            else:
                kind = kinds.get(sid, "unknown")
                mark = "ok " if kind.startswith("DefineBits") else "!! "
                print(f"  {mark} {name:14s} id={sid:5d} kind={kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))