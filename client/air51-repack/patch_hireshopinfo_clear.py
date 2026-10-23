"""修 HireShopInfoUI 的立绘重叠。

问题：readDatas 里每次 `_pic_img.addChild(_loc6_)` 都往同一个容器追加图片，
没有先清空；连开几只坐骑/装备，图像就叠在一起。

改法：addChild 之前先 `_pic_img.removeAll()`（GameObject 自带），与
HireMountsUI 的用法一致。
"""

import io
import re
import sys

path = sys.argv[1] + r"\scripts\cc\lv1\game\ui\HireShopInfoUI.as"
src = io.open(path, encoding="utf-8").read()

anchor = re.compile(r"([ \t]*)_pic_img\.addChild\(_loc6_\);")
m = anchor.search(src)
if not m:
    print("ANCHOR_MISSING")
    sys.exit(1)

indent = m.group(1)
src = src[: m.start()] + indent + "_pic_img.removeAll();\n" + src[m.start():]
io.open(path, "w", encoding="utf-8", newline="").write(src)
print("PATCHED_OK")
