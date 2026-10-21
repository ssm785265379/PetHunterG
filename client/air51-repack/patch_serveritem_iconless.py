"""Remove server-row icon and status-sprite lookups from exported AS3 source."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def _replace_once(pattern: str, replacement: str, source: str, label: str) -> str:
    result, count = re.subn(pattern, replacement, source, count=1, flags=re.DOTALL | re.MULTILINE)
    if count != 1:
        raise ValueError(f"expected one ServerItem {label} block, found {count}")
    return result


def patch_server_item_source(source: str) -> str:
    setter_start = source.find("override public function set data")
    setter_end = source.find("private function initBack", setter_start)
    if setter_start < 0 or setter_end < 0:
        raise ValueError("expected one ServerItem data setter")

    before, setter, after = source[:setter_start], source[setter_start:setter_end], source[setter_end:]
    setter = _replace_once(
        r"^\s*if\(data\.icon\)\s*\{.*?^\s*\}\s*(?=if\(data\.name\))",
        "\n            ",
        setter,
        "icon",
    )
    setter = _replace_once(
        r"^\s*if\(data\.n == 0\)\s*\{.*?^\s*\}\s*else\s*\{.*?^\s*\}",
        "",
        setter,
        "status",
    )
    if '"" + data.name' not in setter:
        raise ValueError("server name assignment was not preserved")
    if "getDefinition(" in setter or "addChild(" in setter:
        raise ValueError("unexpected visual/resource lookup remains in data setter")
    return before + setter + after


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="FFDec-exported ServerItem.as")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    patched = patch_server_item_source(args.input.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(patched, encoding="utf-8", newline="\n")
    print(f"Iconless ServerItem source written to {args.output}")


if __name__ == "__main__":
    main()
