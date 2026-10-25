"""Blacksmith P2/P3: 32/33/35 神器强化, 36 附魔, 77-80 转化熔合.

Table provenance
----------------
* ``equipEnchant.txt`` is keyed by the *equipment* id and carries
  ``needMoney/needPoint/needCrystal/needGoods/maxCount/extSkills/rate``.
  ``maxCount`` is the number of traits the piece may hold (its ``remark`` reads
  "N个M等级特性"), ``extSkills`` is ``"baseId:minLv-maxLv"`` where ``baseId`` is
  the level-1 skill.txt id, and ``rate`` is a 万分比 weight per entry.
* ``help.txt`` entry 7 is the fusion rule: gold equipment only, same category
  (weapon/armour/helmet), 20% of value for a same-value pair and the value
  difference for an upgrade, both paid in 蓝色晶石 (prop 10032, error 423),
  original traits move to the result, originals disappear, equipped pieces are
  refused.

Everything the shipped files do not contain (strengthen fee/stat gain, the
stone↔gold conversion, the upgrade product id) is a LOCAL DEFAULT documented
next to the ``LOCAL_REFINE_*`` / ``LOCAL_SYNTHESIS_*`` constants in ``app.py``.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pet_hunter_server import config_tables
from pet_hunter_server.app import create_app
from support import create_local_player, envelope

# 25001 焚天如意棒 (male weapon, gold value 3600, enchant: 500 crystal / 1 slot)
ENCHANT_WEAPON = 25001
# 57001 魔王之剑 (male weapon, remark 高级神器, enchant: 7000 crystal + 10032:1)
ARTIFACT = 57001
# 25002 焚天之铠 / 25012 玄天之铠: same value (3600), same category (armour),
# three enchant slots each -> enough room to see traits move without truncation.
FUSION_MAIN = 25002
FUSION_VICE = 25012
UPGRADE_VICE = 35002  # 超级焚天之铠, value 9600 -> upgrade product 25032 (26000)


def _client(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "ForgeP2")
    return client, database, uid


def _player_id(database: Path, uid: str) -> int:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]


def _prepare(database: Path, uid: str, *, money=0, point=0, crystal=0) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE players SET money = ?, point = ?, crystal = ? WHERE uid = ?",
            (money, point, crystal, uid),
        )


def _give(database: Path, uid: str, item_id: int, quantity: int = 1) -> None:
    """Stack a prop into the tab prop.txt says it belongs to (10032 is tab 1)."""
    record = config_tables.prop_record(item_id) or {}
    team = config_tables.prop_team(record) or 1
    player_id = _player_id(database, uid)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO inventory (player_id, item_id, team, quantity, icon, item_type, use_type)"
            " VALUES (?, ?, ?, ?, ?, 0, 0)"
            " ON CONFLICT (player_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity",
            (player_id, item_id, team, quantity, item_id),
        )


def _quantity(database: Path, uid: str, item_id: int) -> int:
    player_id = _player_id(database, uid)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT quantity FROM inventory WHERE player_id=? AND item_id=?",
            (player_id, item_id),
        ).fetchone()
    return row[0] if row else 0


def _equip(
    database: Path,
    uid: str,
    item_id: int,
    *,
    level: int = 1,
    buffs: str = "",
    equipped: int = 0,
) -> int:
    """Insert one equipment row built from its equip.txt record; returns its id."""
    record = config_tables.equip_record(item_id)
    stats = config_tables.equip_stats(record)
    player_id = _player_id(database, uid)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """INSERT INTO inventory (player_id, item_id, team, quantity, icon,
                                      item_type, use_type, level, star, pro,
                                      hp, speed, phy_att, mag_att, phy_def, mag_def,
                                      equipped, buffs)
               VALUES (?, ?, 3, 1, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (player_id, item_id) DO UPDATE SET
                   level = excluded.level, buffs = excluded.buffs,
                   equipped = excluded.equipped""",
            (
                player_id, item_id, config_tables.equip_icon(record),
                config_tables.equip_slot(record),
                int(str(record.get("useType", "1")).strip() or 1),
                level, config_tables.equip_star(record),
                stats["hp"], stats["speed"], stats["phy_att"], stats["mag_att"],
                stats["phy_def"], stats["mag_def"], equipped, buffs,
            ),
        )
        return connection.execute(
            "SELECT id FROM inventory WHERE player_id=? AND item_id=?",
            (player_id, item_id),
        ).fetchone()[0]


def _show(client, uid: str, **fields):
    data = {"m": "show", "uid": uid}
    data.update(fields)
    return envelope(client.post("/flash.do", data=data))


def _raw(client, uid: str, **fields) -> str:
    data = {"m": "show", "uid": uid}
    data.update(fields)
    return client.post("/flash.do", data=data).get_data(as_text=True)


def _enchant_ids(item_id: int) -> set[int]:
    """Every skill id the enchant table can hand out for that equipment."""
    record = config_tables.equip_enchant_record(item_id)
    allowed: set[int] = set()
    for base, low, high in config_tables.equip_enchant_ext_skills(record):
        allowed.update(base + level - 1 for level in range(low, high + 1))
    return allowed


# ---------------------------------------------------------------------------
# 32: enchant / strengthen lists
# ---------------------------------------------------------------------------


def test_list_ttype3_shows_only_equipment_with_an_enchant_row(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    # The starter piece 20001 has no equipEnchant.txt row at all.
    command, payload = _show(client, uid, showId="32", ttype="3", p="1", n="9")
    assert command == 32
    assert payload == {"list": [], "total": 0}

    index = _equip(database, uid, ENCHANT_WEAPON)
    command, payload = _show(client, uid, showId="32", ttype="3", p="1", n="9")
    assert command == 32
    assert payload["total"] == 1
    assert payload["list"] == [{
        "index": index, "id": ENCHANT_WEAPON, "icon": ENCHANT_WEAPON, "level": 1,
    }], "index must be inventory.id: 36 echoes it back verbatim"


def test_list_ttype2_shows_only_artifact_equipment(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _equip(database, uid, ENCHANT_WEAPON)  # gold weapon, but remark is not 神器
    command, payload = _show(client, uid, showId="32", ttype="2", p="1", n="9")
    assert command == 32
    assert payload == {"list": [], "total": 0}

    index = _equip(database, uid, ARTIFACT)
    command, payload = _show(client, uid, showId="32", ttype="2", p="1", n="9")
    assert command == 32
    assert [row["index"] for row in payload["list"]] == [index]


# ---------------------------------------------------------------------------
# 33 ttype=3: enchant detail
# ---------------------------------------------------------------------------


def test_enchant_detail_reads_cost_slots_and_skill_band_from_the_table(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, money=11, point=22, crystal=500)
    index = _equip(database, uid, ENCHANT_WEAPON)
    record = config_tables.equip_enchant_record(ENCHANT_WEAPON)
    need = config_tables.equip_enchant_need(record)

    command, payload = _show(client, uid, showId="33", ttype="3", gid=str(index))
    assert command == 33
    assert payload["index"] == index
    assert payload["id"] == ENCHANT_WEAPON
    assert (payload["need_money"], payload["own_money"]) == (need["money"], 11)
    assert (payload["need_point"], payload["own_point"]) == (need["point"], 22)
    assert (payload["need_crystal"], payload["own_crystal"]) == (need["crystal"], 500)
    assert payload["need_goods"] == []
    assert payload["max_count"] == config_tables.equip_enchant_max_count(record) == 1
    assert payload["enchant_count"] == 0
    assert payload["buffs"] == []
    first_base, first_low, first_high = config_tables.equip_enchant_ext_skills(record)[0]
    assert {
        "id": first_base, "min_level": first_low, "max_level": first_high,
    } in payload["ext_skills"]
    # equip.txt skills stay on the “技能” line; enchant adds nothing there yet.
    assert payload["skills"] == [
        {"id": skill_id} for skill_id in config_tables.equip_skills(
            config_tables.equip_record(ENCHANT_WEAPON)
        )
    ]


def test_enchant_detail_rejects_a_piece_without_a_table_row(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    with sqlite3.connect(database) as connection:
        starter = connection.execute(
            "SELECT id FROM inventory WHERE team = 3 ORDER BY id LIMIT 1"
        ).fetchone()[0]
    assert _raw(client, uid, showId="33", ttype="3", gid=str(starter)) == "-1\t-1:9"


# ---------------------------------------------------------------------------
# 36: enchant transaction
# ---------------------------------------------------------------------------


def test_enchant_draws_a_trait_pays_the_cost_and_persists_it(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, crystal=900)
    index = _equip(database, uid, ENCHANT_WEAPON)

    command, payload = _show(client, uid, showId="36", index=str(index))
    assert command == 36
    need = config_tables.equip_enchant_need(
        config_tables.equip_enchant_record(ENCHANT_WEAPON)
    )
    allowed = _enchant_ids(ENCHANT_WEAPON)
    assert payload["index"] == index
    assert payload["value"] == "ok"
    assert len(payload["buffs"]) == 1
    drawn = payload["buffs"][0]["id"]
    assert drawn in allowed, "the trait must come from this row's extSkills band"
    assert payload["enchant_count"] == 1
    assert payload["own_crystal"] == 900 - need["crystal"]

    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT pro, buffs FROM inventory WHERE id = ?", (index,)
        ).fetchone()
        crystal = connection.execute(
            "SELECT crystal FROM players WHERE id = ?", (_player_id(database, uid),)
        ).fetchone()[0]
    assert stored[1] == str(drawn), "inventory.buffs is what 39/36 read back"
    assert stored[0] == 0, "附魔不动 pro（pro 是五行，不是附魔次数）"
    assert crystal == 900 - need["crystal"]

    # The equipment tooltip (39) must show the same trait under 特性.
    command, detail = _show(client, uid, showId="39", index=str(index))
    assert command == 39
    assert detail["buffs"] == [{"id": drawn}]

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT level FROM inventory WHERE id = ?", (index,)
        ).fetchone()[0] == 1, "附魔不该改强化等级"


def test_enchant_stops_at_max_count(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, crystal=9000)
    index = _equip(database, uid, ENCHANT_WEAPON)  # maxCount = 1

    assert _show(client, uid, showId="36", index=str(index))[0] == 36
    body = _raw(client, uid, showId="36", index=str(index))
    assert body == "-1\t-1:100", "no error.txt key for 附魔上限 -> documented 100"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT crystal FROM players WHERE id = ?", (_player_id(database, uid),)
        ).fetchone()[0] == 9000 - 500, "a refused enchant must not charge"


def test_enchant_reports_crystal_shortage_with_405(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, crystal=499)
    index = _equip(database, uid, ENCHANT_WEAPON)
    assert _raw(client, uid, showId="36", index=str(index)) == "-1\t-1:405"


def test_enchant_consumes_need_goods_and_reports_material_shortage(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, crystal=8000)
    index = _equip(database, uid, ARTIFACT)
    record = config_tables.equip_enchant_record(ARTIFACT)
    goods = config_tables.equip_enchant_goods(record)
    assert goods == [(10032, 1)], "57001 的 needGoods 是 10032:1"

    assert _raw(client, uid, showId="36", index=str(index)) == "-1\t-1:400"

    _give(database, uid, 10032, 2)
    command, payload = _show(client, uid, showId="36", index=str(index))
    assert command == 36
    assert payload["need_goods"][0]["own_num"] <= 1
    assert _quantity(database, uid, 10032) == 1, "exactly one 蓝色晶石 consumed"
    assert payload["own_crystal"] == 8000 - config_tables.equip_enchant_need(record)["crystal"]


def test_every_enchant_row_resolves_to_real_skill_ids():
    """Sanity gate on the shipped table: extSkills ids must exist in skill.txt."""
    skills = config_tables._table("skill.txt")
    table = config_tables.equip_enchant_table()
    assert table, "equipEnchant.txt must load"
    for item_id, record in table.items():
        entries = config_tables.equip_enchant_ext_skills(record)
        weights = config_tables.equip_enchant_rates(record)
        assert entries, item_id
        assert len(weights) == len(entries), item_id
        assert sum(weights) == 10000, item_id
        for base, low, high in entries:
            for level in range(low, high + 1):
                assert (base + level - 1) in skills, (item_id, base, level)


# ---------------------------------------------------------------------------
# 33 ttype=2 / 35: artifact strengthen
# ---------------------------------------------------------------------------


def test_refine_detail_previews_the_next_level_from_the_table_base(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, money=600, crystal=0)
    _give(database, uid, 11024, 1)
    index = _equip(database, uid, ARTIFACT)
    record = config_tables.equip_record(ARTIFACT)
    base = config_tables.equip_stats(record)

    command, payload = _show(client, uid, showId="33", ttype="2", gid=str(index))
    assert command == 33
    assert payload["level"] == 1
    assert payload["need_money"] == 500
    assert payload["need_goods"] == [{"id": 11024, "need_num": 1, "own_num": 1}]
    preview = payload["next_refine"]
    assert preview["level"] == 2
    for column in ("hp", "speed", "phy_att", "mag_att", "phy_def", "mag_def"):
        assert preview[column] == base[column] + base[column] * 5 // 100, column
        assert payload[column] == base[column], "current values come from the bag row"


def test_refine_spends_gold_and_a_diamond_and_raises_the_level(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, money=600)
    _give(database, uid, 11024, 2)
    index = _equip(database, uid, ARTIFACT)
    record = config_tables.equip_record(ARTIFACT)
    base = config_tables.equip_stats(record)

    command, payload = _show(client, uid, showId="35", index=str(index))
    assert command == 35
    assert payload == {
        "index": index, "id": ARTIFACT, "icon": ARTIFACT, "level": 2, "value": "ok",
    }, "RefineInfoUI.as:159-186 only reads level/icon, then re-sends 33"

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT level, hp, phy_att, mag_att, phy_def, mag_def FROM inventory WHERE id=?",
            (index,),
        ).fetchone()
        money = connection.execute(
            "SELECT money FROM players WHERE id=?", (_player_id(database, uid),)
        ).fetchone()[0]
    assert row[0] == 2
    assert row[1] == base["hp"] + base["hp"] * 5 // 100
    assert row[2] == base["phy_att"] + base["phy_att"] * 5 // 100
    assert money == 100
    assert _quantity(database, uid, 11024) == 1

    command, detail = _show(client, uid, showId="33", ttype="2", gid=str(index))
    assert command == 33
    assert detail["level"] == 2
    assert detail["next_refine"]["level"] == 3


def test_refine_shortages_and_the_level_cap(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    index = _equip(database, uid, ARTIFACT)

    _prepare(database, uid, money=499)
    _give(database, uid, 11024, 1)
    assert _raw(client, uid, showId="35", index=str(index)) == "-1\t-1:403"

    _prepare(database, uid, money=500)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM inventory WHERE player_id=? AND item_id=?",
            (_player_id(database, uid), 11024),
        )
    assert _raw(client, uid, showId="35", index=str(index)) == "-1\t-1:400"

    # At the local cap the client is told "神器达到顶级" by leaving next_refine out.
    from pet_hunter_server import app as server_app

    _equip(database, uid, ARTIFACT, level=server_app.LOCAL_REFINE_MAX_LEVEL)
    _, detail = _show(client, uid, showId="33", ttype="2", gid=str(index))
    assert "next_refine" not in detail
    assert _raw(client, uid, showId="35", index=str(index)) == "-1\t-1:408", \
        "error.txt 408 此装备已经不能再强化了"


def test_refine_refuses_a_piece_that_is_not_an_artifact(tmp_path: Path):
    client, database, uid = _client(tmp_path)
    _prepare(database, uid, money=1000)
    index = _equip(database, uid, ENCHANT_WEAPON)  # gold equipment, remark != 神器
    assert _raw(client, uid, showId="33", ttype="2", gid=str(index)) == "-1\t-1:406"
    assert _raw(client, uid, showId="35", index=str(index)) == "-1\t-1:406", \
        "error.txt 406 此装备不能强化"
