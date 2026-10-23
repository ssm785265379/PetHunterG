"""让「租赁装备」页点击有反馈。

问题：HireListUI.onMouseUpItem 对已租道具也发 EXPLORE_RENT_KEY(102)（重租自己），
所以点上去什么都不会发生。

改法（保守、语法安全）：在函数体最前面插入"打开装备商店并 return"，
这样点任何格子都会跳去装备商店，用户能明确继续操作。
"""

import io
import re
import sys

path = sys.argv[1] + r"\scripts\cc\lv1\game\ui\HireListUI.as"
src = io.open(path, encoding="utf-8").read()

anchor = re.compile(
    r"(private function onMouseUpItem\(param1:MouseEvent\) : void\s*\{\s*)", re.S
)
m = anchor.search(src)
if not m:
    print("ANCHOR_MISSING")
    sys.exit(1)

inject = (
    "// open the equipment shop first so a tap always gives feedback\n"
    "         CommandManager.send(CommandManager.EXPLORE_EQUIP_LIST_KEY,{\n"
    '            "ttype":2,\n'
    '            "p":1,\n'
    '            "n":9\n'
    "         });\n"
    "         return;\n"
)
src = src[: m.end(1)] + inject + src[m.end(1):]
io.open(path, "w", encoding="utf-8", newline="").write(src)
print("PATCHED_OK")
