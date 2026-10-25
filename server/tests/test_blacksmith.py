"""Blacksmith commands 32/33/34 over the table-driven recipes.

Products, icons, stats, stars and skills all come from
``client/air51-repack/src/data/zh-CN/config/equip.txt``; materials come from
``prop.txt`` 11001-11009. Everything the shipped files do not contain (craft fee,
material pick/count) is the LOCAL DEFAULT rule documented next to the
``LOCAL_FORGE_*`` constants in ``app.py``.

Every test creates its own database through the ordinary quick-create path and
talks to the real ``/flash.do`` handlers, so the assertions cover the wire
format the client parses, not just internal helpers.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pet_hunter_server import app as server_app
from pet_hunter_server import config_tables
from pet_hunter_server.app import create_app
from support import create_local_player, envelope

# 32 order: the legacy row stays first, then weapons, armour, helmets.
EXPECTED_ORDER = [32001, 25001, 35001, 25002, 35002, 25003, 35003]


def _client(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "ForgeT")
    return client, database, uid


def _player_id(database: Path, uid: str) -> int:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]


def _prepare(
    database: Path,
    uid: str,
    *,
    money: int = 0,
    point: int = 0,
    crystal: int = 0,
    capacity: int | None = None,
) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE players SET money = ?, point = ?, crystal = ? WHERE uid = ?",
            (money, point, crystal, uid),
        )
        if capacity is not None:
            connection.execute(
                "UPDATE players SET bag_capacity = ? WHERE uid = ?", (capacity, uid)
            )


def _give(
    database: Path, uid: str, item_id: int, quantity: int = 1, team: int = 2
) -> None:
    """Stack an item into the bag; team 2 = prop tab (forge materials)."""
    player_id = _player_id(database, uid)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO inventory (player_id, item_id, team, quantity, icon, item_type, use_type)"
            " VALUES (?, ?, ?, ?, ?, 0, 0)"
            " ON CONFLICT (player_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity",
            (player_id, item_id, team, quantity, item_id),
        )


def _show(client, uid: str, **fields):
    data = {"m": "show", "uid": uid}
    data.update(fields)
    return envelope(client.post("/flash.do", data=data))


def _raw(client, uid: str, **fields) -> str:
    data = {"m": "show", "uid": uid}
    data.update(fields)
    return client.post("/flash.do", data=data).get_data(as_text=True)


# ---------------------------------------------------------------------------
# 32: list + paging + category
# ---------------------------------------------------------------------------


def test_list_is_paged_and_category_scoped(tmp_path: Path):
    client, _database, uid = _client(tmp_path)

    command, payload = _show(client, uid, showId="32", ttype="1", p="1", n="2")
    assert command == 32
    assert payload["total"] == len(EXPECTED_ORDER)
    assert [row["index"] for row in payload["list"]] == EXPECTED_ORDER[:2]
    assert payload["list"][0] == {
        "index": 32001, "id": 20002, "icon": 20002, "level": 1,
    }, "the legacy recipe keeps its old gid so old callers/saves still resolve"
    assert payload["list"][1] == {
        "index": 25001, "id": 25001, "icon": 25001, "level": 9,
    }, "table-driven rows use the equip id as both index and id"

    collected = []
    for page in ("1", "2", "3", "4"):
        command, page_payload = _show(
            client, uid, showId="32", ttype="1", p=page, n="2"
        )
        assert command == 32
        assert page_payload["total"] == len(EXPECTED_ORDER)
        collected.extend(row["index"] for row in page_payload["list"])
    assert collected == EXPECTED_ORDER
    assert _show(client, uid, showId="32", ttype="1", p="5", n="2")[1]["list"] == []

    # 2/3 are refine/enchant, which have their own commands (35/36).
    for ttype in ("2", "3"):
        command, payload = _show(client, uid, showId="32", ttype=ttype, p="1", n="9")
        assert command == 32
        assert payload == {"list": [], "total": 0}


# ---------------------------------------------------------------------------
# 33: detail
# ---------------------------------------------------------------------------


def test_detail_serves_stats_and_costs_from_the_config_tables(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, money=1234, point=7, crystal=9)
    _give(database, uid, 11001, 2)

    command, payload = _show(client, uid, showId="33", gid="25001", ttype="1")
    assert command == 33

    record = config_tables.equip_record(25001)
    stats = config_tables.equip_stats(record)
    assert payload["id"] == 25001
    assert payload["icon"] == int(str(record["iconId"]).strip())
    assert payload["star"] == int(str(record["star"]).strip())
    assert payload["pro"] == 0
    # LOCAL DEFAULT: equip.txt has no level column, so `level` is the star tier.
    assert payload["level"] == 9
    for column in ("hp", "speed", "phy_att", "mag_att", "phy_def", "mag_def"):
        assert payload[column] == stats[column], column
    assert payload["skills"] == config_tables.equip_skills(record)
    assert payload["buffs"] == []

    assert (payload["need_money"], payload["own_money"]) == (360, 1234)
    assert (payload["need_point"], payload["own_point"]) == (0, 7)
    assert (payload["need_crystal"], payload["own_crystal"]) == (0, 9)
    assert payload["need_goods"] == [
        {"id": 11001, "need_num": 1, "own_num": 2}
    ]


def test_detail_high_tier_recipe_lists_every_material(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, money=5000)
    _give(database, uid, 11001, 5)

    command, payload = _show(client, uid, showId="33", gid="35001", ttype="1")
    assert command == 33
    # tier 2 (money=9600): the slot's first two jades, 2 each.
    assert payload["need_money"] == 960
    assert [
        (goods["id"], goods["need_num"], goods["own_num"])
        for goods in payload["need_goods"]
    ] == [(11001, 2, 5), (11002, 2, 0)]


@pytest.mark.parametrize("gid", ["99999", "abc", ""])
def test_detail_rejects_unknown_or_unparsable_gid(tmp_path: Path, gid: str):
    client, _database, uid = _client(tmp_path)
    assert _raw(client, uid, showId="33", gid=gid, ttype="1") == "-1\t-1:100"


# ---------------------------------------------------------------------------
# 34: crafting transaction and error codes
# ---------------------------------------------------------------------------


def test_make_spends_material_and_money_and_adds_one_product(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, money=1000)
    _give(database, uid, 11001, 1)
    player_id = _player_id(database, uid)

    command, made = _show(client, uid, showId="34", gid="25001")
    assert command == 34
    assert made["id"] == 25001
    assert made["icon"] == 25001
    assert isinstance(made["index"], int)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT money FROM players WHERE id = ?", (player_id,)
        ).fetchone()[0] == 1000 - 360, "fee = 10% of equip.txt money"
        assert connection.execute(
            "SELECT quantity FROM inventory WHERE player_id=? AND item_id=? AND team=2",
            (player_id, 11001),
        ).fetchone() is None, "the consumed material row is gone"
        row = connection.execute(
            "SELECT id, quantity, team, level, star, phy_att, speed, icon"
            " FROM inventory WHERE player_id=? AND item_id=?",
            (player_id, 25001),
        ).fetchone()
    record = config_tables.equip_record(25001)
    assert row == (
        made["index"], 1, 3, 1,
        int(str(record["star"]).strip()),
        int(str(record["phyAtt"]).strip()),
        int(str(record["speed"]).strip()),
        int(str(record["iconId"]).strip()),
    )


def test_make_without_materials_returns_400(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, money=1000)

    assert _raw(client, uid, showId="34", gid="25001") == "-1\t-1:400"

    # Materials must sit in the prop tab (team 2); a copy in another tab is not
    # spendable and must not satisfy the check.
    _give(database, uid, 11001, 3, team=1)
    assert _raw(client, uid, showId="34", gid="25001") == "-1\t-1:400"


def test_make_without_money_returns_403(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, money=359)
    _give(database, uid, 11001, 1)
    assert _raw(client, uid, showId="34", gid="25001") == "-1\t-1:403"

    # One coin more is enough; the check is exactly the recipe fee.
    _prepare(database, uid, money=360)
    assert _raw(client, uid, showId="34", gid="25001").startswith("34\t")


def test_make_reports_silver_and_crystal_shortage(tmp_path: Path, monkeypatch):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, money=1000, point=0, crystal=0)
    # The six shipped recipes only cost gold, so a synthetic legacy-shaped recipe
    # is used to exercise the 404/405 routes without touching client config.
    monkeypatch.setitem(server_app.LOCAL_FORGE_LEGACY_RECIPES, 32002, {
        "output": 20002, "money": 1, "point": 5, "crystal": 0, "goods": (),
    })
    monkeypatch.setitem(server_app.LOCAL_FORGE_LEGACY_RECIPES, 32003, {
        "output": 20002, "money": 1, "point": 0, "crystal": 5, "goods": (),
    })

    assert _raw(client, uid, showId="34", gid="32002") == "-1\t-1:404"
    assert _raw(client, uid, showId="34", gid="32003") == "-1\t-1:405"

    _prepare(database, uid, money=1000, point=5, crystal=5)
    assert _raw(client, uid, showId="34", gid="32002").startswith("34\t")
    assert _raw(client, uid, showId="34", gid="32003").startswith("34\t")


def test_make_twice_stacks_on_the_same_inventory_row(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, money=2000)
    _give(database, uid, 11001, 2)
    player_id = _player_id(database, uid)

    _command, first = _show(client, uid, showId="34", gid="25001")
    _command, second = _show(client, uid, showId="34", gid="25001")

    assert second["index"] == first["index"], "re-crafting must reuse the bag row"
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT id, quantity FROM inventory WHERE player_id=? AND item_id=?",
            (player_id, 25001),
        ).fetchall()
        assert rows == [(first["index"], 2)], "one row, quantity accumulated"
        assert connection.execute(
            "SELECT COUNT(*) FROM inventory WHERE player_id=? AND item_id=?",
            (player_id, 25001),
        ).fetchone()[0] == 1, "UNIQUE(player_id,item_id) must not be hit by a plain INSERT"
        assert connection.execute(
            "SELECT money FROM players WHERE id=?", (player_id,)
        ).fetchone()[0] == 2000 - 720


def test_make_rejects_a_full_bag_but_still_allows_stacking(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, money=1000, capacity=1)
    _give(database, uid, 11001, 1)
    # One unrelated piece of equipment occupies the only equipment slot.
    _give(database, uid, 99999, 1, team=3)

    assert _raw(client, uid, showId="34", gid="25001") == "-1\t-1:300"

    # Already owning the product needs no new slot, so that craft goes through.
    _give(database, uid, 25001, 1, team=3)
    assert _raw(client, uid, showId="34", gid="25001").startswith("34\t")


def test_make_rejects_unknown_or_malformed_gid(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, money=1000)

    assert _raw(client, uid, showId="34", gid="99999") == "-1\t-1:400"
    assert _raw(client, uid, showId="34", gid="abc") == "-1\t-1:100"
