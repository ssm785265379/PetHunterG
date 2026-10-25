"""T04 人物成长：等级/经验/称号/属性/装备技能/70-71-72 转职。

新测试一律放这里（T03 之后不再往 test_app.py 尾巴上堆），helper 从 support 取。
配置表数值以 client/air51-repack/src/data 的原始文件为准，本地设计数值在
app.py 里用 LOCAL DEFAULT 标注。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pet_hunter_server import config_tables, create_app
from support import create_local_player, envelope


def test_up_role_table_reads_all_hunter_titles():
    rows = config_tables.up_role_table()

    assert len(rows) == 120
    assert sorted(rows) == list(range(1, 121))
    assert rows[2]["needLevel"] == "400"
    assert rows[2]["rewardGoods"] == "10016:1"
    # 5 级转生是第一个掉 999 级的称号；4 级及以前不掉级。
    assert rows[5]["lowerLevel"] == "999"
    assert rows[4]["lowerLevel"] == "0"
    assert rows[1]["rewardGoods"] == "0"


def test_clear_caches_also_drops_the_up_role_table():
    config_tables.up_role_table()
    assert config_tables.up_role_table.cache_info().currsize == 1

    config_tables.clear_caches()

    assert config_tables.up_role_table.cache_info().currsize == 0


def test_510_profile_carries_real_job_and_exp(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "HeroJob")

    _, fresh = envelope(
        client.post("/flash.do", data={"m": "show", "showId": "510", "uid": uid})
    )
    assert (fresh["lv"], fresh["job"], fresh["exp"]) == (1, 1, 0)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE players SET lv=7, job=3, exp=123 WHERE uid=?", (uid,)
        )
        connection.commit()
    _, profile = envelope(
        client.post("/flash.do", data={"m": "show", "showId": "510", "uid": uid})
    )

    assert profile["lv"] == 7
    assert profile["job"] == 3
    assert profile["exp"] == 123


def test_hero_exp_curve_and_grant_carry_overflow(tmp_path: Path):
    from pet_hunter_server import app as A

    # LOCAL DEFAULT 曲线：1 级 100，之后每级 +10（400 级 4090）。
    assert A.hunter_exp_to_next(1) == 100
    assert A.hunter_exp_to_next(2) == 110
    assert A.hunter_exp_to_next(400) == 4090

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "HeroXp")
    with sqlite3.connect(database) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE uid=?", (uid,)
        ).fetchone()[0]
    with A._connect_database(database) as connection:
        # 220 = 100(1→2) + 110(2→3) + 10 余量。
        assert A._grant_hero_exp(connection, player_id, 220) == 3
        row = connection.execute(
            "SELECT lv, exp FROM players WHERE id=?", (player_id,)
        ).fetchone()
        assert (row["lv"], row["exp"]) == (3, 10)
        # 封顶 1000 级，不再升。
        connection.execute(
            "UPDATE players SET lv=1000, exp=0 WHERE id=?", (player_id,)
        )
        assert A._grant_hero_exp(connection, player_id, 10_000) == 1000


def test_hunt_win_grants_hero_exp_and_levels_the_hunter(tmp_path: Path, monkeypatch):
    from pet_hunter_server import app as A

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "HeroExp")
    monkeypatch.setattr(A, "_record_is_win", lambda record: True)

    _, result = envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "6", "uid": uid, "hid": 1, "ttype": 1},
        )
    )
    assert result["is_win"] == 1

    _, profile = envelope(
        client.post("/flash.do", data={"m": "show", "showId": "510", "uid": uid})
    )
    assert profile["lv"] > 1, "一场胜利的人物经验应足够升到 2 级"
    assert profile["exp"] >= 0
