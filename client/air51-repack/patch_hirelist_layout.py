import io
import re
import sys

srcdir = r"C:\Users\ssm\AppData\Local\Temp\as3-edit4"
path = srcdir + r"\scripts\cc\lv1\game\ui\HireListUI.as"
src = io.open(path, encoding="utf-8").read()

anchor = re.compile(r'^([ \t]*)_page_img\.set\(', re.M)
m = anchor.search(src)
if not m:
    print("ANCHOR_MISSING")
    sys.exit(1)

indent = m.group(1)
lines = [
    "while(_loc11_ < _item_num)",
    "{",
    "   if(_items[_loc11_] != null && _items[_loc11_].width > 0)",
    "   {",
    "      _items[_loc11_].x = 20 + _loc11_ % 3 * (Math.max(_items[_loc11_].width,90) + 5);",
    "      _items[_loc11_].y = 90 + (_loc11_ / 3 | 0) * (Math.max(_items[_loc11_].height,90) + 5);",
    "   }",
    "   _loc11_++;",
    "}",
]
block = "".join(indent + line + "\n" for line in lines)
src = src[:m.start()] + block + src[m.start():]
io.open(path, "w", encoding="utf-8", newline="").write(src)
print("HireListUI patched")
