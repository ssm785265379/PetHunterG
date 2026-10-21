"""List the symbol names an AIR SWF actually defines.

The earlier scan_symbols.py searched the raw file and reported false
MISSING results: SWF bodies are zlib-compressed, so a plain byte search over
a CWS file sees almost nothing. This module inflates the body first and only
then scans, which is what makes the answer usable.

Names live in the tag stream as printable runs; SymbolClass / DefineSprite /
DefineButton2 all carry them as null-terminated strings, so scanning for
printable ASCII runs is a good proxy for "this symbol can be
getDefinition()'d".

    python tools/swf_symbols.py data/map.swf map_3 map_1
"""

from __future__ import annotations

import pathlib
import re
import sys
import zlib

# Printable ASCII runs long enough to be a symbol name rather than noise.
NAME = re.compile(rb"[\x20-\x7e]{3,64}")


def swf_body(path: pathlib.Path) -> bytes:
    """Return the decompressed SWF body, tag stream included."""
    raw = path.read_bytes()
    if raw[:3] == b"CWS":
        return zlib.decompress(raw[8:])
    if raw[:3] == b"ZWS":
        # LZMA-compressed variant: the compressed length sits at bytes 4..8.
        import lzma

        return lzma.LZMADecompressor().decompress(raw[12:])
    if raw[:3] == b"FWS":
        return raw[8:]
    raise ValueError(f"{path} is not an uncompressed, zlib- or lzma-SWF")


def symbols(path: pathlib.Path) -> set[str]:
    """Every printable name the SWF defines."""
    body = swf_body(path)
    return {run.decode("ascii", "ignore") for run in NAME.findall(body)}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    swf = pathlib.Path(argv[1])
    if not swf.is_file():
        print(f"no such file: {swf}")
        return 1
    found = symbols(swf)
    if len(argv) == 2:
        for name in sorted(found):
            print(name)
        return 0
    missing = False
    for wanted in argv[2:]:
        ok = wanted in found
        missing |= not ok
        print(f"{'ok     ' if ok else 'MISSING'} {wanted}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))