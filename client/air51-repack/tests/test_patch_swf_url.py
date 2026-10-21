import struct
import unittest

from patch_swf_url import patch_swf_urls


OLD_URL = b"http://123.196.114.169/"
NEW_URL = b"http://127.0.0.1:8080/"


def encode_u30(value: int) -> bytes:
    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def synthetic_swf(url: bytes = OLD_URL) -> bytes:
    abc = bytearray(struct.pack("<HH", 16, 46))
    abc += encode_u30(1)  # int pool
    abc += encode_u30(1)  # uint pool
    abc += encode_u30(1)  # double pool
    abc += encode_u30(2)  # string pool
    abc += encode_u30(len(url)) + url
    abc += b"\x01\x01\x01\x01\x01\x00"  # remaining empty pools

    doabc = struct.pack("<I", 0) + b"\x00" + abc
    tag = struct.pack("<H", (82 << 6) | 63) + struct.pack("<I", len(doabc)) + doabc
    end = b"\x00\x00"
    body = tag + end
    return b"FWS" + bytes([17]) + struct.pack("<I", 8 + len(body)) + body


class PatchSwfUrlTests(unittest.TestCase):
    def test_rewrites_url_and_updates_swf_length(self):
        original = synthetic_swf()

        patched = patch_swf_urls(original, {OLD_URL.decode("ascii"): NEW_URL.decode("ascii")})

        self.assertEqual(struct.unpack_from("<I", patched, 4)[0], len(patched))
        self.assertIn(NEW_URL, patched)
        self.assertNotIn(OLD_URL, patched)

    def test_requires_exactly_one_matching_constant(self):
        with self.assertRaisesRegex(ValueError, "expected exactly one"):
            patch_swf_urls(synthetic_swf(b"not-the-url"), {OLD_URL.decode("ascii"): NEW_URL.decode("ascii")})

    def test_rewrites_multiple_urls_in_one_swf(self):
        fallback = b"http://123.196.114.177"
        abc = bytearray(struct.pack("<HH", 16, 46))
        abc += b"\x01\x01\x01\x03"
        for value in (OLD_URL, fallback):
            abc += encode_u30(len(value)) + value
        abc += b"\x01\x01\x01\x01\x01\x00"
        payload = struct.pack("<I", 0) + b"\x00" + abc
        tag = struct.pack("<H", (82 << 6) | 63) + struct.pack("<I", len(payload)) + payload
        body = tag + b"\x00\x00"
        swf = b"FWS" + bytes([17]) + struct.pack("<I", 8 + len(body)) + body
        replacements = {
            OLD_URL.decode("ascii"): NEW_URL.decode("ascii"),
            fallback.decode("ascii"): "http://127.0.0.1:8080",
        }

        patched = patch_swf_urls(swf, replacements)

        self.assertIn(NEW_URL, patched)
        self.assertIn(b"http://127.0.0.1:8080", patched)
        self.assertNotIn(fallback, patched)

    def test_replace_all_rewrites_repeated_constant_pool_strings(self):
        abc = bytearray(struct.pack("<HH", 16, 46))
        abc += b"\x01\x01\x01\x03"
        for _ in range(2):
            abc += encode_u30(len(OLD_URL)) + OLD_URL
        abc += b"\x01\x01\x01\x01\x01\x00"
        payload = struct.pack("<I", 0) + b"\x00" + abc
        tag = struct.pack("<H", (82 << 6) | 63) + struct.pack("<I", len(payload)) + payload
        body = tag + b"\x00\x00"
        swf = b"FWS" + bytes([17]) + struct.pack("<I", 8 + len(body)) + body

        patched = patch_swf_urls(
            swf,
            {OLD_URL.decode("ascii"): NEW_URL.decode("ascii")},
            allow_multiple=True,
        )

        self.assertEqual(patched.count(NEW_URL), 2)
        self.assertNotIn(OLD_URL, patched)


if __name__ == "__main__":
    unittest.main()
