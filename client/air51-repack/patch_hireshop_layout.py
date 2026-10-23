import io
import re

p = r"C:\Users\ssm\AppData\Local\Temp\as3-edit3\scripts\cc\lv1\game\ui\HireShopUI.as"
src = io.open(p, encoding="utf-8").read()

decl = re.compile(r'^(\s*)var _loc10_:String = null;', re.M)
m = decl.search(src)
assert m, "decl anchor missing"
indent = m.group(1)
extra = "\n" + indent + "var _cellW:Number = 95;" + "\n" + indent + "var _cellH:Number = 95;"
src = src[:m.end()] + extra + src[m.end():]

setter = re.compile(r'^([ \t]*)_page_img\.set\(', re.M)
m2 = setter.search(src)
assert m2, "setter anchor missing"
i2 = m2.group(1)
lines = [
    "while(_loc11_ < _item_num)",
    "{",
    "   if(_items[_loc11_] != null && _items[_loc11_].width > 0)",
    "   {",
    "      _cellW = Math.max(_items[_loc11_].width,90) + 5;",
    "      _cellH = Math.max(_items[_loc11_].height,90) + 5;",
    "      _items[_loc11_].x = 20 + _loc11_ % 3 * _cellW;",
    "      _items[_loc11_].y = 90 + (_loc11_ / 3 | 0) * _cellH;",
    "   }",
    "   _loc11_++;",
    "}",
]
block = "".join(i2 + line + "\n" for line in lines)

src = src[:m2.start()] + block + src[m2.start():]
io.open(p, "w", encoding="utf-8", newline="").write(src)
print("patched:", "while(_loc11_ < _item_num)" in src, "| cellW:", "_cellW" in src)
