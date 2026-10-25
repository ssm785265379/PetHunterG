"""PvE 出战宠：6 狩猎 / 74 副本 / 103 探险共用 squad_slot；擂台 24/506 不动。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from pet_hunter_server import create_app
from support import create_local_player, envelope


def _setup(tmp_path: Path, nick: str):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, nick)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE players SET ht_ap=20, arena_ap=5, explore_ap=20,"
            " point=100000, money=100000, cur_explore_map=1 WHERE uid=?",
            (uid,),
        )
        connection.commit()
    return database, client, uid


def _pet_ids(database: Path) -> list[int]:
    with sqlite3.connect(database) as connection:
        return [row[0] for row in connection.execute(
            "SELECT id FROM pets WHERE player_id=1 ORDER BY id"
        )]


def _set_squad(database: Path, slot1: int, slot2: int) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE pets SET squad_slot=0 WHERE player_id=1")
        if slot1:
            connection.execute("UPDATE pets SET squad_slot=1 WHERE id=?", (slot1,))
        if slot2:
            connection.execute("UPDATE pets SET squad_slot=2 WHERE id=?", (slot2,))
        connection.commit()


def _battle_pet_order(client, uid: str, show_id: str, **extra) -> list[int]:
    if show_id == "103":
        envelope(
            client.post(
                "/flash.do",
                data={"m": "show", "showId": "99", "uid": uid, "gid": 1},
            )
        )
    _, payload = envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": show_id, "uid": uid, **extra},
        )
    )
    if show_id == "103":
        payload = payload["battle_result"]
    return [unit["index"] for unit in payload["att_list"] if unit.get("is_pet")]


def _fighter_pet_order(client, uid: str) -> list[int]:
    _, payload = envelope(
        client.post("/flash.do", data={"m": "show", "showId": "506", "uid": uid})
    )
    return [pet["index"] for pet in payload["pets"]]


def test_pve_battles_follow_squad_slot_order(tmp_path: Path):
    database, client, uid = _setup(tmp_path, "SqOrder")
    first, second = _pet_ids(database)
    # 故意反着放：槽1=第二只，槽2=第一只。
    _set_squad(database, second, first)

    assert _battle_pet_order(client, uid, "6", hid=1) == [second, first]
    assert _battle_pet_order(client, uid, "74", hid=1001) == [second, first]
    assert _battle_pet_order(client, uid, "103") == [second, first]

    # 擂台不在这次范围内：24 战斗和 506 展示仍按 id 最小的两只。
    assert _battle_pet_order(client, uid, "24") == [first, second]
    assert _fighter_pet_order(client, uid) == [first, second]


def test_pve_battles_fall_back_to_lowest_ids_when_no_squad(tmp_path: Path):
    database, client, uid = _setup(tmp_path, "SqFall")
    first, second = _pet_ids(database)
    _set_squad(database, 0, 0)

    assert _battle_pet_order(client, uid, "6", hid=1) == [first, second]
    assert _battle_pet_order(client, uid, "74", hid=1001) == [first, second]
    assert _battle_pet_order(client, uid, "103") == [first, second]


def test_training_pet_is_excluded_from_pve_squad_and_fallback(tmp_path: Path):
    database, client, uid = _setup(tmp_path, "SqTrain")
    first, second = _pet_ids(database)
    _set_squad(database, first, second)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE pets SET train_end=strftime('%s','now')+3600 WHERE id=?",
            (first,),
        )
        connection.commit()

    # 槽1 在训练：只剩槽2 的宠物。
    assert _battle_pet_order(client, uid, "6", hid=1) == [second]
    assert _battle_pet_order(client, uid, "74", hid=1001) == [second]
    assert _battle_pet_order(client, uid, "103") == [second]

    # 清空出战槽后回退：训练的宠物必须被 PET_READY_SQL 排除。
    _set_squad(database, 0, 0)
    assert _battle_pet_order(client, uid, "6", hid=1) == [second]
    assert _battle_pet_order(client, uid, "74", hid=1001) == [second]
    assert _battle_pet_order(client, uid, "103") == [second]
