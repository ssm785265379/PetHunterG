"""修补坐骑/装备租赁的可达性。

问题（拆包证据）：
1. HireMountsUI.onMouseUpHire：`if(this.data)` 时发 EXPLORE_RENT_KEY(102) 再租自己，
   只有 data 为空才发 100 打开商店；而服务端总会返回一只坐骑 → 商店永远进不去，
   坐骑无法切换。
2. HireListUI.onMouseUpItem：点已租的道具也发 102（重租自己），没有任何反馈。

改法：
1. 坐骑界面的热区改为始终打开坐骑商店（100, ttype=1）。
2. 已租道具点击改为打开装备商店（100, ttype=2），给用户一个明确的去处。
"""

import io
import re
import sys

srcdir = sys.argv[1]
mounts = srcdir + r"\scripts\cc\lv1\game\ui\HireMountsUI.as"
hirelist = srcdir + r"\scripts\cc\lv1\game\ui\HireListUI.as"

# ---- 1) HireMountsUI：热区始终打开坐骑商店 ----
src = io.open(mounts, encoding="utf-8").read()
pattern = re.compile(
    r"if\(this\.data\)\s*\{\s*"
    r"CommandManager\.send\(CommandManager\.EXPLORE_RENT_KEY,\{\s*"
    r'"gid":data\.id,\s*"ttype":data\.type\s*\}\);\s*\}\s*else\s*\{\s*'
    r"CommandManager\.send\(CommandManager\.EXPLORE_EQUIP_LIST_KEY,\{\s*"
    r'"ttype":1,\s*"p":1,\s*"n":9\s*\}\);\s*\}',
    re.S,
)
replacement = (
    "CommandManager.send(CommandManager.EXPLORE_EQUIP_LIST_KEY,{\n"
    '            "ttype":1,\n'
    '            "p":1,\n'
    '            "n":9\n'
    "         });"
)
updated, count = pattern.subn(replacement, src)
if count != 1:
    print("MOUNT_PATTERN_MISSING", count)
    sys.exit(1)
io.open(mounts, "w", encoding="utf-8", newline="").write(updated)

# ---- 2) HireListUI：点已租道具 -> 打开装备商店 ----
src = io.open(hirelist, encoding="utf-8").read()
pattern2 = re.compile(
    r"else\s*\{\s*CommandManager\.send\(CommandManager\.EXPLORE_RENT_KEY,\{\s*"
    r'"gid":_loc2_\.data\.id,',
    re.S,
)
replacement2 = (
    "else\n"
    "         {\n"
    "            CommandManager.send(CommandManager.EXPLORE_EQUIP_LIST_KEY,{\n"
    '               "ttype":2,\n'
    '               "p":1,\n'
    '               "n":9\n'
    "            });\n"
    "         }\n"
    "         if(false)\n"
    "         {\n"
    '            CommandManager.send(CommandManager.EXPLORE_RENT_KEY,{"gid":_loc2_.data.id,'
)
updated2, count2 = pattern2.subn(replacement2, src)
if count2 != 1:
    print("HIRELIST_PATTERN_MISSING", count2)
    sys.exit(1)
io.open(hirelist, "w", encoding="utf-8", newline="").write(updated2)
print("PATCHED_OK")
