"""Rewrite one ActionScript constant-pool URL in an uncompressed SWF."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


def _read_u30(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for index in range(5):
        if offset >= len(data):
            raise ValueError("truncated U30 value")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << (7 * index)
        if byte < 0x80:
            if value > 0x3FFFFFFF:
                raise ValueError("U30 value is out of range")
            return value, offset
    raise ValueError("invalid U30 value")


def _encode_u30(value: int) -> bytes:
    if not 0 <= value <= 0x3FFFFFFF:
        raise ValueError("U30 value is out of range")
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _copy_varint(data: bytes, offset: int) -> tuple[bytes, int]:
    start = offset
    for _ in range(5):
        if offset >= len(data):
            raise ValueError("truncated ABC integer pool")
        byte = data[offset]
        offset += 1
        if byte < 0x80:
            return data[start:offset], offset
    raise ValueError("invalid ABC integer pool value")


def _rewrite_abc_string(abc: bytes, replacements: dict[bytes, bytes]) -> tuple[bytes, dict[bytes, int]]:
    if len(abc) < 4:
        raise ValueError("truncated ABC header")
    offset = 4
    prefix = bytearray(abc[:4])

    for pool, width in (("int", None), ("uint", None), ("double", 8)):
        count, offset = _read_u30(abc, offset)
        prefix += _encode_u30(count)
        if count > 1:
            if width is None:
                for _ in range(count - 1):
                    value, offset = _copy_varint(abc, offset)
                    prefix += value
            else:
                end = offset + (count - 1) * width
                if end > len(abc):
                    raise ValueError("truncated ABC double pool")
                prefix += abc[offset:end]
                offset = end

    count, offset = _read_u30(abc, offset)
    prefix += _encode_u30(count)
    matches = {old: 0 for old in replacements}
    for _ in range(max(0, count - 1)):
        length, offset = _read_u30(abc, offset)
        end = offset + length
        if end > len(abc):
            raise ValueError("truncated ABC string pool")
        value = abc[offset:end]
        offset = end
        if value in replacements:
            matches[value] += 1
            value = replacements[value]
        prefix += _encode_u30(len(value)) + value

    if offset > len(abc):
        raise ValueError("invalid ABC constant pool")
    return bytes(prefix) + abc[offset:], matches


def _rewrite_doabc(payload: bytes, replacements: dict[bytes, bytes]) -> tuple[bytes, dict[bytes, int]]:
    if len(payload) < 5:
        raise ValueError("truncated DoABC tag")
    name_end = payload.find(b"\x00", 4)
    if name_end < 0:
        raise ValueError("unterminated DoABC name")
    abc, matches = _rewrite_abc_string(payload[name_end + 1 :], replacements)
    return payload[: name_end + 1] + abc, matches


def patch_swf_urls(
    data: bytes, replacements: dict[str, str], *, allow_multiple: bool = False
) -> bytes:
    if len(data) < 8 or data[:3] != b"FWS":
        raise ValueError("only uncompressed FWS files are supported")
    declared_length = struct.unpack_from("<I", data, 4)[0]
    if declared_length != len(data):
        raise ValueError("SWF declared length does not match file size")

    encoded = {old.encode("utf-8"): new.encode("utf-8") for old, new in replacements.items()}
    if not encoded or len(encoded) != len(replacements):
        raise ValueError("replacement source strings must be unique and non-empty")
    output = bytearray(data[:8])
    offset = 8
    matches = {old: 0 for old in encoded}

    while offset < len(data):
        if offset + 2 > len(data):
            raise ValueError("truncated SWF tag header")
        record = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        tag_code, short_length = record >> 6, record & 0x3F
        if short_length == 0x3F:
            if offset + 4 > len(data):
                raise ValueError("truncated SWF long tag header")
            payload_length = struct.unpack_from("<I", data, offset)[0]
            offset += 4
        else:
            payload_length = short_length
        end = offset + payload_length
        if end > len(data):
            raise ValueError("truncated SWF tag payload")
        payload = data[offset:end]
        offset = end

        if tag_code == 82:
            payload, found = _rewrite_doabc(payload, encoded)
            for old, count in found.items():
                matches[old] += count
            if payload:
                output += struct.pack("<H", (tag_code << 6) | 0x3F)
                output += struct.pack("<I", len(payload))
                output += payload
        elif tag_code == 0:
            if payload_length:
                raise ValueError("invalid SWF End tag")
            output += struct.pack("<H", 0)
            if offset != len(data):
                raise ValueError("data found after SWF End tag")
            break
        else:
            if payload_length < 0x3F:
                output += struct.pack("<H", (tag_code << 6) | payload_length)
            else:
                output += struct.pack("<H", (tag_code << 6) | 0x3F)
                output += struct.pack("<I", payload_length)
            output += payload

    for old, count in matches.items():
        if count == 0 or (count != 1 and not allow_multiple):
            expectation = "at least one" if allow_multiple else "exactly one"
            raise ValueError(
                f"expected {expectation} matching ABC string for {old!r}, found {count}"
            )
    struct.pack_into("<I", output, 4, len(output))
    return bytes(output)


def patch_swf_url(data: bytes, old_url: str, new_url: str) -> bytes:
    return patch_swf_urls(data, {old_url: new_url})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--old", default="http://123.196.114.169/")
    parser.add_argument("--new")
    parser.add_argument("--replace", action="append", default=[], metavar="OLD=NEW")
    parser.add_argument(
        "--replace-all",
        action="store_true",
        help="allow each old ABC string to occur more than once",
    )
    args = parser.parse_args()

    replacements = {}
    for entry in args.replace:
        old, separator, new = entry.partition("=")
        if not separator or not old or not new:
            parser.error("--replace must use OLD=NEW")
        replacements[old] = new
    if args.new:
        replacements[args.old] = args.new
    if not replacements:
        parser.error("provide --new or at least one --replace")
    patched = patch_swf_urls(
        args.input.read_bytes(), replacements, allow_multiple=args.replace_all
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    print(f"Patched SWF written to {args.output} ({len(patched)} bytes)")


if __name__ == "__main__":
    main()
