"""图鉴 / 神器协议（25、26、7、48、49、107）。

客户端证据来自 FFDec 26.4.0 对 ``client/air51-repack/build/input`` 的导出
（导出目录只在 %TEMP%，不入库）：

* ``IllustrationListUI.as:176-243``：25 发 ``ttype/p/n``，读
  ``finish_rate`` 与 ``pics[].{id,icon,is_reward}``；名称由客户端自己按
  ``getConfigValue("pic", id, "name")`` 解析。
* ``PicItem.as:110-170``：``is_reward`` 为 0 时格子画灰且 ``mouseEnabled=false``，
  所以这个字段表示「是否已登记」，不是「有没有奖励」。
* ``IllustrationTaskUI.as:190-264``：48 读 ``own_num/need_num/reward_*/is_finish``，
  49 领奖后整页刷新。
* ``ArtifactUI.as:138-172``：神器四个按钮发 107，``ttype=1..4``；
  ``res.swf`` 的 ``img_artifact_1..4`` 位图分别是初级/中级/高级/终级神器。
* ``ArtifactListUI.as:365-420``：107 只读 ``id/need_money/is_reward/pics[]``，
  ``pics`` 行是 pic.txt id，全登记后才允许 108（``gid=id``）。

107 的「每档需要哪些图鉴」在随包配置表里没有对应表，保持 ``pics: []`` 并在
``docs/illustration-artifact-protocol.md`` 写清未取证。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pet_hunter_server import app as A
from pet_hunter_server import config_tables, create_app
from support import create_local_player, envelope


def _setup(tmp_path: Path, nick: str):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, nick)
    return database, client, uid


def _show(client, show_id, uid, **params):
    body = {"m": "show", "showId": show_id, "uid": uid}
    body.update(params)
    return envelope(client.post("/flash.do", data=body))


def _unlock(database: Path, uid: str, pic_ids) -> None:
    with sqlite3.connect(database) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]
        for pic_id in pic_ids:
            connection.execute(
                "INSERT OR IGNORE INTO pic_unlocked (player_id, pic_id, unlocked_at)"
                " VALUES (?,?,datetime('now'))",
                (player_id, pic_id),
            )
        connection.commit()


def _unlocked_rows(database: Path, uid: str) -> set[int]:
    with sqlite3.connect(database) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT pic_id FROM pic_unlocked WHERE player_id ="
                " (SELECT id FROM players WHERE uid = ?)",
                (uid,),
            )
        }


def _page_ids(client, uid, ttype: int, page: int, size: int) -> list[int]:
    command, payload = _show(
        client, 25, uid, ttype=ttype, p=page, n=size
    )
    assert command == 25
    return [row["id"] for row in payload["pics"]]


@pytest.mark.parametrize(
    ("ttype", "total"),
    ((1, 342), (2, 936), (3, 97), (4, 42)),
)
def test_25_lists_the_whole_pic_txt_tab(tmp_path: Path, ttype: int, total: int):
    """25 必须给出 pic.txt 该分页的全量条目，而不是写死的 3 条。"""
    _database, client, uid = _setup(tmp_path, f"PicTab{ttype}")
    pics = config_tables._table("pic.txt")
    seen: list[int] = []
    page = 1
    while True:
        ids = _page_ids(client, uid, ttype, page, 60)
        seen.extend(ids)
        if len(ids) < 60:
            break
        page += 1
    assert len(seen) == total
    if ttype == 1:
        # 宠物分页 342 条：用户报的「图鉴只有 3 条」在这个数字面前不成立。
        assert len(seen) > 100
    assert len(set(seen)) == total, "分页不能重复或漏条目"
    assert {pics[pic_id]["type"].strip() for pic_id in seen} == {str(ttype)}
    # 客户端发 n=9：第一页必须正好 9 条，第二页是另一批。
    first = _page_ids(client, uid, ttype, 1, 9)
    second = _page_ids(client, uid, ttype, 2, 9)
    assert len(first) == 9 and len(second) == 9
    assert set(first).isdisjoint(second)


def test_25_pages_have_the_right_last_page_size(tmp_path: Path):
    """42 条 + n=9：第 5 页只有 6 条，第 6 页必须为空。"""
    _database, client, uid = _setup(tmp_path, "PicLast")
    assert len(_page_ids(client, uid, 4, 1, 9)) == 9
    assert len(_page_ids(client, uid, 4, 5, 9)) == 6
    assert _page_ids(client, uid, 4, 6, 9) == []


def test_25_finish_rate_and_is_reward_follow_pic_unlocked(tmp_path: Path):
    database, client, uid = _setup(tmp_path, "PicRate")
    _command, fresh = _show(client, 25, uid, ttype=4, p=1, n=9)
    assert fresh["finish_rate"] == 0
    assert all(row["is_reward"] == 0 for row in fresh["pics"])

    first_two = _page_ids(client, uid, 4, 1, 9)[:2]
    _unlock(database, uid, first_two)
    _command, after = _show(client, 25, uid, ttype=4, p=1, n=9)
    assert 0 < after["finish_rate"] < 100
    unlocked_flags = {row["id"]: row["is_reward"] for row in after["pics"]}
    assert all(unlocked_flags[pic_id] == 1 for pic_id in first_two)

    catalogue = A._pic_catalogue(4)
    _unlock(database, uid, [pic_id for pic_id, _icon in catalogue])
    _command, full = _show(client, 25, uid, ttype=4, p=1, n=9)
    assert full["finish_rate"] == 100
    assert all(row["is_reward"] == 1 for row in full["pics"])

    # 图鉴的完成度是按分页算的，宠物页不应被「发现」页的解锁带高。
    _command, pets = _show(client, 25, uid, ttype=1, p=1, n=9)
    assert pets["finish_rate"] == 0


def test_7_catch_registers_the_same_pic_id_that_25_lists_and_48_counts(tmp_path: Path):
    """7 号存 pic.txt id，弹窗条目、25 的格子、48 的 own_num 必须是同一个 id。"""
    database, client, uid = _setup(tmp_path, "PicCatch")
    command, caught = _show(client, 7, uid, hid=1)
    assert command == 7
    pic = caught["pic"]
    assert pic, "第一次捕捉必须弹「获得图鉴」"
    pics = config_tables._table("pic.txt")
    for entry in pic:
        assert entry["id"] == entry["icon"]
        assert entry["id"] in pics
        assert pics[entry["id"]]["type"].strip() == "1"
    registered = _unlocked_rows(database, uid)
    assert registered == {entry["id"] for entry in pic}
    # 同一个 id 在 25 的宠物分页里显示为已登记。
    catalogue = [pic_id for pic_id, _icon in A._pic_catalogue(1)]
    for entry in pic:
        index = catalogue.index(entry["id"])
        page = index // 9 + 1
        rows = _show(client, 25, uid, ttype=1, p=page, n=9)[1]["pics"]
        row = next(item for item in rows if item["id"] == entry["id"])
        assert row["is_reward"] == 1
    # 48 的 own_num 与 25 用同一份目录，第一次捕捉后就是 1。
    _command, step = _show(client, 48, uid)
    assert step["own_num"] == len(pic)

    # 已登记过的生物不再重复弹图鉴，也不再增加计数。
    _command, again = _show(client, 7, uid, hid=1)
    assert again["pic"] == []
    assert _show(client, 48, uid)[1]["own_num"] == len(pic)


def test_hunt_banner_only_returns_pic_txt_ids(tmp_path: Path):
    """6 号狩猎的获得图鉴条目也必须落在 pic.txt 里（否则 25 永远看不到）。"""
    _database, client, uid = _setup(tmp_path, "PicHunt")
    command, hunt = _show(client, 6, uid, hid=1)
    assert command == 6
    pics = config_tables._table("pic.txt")
    assert hunt["pic"], "第一场狩猎至少登记一种怪"
    for entry in hunt["pic"]:
        assert entry["id"] in pics
        assert entry["id"] == entry["icon"]
    assert _unlocked_rows(_database, uid) == {entry["id"] for entry in hunt["pic"]}


def test_48_counts_only_ids_the_illustration_ui_can_show(tmp_path: Path):
    """48 的 own_num 必须跟 25 的目录一致：legacy/type5 行保留但不计数。"""
    database, client, uid = _setup(tmp_path, "PicStep")
    real = [pic_id for pic_id, _icon in A._pic_catalogue(1)][:5]
    # 旧存档里可能存在的非目录 id：不存在的号、只有 pet.txt 的超级进化体、
    # 以及客户端没有页签的 type=5（景点）。
    legacy = [999999, 6501, 150011]
    _unlock(database, uid, legacy[:1] + real[:2] + legacy[1:])
    _command, step = _show(client, 48, uid)
    assert step["own_num"] == 2, "只有 pic.txt 目录里的 id 才算图鉴数量"
    assert step["is_finish"] == 0

    _unlock(database, uid, real[2:])
    _command, step = _show(client, 48, uid)
    assert step["own_num"] == 5
    assert step["need_num"] == 5
    assert step["is_finish"] == 1

    # 49 领一次成功，再领同样一档必须被拒（防重复领奖）。
    command, claimed = _show(client, 49, uid)
    assert command == 49 and claimed["id"] == step["id"]
    again = client.post("/flash.do", data={"m": "show", "showId": 49, "uid": uid})
    assert again.get_data(as_text=True) == "-1\t-1:504"
    _command, next_step = _show(client, 48, uid)
    assert next_step["own_num"] == 5
    assert next_step["need_num"] == 10, "下一档里程碑必须刷新到 need=10"


def test_48_ignores_rows_left_by_older_builds(tmp_path: Path):
    """旧行保留可读：把 legacy id 写进 pic_unlocked 不会让 25/48 崩或虚增。"""
    database, client, uid = _setup(tmp_path, "PicOld")
    _unlock(database, uid, [6501, 150011, 999999])
    _command, step = _show(client, 48, uid)
    assert step["own_num"] == 0
    _command, page = _show(client, 25, uid, ttype=1, p=1, n=9)
    assert page["finish_rate"] == 0
    assert all(row["is_reward"] == 0 for row in page["pics"])
    assert _unlocked_rows(database, uid) == {6501, 150011, 999999}, "旧行不能被删"


@pytest.mark.parametrize("ttype", (1, 2, 3, 4))
def test_107_artifact_tier_has_a_renderable_shape(tmp_path: Path, ttype: int):
    """107：四档神器的 id/need_money/is_reward/pics 形状正确；条目未取证。"""
    _database, client, uid = _setup(tmp_path, f"Art{ttype}")
    command, payload = _show(client, 107, uid, ttype=ttype, p=1, n=9)
    assert command == 107
    assert set(payload) == {"id", "need_money", "is_reward", "pics"}
    assert payload["id"] == ttype
    assert payload["need_money"] == 0
    assert payload["is_reward"] == 0
    # 随包配置没有「第 N 档需要哪些图鉴」的表，先保持空结构而不是编条目。
    assert payload["pics"] == []
    assert all(isinstance(payload[key], int) for key in ("id", "need_money", "is_reward"))


def test_108_refuses_instead_of_paying_a_made_up_artifact(tmp_path: Path):
    """108 没有条目/奖励证据：必须明确报错，不能落到 {"value":"ok"} 假成功。"""
    database, client, uid = _setup(tmp_path, "ArtRwd")
    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT money, point, crystal FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        bag_before = connection.execute(
            "SELECT COUNT(*) FROM inventory WHERE player_id ="
            " (SELECT id FROM players WHERE uid = ?)", (uid,)
        ).fetchone()[0]
    response = client.post(
        "/flash.do", data={"m": "show", "showId": 108, "uid": uid, "gid": 1}
    )
    assert response.get_data(as_text=True) == "-1\t-1:100"
    with sqlite3.connect(database) as connection:
        after = connection.execute(
            "SELECT money, point, crystal FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        bag_after = connection.execute(
            "SELECT COUNT(*) FROM inventory WHERE player_id ="
            " (SELECT id FROM players WHERE uid = ?)", (uid,)
        ).fetchone()[0]
    assert after == before, "拒绝领取时不能有货币副作用"
    assert bag_after == bag_before, "拒绝领取时不能发道具/装备"


def test_107_rejects_bad_tier_and_unknown_player(tmp_path: Path):
    _database, client, uid = _setup(tmp_path, "ArtBad")
    for body in (
        {"ttype": 0, "p": 1, "n": 9},
        {"ttype": 5, "p": 1, "n": 9},
        {"ttype": 1, "p": 0, "n": 9},
        {"ttype": 1, "p": 1, "n": 0},
    ):
        response = client.post(
            "/flash.do", data={"m": "show", "showId": 107, "uid": uid, **body}
        )
        assert response.get_data(as_text=True) == "-1\t-1:100", body
    missing = client.post(
        "/flash.do", data={"m": "show", "showId": 107, "uid": "nobody", "ttype": 1}
    )
    assert missing.get_data(as_text=True) == "-1\t-1:103"
