"""从干净的 URL 补丁基线重建全部客户端改动（自包含，不依赖旧脚本）。

应用顺序：
  1. ExploreMapListUI: "isClick":true -> is_open 判断（未解锁显示锁）
  2. ExploreMapListUI: 播放地图 BGM 前 stopAll（修音乐重叠）
  3. HireShopUI: 数据填充后按真实尺寸重排（修九宫格叠放）
  4. HireMountsUI: 透明热区改为打开坐骑商店（修无法切换）
  5. HireShopInfoUI: addChild 前 removeAll（修立绘重叠）

刻意**不**改 HireListUI：它的原始布局是对的，我之前的"重排"把它挤到左上角了。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
FFDEC = Path(r"D:\Tool\FFDec-26.4.0\ffdec.jar")
JAVA = Path(r"D:\Configure\jdk17\bin\java.exe")
BASE = REPO / "build" / "input-remote" / "APetHunter.swf"
FINAL = REPO / "build" / "input-explore" / "APetHunter.swf"


def export(target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    subprocess.run([str(JAVA), "-jar", str(FFDEC), "-export", "script",
                    str(target), str(BASE)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def import_class(root: Path, name: str, src_swf: Path, out_swf: Path) -> Path:
    only = Path(tempfile.mkdtemp())
    dst = only / "scripts" / "cc" / "lv1" / "game" / "ui"
    dst.mkdir(parents=True)
    shutil.copy2(root / "scripts" / "cc" / "lv1" / "game" / "ui" / f"{name}.as",
                 dst / f"{name}.as")
    subprocess.run([str(JAVA), "-jar", str(FFDEC), "-importScript",
                    str(src_swf), str(out_swf), str(only)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not out_swf.exists():
        raise SystemExit(f"import failed: {name}")
    return out_swf


def main() -> int:
    root = Path(tempfile.mkdtemp())
    export(root)
    ui = root / "scripts" / "cc" / "lv1" / "game" / "ui"

    # 1+2) ExploreMapListUI
    p = ui / "ExploreMapListUI.as"
    src = p.read_text(encoding="utf-8")
    if '"isClick":true' not in src:
        raise SystemExit("isClick anchor missing")
    src = src.replace('"isClick":true', '"isClick":_loc5_.is_open != 0')
    bgm = re.compile(
        r'if\(SoundManager\.contains\("sound_back"\)\)\s*\{\s*'
        r'SoundManager\.stop\("sound_back"\);\s*\}\s*'
        r'_loc7_ = "sound_event_" \+ \(200 \+ param2\.world\);\s*'
        r'if\(!SoundManager\.contains\(_loc7_\)\)\s*\{\s*'
        r'SoundManager\.play\(_loc7_,2147483647\);\s*\}'
    )
    src, n = bgm.subn(
        'SoundManager.stopAll();\n'
        '              _loc7_ = "sound_event_" + (200 + param2.world);\n'
        '              SoundManager.play(_loc7_,2147483647);',
        src,
    )
    if n != 1:
        raise SystemExit("bgm anchor missing")
    p.write_text(src, encoding="utf-8")

    # 3) HireShopUI 重排
    p = ui / "HireShopUI.as"
    src = p.read_text(encoding="utf-8")
    decl = re.compile(r'^(\s*)var _loc10_:String = null;', re.M)
    m = decl.search(src)
    if not m:
        raise SystemExit("shop decl anchor missing")
    indent = m.group(1)
    src = src[: m.end()] + (
        "\n" + indent + "var _cellW:Number = 95;"
        "\n" + indent + "var _cellH:Number = 95;"
    ) + src[m.end():]
    setter = re.compile(r'^([ \t]*)_page_img\.set\(', re.M)
    m2 = setter.search(src)
    if not m2:
        raise SystemExit("shop setter anchor missing")
    i2 = m2.group(1)
    block = "".join(i2 + line + "\n" for line in [
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
    ])
    src = src[: m2.start()] + block + src[m2.start():]
    p.write_text(src, encoding="utf-8")

    # 4) HireMountsUI 热区必然打开坐骑商店
    p = ui / "HireMountsUI.as"
    src = p.read_text(encoding="utf-8")
    hire = re.compile(
        r"if\(this\.data\)\s*\{\s*"
        r"CommandManager\.send\(CommandManager\.EXPLORE_RENT_KEY,\{\s*"
        r'"gid":data\.id,\s*"ttype":data\.type\s*\}\);\s*\}\s*else\s*\{\s*'
        r"CommandManager\.send\(CommandManager\.EXPLORE_EQUIP_LIST_KEY,\{\s*"
        r'"ttype":1,\s*"p":1,\s*"n":9\s*\}\);\s*\}',
        re.S,
    )
    src, n = hire.subn(
        "CommandManager.send(CommandManager.EXPLORE_EQUIP_LIST_KEY,{\n"
        '            "ttype":1,\n'
        '            "p":1,\n'
        '            "n":9\n'
        "         });",
        src,
    )
    if n != 1:
        raise SystemExit("mount hotspot anchor missing")
    p.write_text(src, encoding="utf-8")

    # 4b) HireMountsUI 也要先清空，否则切换坐骑时上一只的贴图会留着
    p = ui / "HireMountsUI.as"
    src = p.read_text(encoding="utf-8")
    add = re.compile(r"([ \t]*)_pic_img\.addChild\(_loc5_\);")
    m = add.search(src)
    if not m:
        raise SystemExit("mounts pic anchor missing")
    src = src[: m.start()] + m.group(1) + "_pic_img.removeAll();\n" + src[m.start():]
    p.write_text(src, encoding="utf-8")

    # 5) HireShopInfoUI 先清空再画
    p = ui / "HireShopInfoUI.as"
    src = p.read_text(encoding="utf-8")
    add = re.compile(r"([ \t]*)_pic_img\.addChild\(_loc6_\);")
    m = add.search(src)
    if not m:
        raise SystemExit("shop info anchor missing")
    src = src[: m.start()] + m.group(1) + "_pic_img.removeAll();\n" + src[m.start():]
    p.write_text(src, encoding="utf-8")

    current = BASE
    for name in ("ExploreMapListUI", "HireShopUI", "HireMountsUI", "HireShopInfoUI"):
        out = REPO / "build" / "input-explore" / f"step-{name}.swf"
        current = import_class(root, name, current, out)
        print(f"  {name}: {current.stat().st_size} bytes")
    shutil.copy2(current, FINAL)
    print("final:", FINAL.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
