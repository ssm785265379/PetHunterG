"""对远端服务端跑一遍只读命令冒烟。

用途：每次部署后确认"所有已实现命令都能返回合法信封"，把 500 / 协议错误提前暴露出来，
而不是等玩家点到了才发现。

用法（在 server/ 目录下）：
    .venv\\Scripts\\python.exe ..\\tools\\smoke-remote.py --base http://43.173.99.241:8080 --uid local-xxxx

判定标准：
  * HTTP 必须 200
  * 正文必须是 `<cmd>\\t<json>`，且 JSON 可解析
  * 业务错误（`-1:<id>`）单独列出——有些是参数不对，有些是真缺陷，需要人工判断

只跑**只读**命令：不买东西、不上阵、不用道具、不合宠，避免动到真实存档。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

# (showId, 额外参数, 说明)
READ_ONLY_CASES: list[tuple[int, dict, str]] = [
    (2, {}, "家园信息"),
    (3, {}, "角色详情"),
    (4, {}, "狩猎地图列表"),
    (5, {"hid": 1}, "狩猎准备页"),
    (11, {}, "宠物列表"),
    (22, {"ttype": 1, "p": 1, "n": 9}, "背包-道具"),
    (22, {"ttype": 2, "p": 1, "n": 9}, "背包-素材"),
    (22, {"ttype": 3, "p": 1, "n": 9}, "背包-装备"),
    (25, {}, "图鉴列表"),
    (26, {"gid": 1001}, "图鉴详情"),
    (27, {"ttype": 1, "p": 1, "n": 9}, "商店列表"),
    (32, {"ttype": 1, "p": 1, "n": 9}, "铁匠配方"),
    (33, {"gid": 32001, "ttype": 1}, "铁匠详情"),
    (42, {"p": 1, "n": 9}, "选宠列表"),
    (46, {"gid": 1}, "任务详情"),
    (48, {}, "图鉴里程碑"),
    (51, {"p": 1, "n": 9}, "好友列表"),
    (52, {"gid": "npc-1"}, "好友详情"),
    (73, {}, "副本列表"),
    (82, {}, "擂台星级"),
    (86, {}, "我的公会"),
    (88, {}, "公会列表"),
    (91, {"gid": 0}, "公会成员"),
    (98, {"ttype": 1}, "探险世界列表"),
    (98, {"ttype": 2, "gid": 1, "p": 1, "n": 9}, "探险地图列表"),
    (99, {"gid": 1}, "探险地图详情"),
    (100, {"ttype": 1, "p": 1, "n": 9}, "探险租借商店"),
    (104, {"ttype": 1, "p": 1, "n": 9}, "已租坐骑"),
    (104, {"ttype": 2, "p": 1, "n": 9}, "已租装备"),
    (107, {}, "成就/图鉴列表"),
    (41, {"ttype": 2, "p": 1, "n": 9}, "玩家更多信息"),
    (504, {}, "养成总览"),
    (505, {"p": 1, "n": 9}, "养成选宠"),
    (507, {}, "擂台排行"),
    (511, {}, "任务追踪"),
]

# 需要带真实 index 的命令：从 11 号里取一只宠物
PET_INDEX_CASES = [
    (12, {"index": "{pet}"}, "宠物详情"),
    (13, {"index": "{pet}"}, "宠物全属性"),
    (9, {"index": "{pet}"}, "养成详情"),
]

# 需要 gid+ttype+loc 三件套的命令
SHOP_CASES = [
    (28, {"gid": 10007, "ttype": 1, "loc": 1}, "商店详情"),
]


def call(base: str, uid: str, show_id: int, extra: dict) -> tuple[int, str]:
    payload = {"m": "show", "showId": show_id, "uid": uid}
    payload.update(extra)
    body = urllib.parse.urlencode(payload).encode()
    request = urllib.request.Request(base.rstrip("/") + "/flash.do", data=body)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, ""
    except Exception as error:  # noqa: BLE001 - 网络问题也要报出来
        return 0, f"{type(error).__name__}: {error}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="例如 http://43.173.99.241:8080")
    parser.add_argument("--uid", required=True)
    args = parser.parse_args()

    cases = list(READ_ONLY_CASES) + list(SHOP_CASES)

    # 先拿一只真实宠物 index，供 12/13/9 使用
    status, text = call(args.base, args.uid, 11, {})
    pet_index = None
    if status == 200 and "\t" in text:
        pets = json.loads(text.split("\t", 1)[1]).get("pets") or []
        if pets:
            pet_index = pets[0].get("index")
    if pet_index is not None:
        for show_id, extra, label in PET_INDEX_CASES:
            resolved = {k: (pet_index if v == "{pet}" else v) for k, v in extra.items()}
            cases.append((show_id, resolved, label))

    failures: list[str] = []
    protocol_errors: list[str] = []
    for show_id, extra, label in cases:
        status, text = call(args.base, args.uid, show_id, extra)
        if status != 200:
            failures.append(f"showId={show_id} {label} -> HTTP {status}")
            continue
        if "\t" not in text:
            protocol_errors.append(f"showId={show_id} {label} -> {text.strip()[:40]}")
            continue
        _, payload = text.split("\t", 1)
        try:
            json.loads(payload)
        except json.JSONDecodeError:
            failures.append(f"showId={show_id} {label} -> 非法 JSON")

    total = len(cases)
    print(f"共 {total} 条命令：HTTP/JSON 失败 {len(failures)}，业务错误 {len(protocol_errors)}")
    for line in failures:
        print("  [FAIL] " + line)
    for line in protocol_errors:
        print("  [BIZ ] " + line)
    if not failures and not protocol_errors:
        print("  全部通过")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
