"""擂台防守快照：PvE 换装/换宠不影响已保存的防守配置。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from pet_hunter_server import create_app
from support import create_local_player, envelope


def _setup(tmp_path: Path, nick: str):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, nick)
    return database, client, uid


def _add_equip(database: Path, item_id: int, item_type: int, equipped: int = 0) -> int:
    with sqlite3.connect(database) as connection:
        cursor = connection.execute(
            "INSERT INTO inventory (player_id, item_id, team, quantity, icon,"
            " item_type, use_type, level, star, pro, hp, speed, phy_att, mag_att,"
            " phy_def, mag_def, equipped)"
            " VALUES (1, ?, 3, 1, ?, ?, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, ?)",
            (item_id, item_id, item_type, equipped),
        )
        connection.commit()
        return cursor.lastrowid


def _equip(database: Path, item_id: int, equipped: int = 1) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE inventory SET equipped=? WHERE player_id=1 AND item_id=?",
            (equipped, item_id),
        )
        connection.commit()


def _set_squad(database: Path, slot1: int, slot2: int) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE pets SET squad_slot=0 WHERE player_id=1")
        connection.execute("UPDATE pets SET squad_slot=1 WHERE id=?", (slot1,))
        connection.execute("UPDATE pets SET squad_slot=2 WHERE id=?", (slot2,))
        connection.commit()


def _inv_id(database: Path, item_id: int) -> int:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT id FROM inventory WHERE player_id=1 AND item_id=?", (item_id,)
        ).fetchone()[0]


def _save_defense(client, uid: str, **data):
    payload = {"m": "show", "showId": "516", "uid": uid}
    payload.update(data)
    return client.post("/flash.do", data=payload)


def _read_defense(client, uid: str):
    return envelope(
        client.post("/flash.do", data={"m": "show", "showId": "515", "uid": uid})
    )


def test_arena_defense_snapshot_survives_pve_changes(tmp_path: Path):
    database, client, uid = _setup(tmp_path, "ArSnap")
    weapon = _inv_id(database, 20001)
    _equip(database, 20001)
    clothes = _add_equip(database, 20002, 2, equipped=1)
    hat = _add_equip(database, 20003, 3, equipped=1)
    other_weapon = _add_equip(database, 20004, 1)
    _set_squad(database, 2, 1)

    saved = _save_defense(
        client, uid, weapon=weapon, clothes=clothes, hat=hat, pet1=2, pet2=1
    )
    assert saved.get_data(as_text=True).startswith("516\t")

    # PvE 换武器、换出战宠；防守快照必须保持不变。
    _equip(database, 20001, equipped=0)
    _equip(database, 20004, equipped=1)
    _set_squad(database, 1, 2)

    _, snapshot = _read_defense(client, uid)
    assert snapshot["kind"] == "arena_defense"
    assert snapshot["is_default"] == 0
    assert snapshot["weapon"] == 20001
    assert snapshot["clothes"] == 20002
    assert snapshot["hat"] == 20003
    assert [pet["index"] for pet in snapshot["pets"]] == [2, 1]
    assert _inv_id(database, 20004) == other_weapon  # 只是避免变量未用


def test_arena_defense_defaults_to_current_pve(tmp_path: Path):
    database, client, uid = _setup(tmp_path, "ArenaDef")
    _equip(database, 20001)
    _set_squad(database, 2, 1)

    _, snapshot = _read_defense(client, uid)
    assert snapshot["is_default"] == 1
    assert snapshot["weapon"] == 20001
    assert [pet["index"] for pet in snapshot["pets"]] == [2, 1]


def test_arena_defense_rejects_foreign_or_wrong_slot(tmp_path: Path):
    database, client, uid = _setup(tmp_path, "ArenaBad")
    _equip(database, 20001)
    weapon = _inv_id(database, 20001)
    clothes = _add_equip(database, 20002, 2)

    assert _save_defense(client, uid, weapon=999999).get_data(
        as_text=True
    ).startswith("-1\t-1:100")
    # 把衣服 id 填进武器槽也要拒绝。
    assert _save_defense(client, uid, weapon=clothes).get_data(
        as_text=True
    ).startswith("-1\t-1:100")
    assert _save_defense(client, uid, weapon=weapon, pet1=999999).get_data(
        as_text=True
    ).startswith("-1\t-1:100")


def test_equip_off_clears_only_that_slot(tmp_path: Path):
    database, client, uid = _setup(tmp_path, "ArenaOff")
    _equip(database, 20001)
    _add_equip(database, 20002, 2, equipped=1)

    response = client.post(
        "/flash.do",
        data={"m": "show", "showId": "37", "uid": uid, "action": "off", "slot": 1},
    )
    command, payload = envelope(response)
    assert command == 37 and payload["value"] == "ok"
    with sqlite3.connect(database) as connection:
        rows = dict(connection.execute(
            "SELECT item_id, equipped FROM inventory WHERE player_id=1 AND team=3"
        ))
    assert rows[20001] == 0
    assert rows[20002] == 1


def test_arena_defense_ignores_a_sold_snapshot_item(tmp_path: Path):
    database, client, uid = _setup(tmp_path, "ArSell")
    _equip(database, 20001)
    weapon = _inv_id(database, 20001)
    _save_defense(client, uid, weapon=weapon)

    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM inventory WHERE id=?", (weapon,))
        connection.commit()

    _, snapshot = _read_defense(client, uid)
    assert snapshot["is_default"] == 0
    assert snapshot["weapon"] == 0


def test_bag_equipment_tab_can_filter_by_slot(tmp_path: Path):
    database, client, uid = _setup(tmp_path, "ArBag")
    _equip(database, 20001)
    _add_equip(database, 20002, 2)

    def ids(slot=None):
        data = {"m": "show", "showId": "22", "uid": uid, "ttype": 3, "p": 1, "n": 9}
        if slot:
            data["slot"] = slot
        _, payload = envelope(client.post("/flash.do", data=data))
        return {row["id"] for row in payload["goods_list"]}, payload["bag_size"]

    assert ids() == ({20001, 20002}, 2)
    assert ids(1) == ({20001}, 1)
    assert ids(2) == ({20002}, 1)


def test_arena_defense_pets_use_44_45_with_ttype3(tmp_path: Path):
    database, client, uid = _setup(tmp_path, "ArPet")
    with sqlite3.connect(database) as connection:
        first, second = [row[0] for row in connection.execute(
            "SELECT id FROM pets WHERE player_id=1 ORDER BY id"
        )]
    _set_squad(database, first, second)

    assert client.post(
        "/flash.do", data={"m": "show", "showId": "44", "uid": uid,
                           "index": second, "ttype": 3}
    ).get_data(as_text=True).startswith("44\t")
    assert client.post(
        "/flash.do", data={"m": "show", "showId": "44", "uid": uid,
                           "index": first, "ttype": 3}
    ).get_data(as_text=True).startswith("44\t")
    _, snapshot = _read_defense(client, uid)
    assert [pet["index"] for pet in snapshot["pets"]] == [second, first]

    # PvE 出战槽不能被 44/45 改动。
    with sqlite3.connect(database) as connection:
        assert dict(connection.execute(
            "SELECT id, squad_slot FROM pets WHERE player_id=1"
        )) == {first: 1, second: 2}

    assert client.post(
        "/flash.do", data={"m": "show", "showId": "45", "uid": uid,
                           "index": second, "ttype": 3}
    ).get_data(as_text=True).startswith("45\t")
    _, snapshot = _read_defense(client, uid)
    assert [pet["index"] for pet in snapshot["pets"]] == [first]
