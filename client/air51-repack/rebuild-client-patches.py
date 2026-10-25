"""从干净的 URL 补丁基线重建全部客户端改动（自包含，不依赖旧脚本）。

应用顺序：
  1. ExploreMapListUI: "isClick":true -> is_open && !is_perfect（未解锁/已完美通关都锁）
  2. ExploreMapListUI: 播放地图 BGM 前 stopAll（修翻页换世界时多首音乐叠加）
  3. ExploreMapListUI: 地图格子显示 best_star（历史最佳星级）
  4. HireShopUI: 数据填充后按真实尺寸重排（修九宫格叠放）
  5. HireMountsUI: 透明热区改为打开坐骑商店（修无法切换）
  6. HireShopInfoUI: addChild 前 removeAll（修立绘重叠）

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
    result = subprocess.run([str(JAVA), "-jar", str(FFDEC), "-importScript",
                    str(src_swf), str(out_swf), str(only)], capture_output=True,
                   text=True)
    if not out_swf.exists():
        raise SystemExit(
            f"import failed: {name} (exit {result.returncode})\n"
            f"{result.stdout[-4000:]}\n{result.stderr[-4000:]}"
        )
    return out_swf


def main() -> int:
    root = Path(tempfile.mkdtemp())
    export(root)
    ui = root / "scripts" / "cc" / "lv1" / "game" / "ui"

    # 1+2) ExploreMapListUI：未解锁/已完美通关都锁；换世界翻页先 stopAll
    p = ui / "ExploreMapListUI.as"
    src = p.read_text(encoding="utf-8")
    if '"isClick":true' not in src:
        raise SystemExit("isClick anchor missing")
    src = src.replace(
        '"isClick":true',
        '"isClick":_loc5_.is_open != 0 && !_loc5_.is_perfect',
    )
    # 地图格子显示历史最佳星级：服务端 98 新增 best_star（0-5）。
    if '"star":_loc5_.star' not in src:
        raise SystemExit("row star anchor missing")
    src = src.replace('"star":_loc5_.star', '"star":_loc5_.best_star')
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

    # 6) BagListUI: 22 号把场景 target 带给服务端（0=人物/家园，宠物 index=宠物）
    p = ui / "BagListUI.as"
    src = p.read_text(encoding="utf-8")
    old = (
        '            CommandManager.send(CommandManager.BAG_INFO_KEY,{\n'
        '               "ttype":data.ttype,\n'
        '               "p":_page,\n'
        '               "n":_item_num\n'
        '            });'
    )
    new = (
        '            CommandManager.send(CommandManager.BAG_INFO_KEY,{\n'
        '               "ttype":data.ttype,\n'
        '               "p":_page,\n'
        '               "n":_item_num,\n'
        '               "target":data.target == null ? 0 : data.target\n'
        '            });'
    )
    if old not in src:
        raise SystemExit("bag target anchor missing")
    src = src.replace(old, new)
    p.write_text(src, encoding="utf-8")

    # 7) BagListUI: 道具使用弹窗（名称 + remark 说明 + 数量 + 使用/取消）
    src = p.read_text(encoding="utf-8")
    snippet = (REPO / "patches" / "BagListUI-use-popup.as3").read_text(encoding="utf-8")

    def patch_once(old_text: str, new_text: str, label: str) -> None:
        nonlocal src
        if src.count(old_text) != 1:
            raise SystemExit(f"bag popup {label} anchor missing")
        src = src.replace(old_text, new_text)

    patch_once(
        "   import flash.display.BitmapData;\n   import flash.events.MouseEvent;",
        "   import flash.display.BitmapData;\n   import flash.display.Shape;\n"
        "   import flash.events.Event;\n   import flash.events.MouseEvent;\n"
        "   import flash.geom.Rectangle;\n   import flash.text.TextFormat;",
        "imports",
    )
    patch_once(
        "      private var _bag_icon:IconItem;",
        """      private var _bag_icon:IconItem;

      private var _use_popup:GameObject;

      private var _use_count_txt:Text;

      private var _use_minus_btn:Button;

      private var _use_plus_btn:Button;

      private var _use_count:int;

      private var _use_max:int;

      private var _use_index:int;

      private var _use_target:int;

      private var _use_item_id:int;

      private var _pet_popup:GameObject;

      private static var _pending_pet_boxes:Array;

      private var _pet_popup_items:Vector.<IconItem>;

      private var _pet_popup_indices:Array;

      private var _pet_popup_grid:GameObject;

      private var _pet_scroll:Number;

      private var _pet_scroll_max:Number;

      private var _pet_view_h:Number;

      private var _pet_grid_w:Number;

      private var _pet_drag_start:Number;

      private var _pet_drag_scroll:Number;

      private var _pet_dragged:Boolean;""",
        "fields",
    )
    patch_once(
        "         super.release();\n         _items.length = 0;",
        "         super.release();\n         hideUsePopup();\n"
        "         hidePetRewardPopup();\n         _items.length = 0;",
        "release",
    )
    # 素材/不可直接使用的道具（prop.txt useType 0，客户端画成蓝底）以前
    # PropItem 直接 mouseEnabled=false，点了毫无反应；现在可点，点了给出提示。
    patch_once(
        "      private function onMouseUpItem(param1:MouseEvent) : void\n      {\n"
        "         var _loc3_:PropItem = PropItem(param1.target);",
        "      private function onMouseUpItem(param1:MouseEvent) : void\n      {\n"
        "         var _loc3_:PropItem = PropItem(param1.target);\n"
        "         if(_loc3_.data != null && int(_loc3_.data.on) == -1)\n"
        "         {\n"
        "            Navigator.getInstance().popUI(AlertUI.show("
        "GameUtil.getConfigValue(\"error\",\"417\",\"value\"),\"\",2),true);\n"
        "            return;\n"
        "         }",
        "material tap",
    )
    patch_once(
        """               else
               {
                  CommandManager.send(CommandManager.USE_GOODS_KEY,{
                     "index":_loc3_.data.index,
                     "index1":data.target
                  });
               }""",
        """               else
               {
                  showUsePopup(_loc3_);
               }""",
        "item tap",
    )
    patch_once(
        "      private function onMouseUpPrav(param1:MouseEvent) : void",
        snippet
        + (REPO / "patches" / "BagListUI-pet-reward.as3").read_text(encoding="utf-8")
        + "      private function onMouseUpPrav(param1:MouseEvent) : void",
        "methods",
    )
    patch_once(
        "               if(_loc14_.team == 3)\n"
        "               {\n"
        "                  _loc9_.level = _loc14_.level;\n"
        "               }",
        "               _loc9_.id = _loc14_.id;\n"
        "               if(_loc14_.team == 3)\n"
        "               {\n"
        "                  _loc9_.level = _loc14_.level;\n"
        "               }",
        "item id",
    )
    patch_once(
        "            update();\n         }",
        "            update();\n"
        "            if(param2.notice)\n"
        "            {\n"
        "               Navigator.getInstance().popUI(AlertUI.show(param2.notice,\"\",1),true);\n"
        "            }\n"
        "            if(param2.notice_box)\n"
        "            {\n"
        "               _pending_pet_boxes = param2.notice_box is Array"
        " ? param2.notice_box as Array : [param2.notice_box];\n"
        "            }\n"
        "            if(_pending_pet_boxes != null && _pending_pet_boxes.length > 0)\n"
        "            {\n"
        "               try\n"
        "               {\n"
        "                  showPetRewardPopup(_pending_pet_boxes);\n"
        "               }\n"
        "               catch(petError:Error)\n"
        "               {\n"
        "               }\n"
        "            }\n"
        "         }",
        "notice",
    )
    p.write_text(src, encoding="utf-8")

    # 8) PropItem: 素材（data.on == -1）也要能点，否则点了完全没反馈
    p = root / "scripts" / "cc" / "lv1" / "game" / "item" / "PropItem.as"
    src = p.read_text(encoding="utf-8")
    old = "               this.mouseEnabled = !_isOpen && data.on == -1 ? false : true;"
    if src.count(old) != 1:
        raise SystemExit("propitem mouseEnabled anchor missing")
    src = src.replace(old, "               this.mouseEnabled = true;")
    p.write_text(src, encoding="utf-8")

    current = BASE
    for name in ("ExploreMapListUI", "HireShopUI", "HireMountsUI",
                 "HireShopInfoUI", "BagListUI"):
        out = REPO / "build" / "input-explore" / f"step-{name}.swf"
        current = import_class(root, name, current, out)
        print(f"  {name}: {current.stat().st_size} bytes")
    # PropItem 在 item 包下，import_class 只认 ui 目录，单独走一次。
    only = Path(tempfile.mkdtemp())
    dst = only / "scripts" / "cc" / "lv1" / "game" / "item"
    dst.mkdir(parents=True)
    shutil.copy2(root / "scripts" / "cc" / "lv1" / "game" / "item" / "PropItem.as",
                 dst / "PropItem.as")
    out = REPO / "build" / "input-explore" / "step-PropItem.swf"
    result = subprocess.run([str(JAVA), "-jar", str(FFDEC), "-importScript",
                             str(current), str(out), str(only)],
                            capture_output=True, text=True)
    if not out.exists():
        raise SystemExit(f"import failed: PropItem\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
    current = out
    print(f"  PropItem: {current.stat().st_size} bytes")
    shutil.copy2(current, FINAL)
    print("final:", FINAL.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
