"""T04 人物成长：等级/经验/称号/属性/装备技能/70-71-72 转职。

新测试一律放这里（T03 之后不再往 test_app.py 尾巴上堆），helper 从 support 取。
配置表数值以 client/air51-repack/src/data 的原始文件为准，本地设计数值在
app.py 里用 LOCAL DEFAULT 标注。
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
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


def _hero_total_exp(profile: dict) -> int:
    """把当前等级内的 exp 折算成从 1 级起的累计经验，便于比较"有没有涨"。"""
    from pet_hunter_server import app as A

    return sum(A.hunter_exp_to_next(lv) for lv in range(1, profile["lv"])) + profile[
        "exp"
    ]


def _profile(client, uid: str) -> dict:
    _, payload = envelope(
        client.post("/flash.do", data={"m": "show", "showId": "510", "uid": uid})
    )
    return payload


def test_explore_battle_grants_hero_exp(tmp_path: Path, monkeypatch):
    from pet_hunter_server import app as A

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "HeroEx")
    before = _hero_total_exp(_profile(client, uid))
    monkeypatch.setattr(A, "_record_is_win", lambda record: True)

    envelope(
        client.post("/flash.do", data={"m": "show", "showId": "99", "uid": uid, "gid": 1})
    )
    _, result = envelope(
        client.post("/flash.do", data={"m": "show", "showId": "103", "uid": uid})
    )
    assert result.get("event_type") == 1

    assert _hero_total_exp(_profile(client, uid)) > before


def test_arena_battle_grants_hero_exp(tmp_path: Path, monkeypatch):
    from pet_hunter_server import app as A

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "HeroAr")
    before = _hero_total_exp(_profile(client, uid))
    monkeypatch.setattr(A, "_record_is_win", lambda record: True)

    _, result = envelope(
        client.post("/flash.do", data={"m": "show", "showId": "24", "uid": uid})
    )
    assert result["is_win"] == 1

    assert _hero_total_exp(_profile(client, uid)) > before


def test_copy_battle_grants_hero_exp(tmp_path: Path, monkeypatch):
    from pet_hunter_server import app as A

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "HeroCp")
    before = _hero_total_exp(_profile(client, uid))
    monkeypatch.setattr(A, "_record_is_win", lambda record: True)

    _, result = envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "74", "uid": uid, "hid": 1001}
        )
    )
    assert result["is_win"] == 1

    assert _hero_total_exp(_profile(client, uid)) > before


def test_lost_arena_battle_grants_a_tenth_of_the_hero_exp(
    tmp_path: Path, monkeypatch
):
    from pet_hunter_server import app as A

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "HeroLs")
    with sqlite3.connect(database) as connection:
        squad_lv = connection.execute(
            "SELECT COALESCE(MAX(lv), 1) FROM pets WHERE player_id=1"
        ).fetchone()[0]
    monkeypatch.setattr(A, "_record_is_win", lambda record: False)

    _, result = envelope(
        client.post("/flash.do", data={"m": "show", "showId": "24", "uid": uid})
    )
    assert result["is_win"] == 0

    expected = (
        A.hero_battle_exp(max(A.LOCAL_ARENA_RIVAL_LEVEL, int(squad_lv))) // 10
    )
    profile = _profile(client, uid)
    assert (profile["lv"], profile["exp"]) == (1, expected)


def test_hero_stats_grow_with_level_and_job_and_match_combat(tmp_path: Path):
    from pet_hunter_server import app as A

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "HeroSt")
    base = _profile(client, uid)
    assert (base["lv"], base["job"]) == (1, 1)
    # 1 级 1 称号 = 原始基准值，老存档不会被这次改动改数值。
    for key, value in A.ROLE_BASE_STATS.items():
        assert base[key] == value, key

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET lv=50, job=10 WHERE uid=?", (uid,))
        connection.commit()
    grown = _profile(client, uid)
    for key in ("hp", "speed", "phy_att", "mag_att", "phy_def", "mag_def"):
        assert grown[key] > base[key], key

    with A._connect_database(database) as connection:
        row = connection.execute(
            "SELECT id,nick,lv,job,sex FROM players WHERE uid=?", (uid,)
        ).fetchone()
        worn = A._worn_equipment(connection, row["id"])
        combat = A._hunter_combat_stats(row, worn)
    assert combat == (grown["hp"], grown["phy_att"], grown["phy_def"])

    # 3 号（RoleInfoUI / 好友详情）和 510 必须用同一份六维。
    _, role = envelope(
        client.post("/flash.do", data={"m": "show", "showId": "3", "uid": uid})
    )
    assert role["job"] == 10
    assert role["hp"] == grown["hp"]


def test_510_lists_worn_equipment_skills_as_objects(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "HeroSk")

    # 新手装默认在背包里（equipped=0），没穿时人物技能栏应为空。
    _, bare = envelope(
        client.post("/flash.do", data={"m": "show", "showId": "510", "uid": uid})
    )
    assert bare["skills"] == []

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE inventory SET equipped=1 WHERE player_id=1 AND team=3"
        )
        connection.commit()

    _, profile = envelope(
        client.post("/flash.do", data={"m": "show", "showId": "510", "uid": uid})
    )
    # 烈焰之剑的 101:5101 要出现在人物技能里；客户端 getSkill 逐项读 .id，
    # 所以每一项必须是 {"id": n} 而不是裸整数。
    assert all(isinstance(entry, dict) for entry in profile["skills"])
    assert {entry["id"] for entry in profile["skills"]} >= {101, 5101}

    _, role = envelope(
        client.post("/flash.do", data={"m": "show", "showId": "3", "uid": uid})
    )
    assert role["skills"] == profile["skills"]


def test_job_list_and_detail_follow_the_up_role_table(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "JobLst")

    _, page = envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "70", "uid": uid, "p": 1, "n": 9},
        )
    )
    rows = {row["job"]: row["state"] for row in page["list"]}
    assert len(page["list"]) == 9
    assert rows[1] == 2, "当前称号"
    assert rows[2] == 1, "下一个可转的称号"
    assert rows[3] == 0, "更远的称号未开放（灰底）"

    _, page2 = envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "70", "uid": uid, "p": 2, "n": 9},
        )
    )
    assert [row["job"] for row in page2["list"]] == list(range(10, 19))

    _, detail = envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "71", "uid": uid, "gid": 2}
        )
    )
    assert detail["need_lv"] == 400
    assert detail["diff_lv"] == 0
    assert set(detail["nextRole"]) >= {
        "now_hp", "next_hp", "now_speed", "next_speed",
        "now_phy_att", "next_phy_att", "now_phy_def", "next_phy_def",
        "now_mag_att", "next_mag_att", "now_mag_def", "next_mag_def",
    }
    assert detail["reward_goods"] == [{"id": 10016, "num": 1}]


def test_job_change_rejects_short_level_then_promotes_and_grants_the_chest(
    tmp_path: Path,
):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "JobChg")

    rejected = client.post(
        "/flash.do", data={"m": "show", "showId": "72", "uid": uid, "gid": 2}
    )
    # 客户端按 `<cmd>\t<data>` 拆包，所以错误体必须是 -1 命令 + -1:207 数据。
    assert rejected.get_data(as_text=True) == "-1\t-1:207"
    # 非相邻称号（3 级，当前 1 级）直接拒绝，不消耗任何宝箱。
    skipped = client.post(
        "/flash.do", data={"m": "show", "showId": "72", "uid": uid, "gid": 3}
    )
    assert skipped.get_data(as_text=True) == "-1\t-1:100"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT job FROM players WHERE uid=?", (uid,)
        ).fetchone()[0] == 1

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET lv=400 WHERE uid=?", (uid,))
        connection.commit()
    _, changed = envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "72", "uid": uid, "gid": 2}
        )
    )
    assert changed["value"] == "ok"
    assert (changed["job"], changed["lv"]) == (2, 400)
    with sqlite3.connect(database) as connection:
        job, lv = connection.execute(
            "SELECT job, lv FROM players WHERE uid=?", (uid,)
        ).fetchone()
        chest = connection.execute(
            "SELECT quantity FROM inventory WHERE player_id=1 AND item_id=10016"
        ).fetchone()
    assert (job, lv) == (2, 400)
    assert chest is not None and chest[0] == 1


def test_job_five_resets_level_to_one_and_still_grants_the_chest(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "JobFiv")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET lv=1000, job=4 WHERE uid=?", (uid,))
        connection.commit()

    _, changed = envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "72", "uid": uid, "gid": 5}
        )
    )

    assert (changed["job"], changed["lv"]) == (5, 1)
    with sqlite3.connect(database) as connection:
        chest = connection.execute(
            "SELECT quantity FROM inventory WHERE player_id=1 AND item_id=12101"
        ).fetchone()
    assert chest is not None and chest[0] == 1


def test_job_list_marks_every_title_owned_at_job_120(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "JobMax")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET job=120 WHERE uid=?", (uid,))
        connection.commit()

    jobs = []
    for page in range(1, 15):
        _, payload = envelope(
            client.post(
                "/flash.do",
                data={"m": "show", "showId": "70", "uid": uid, "p": page, "n": 9},
            )
        )
        jobs.extend(payload["list"])
    assert len(jobs) == 120
    assert all(row["state"] == 2 for row in jobs)


def test_grant_hero_exp_script_updates_level_and_job(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = create_local_player(client, "HeroSc")
    script = Path(__file__).resolve().parents[1] / "scripts" / "grant_hero_exp.py"

    run = subprocess.run(
        [sys.executable, str(script), "--uid", uid, "--db", str(database), "--exp", "220"],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert "lv -> 3" in run.stdout
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT lv, exp FROM players WHERE uid=?", (uid,)
        ).fetchone() == (3, 10)

    run = subprocess.run(
        [
            sys.executable, str(script), "--uid", uid, "--db", str(database),
            "--lv", "400", "--job", "2",
        ],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT lv, job FROM players WHERE uid=?", (uid,)
        ).fetchone() == (400, 2)


def test_old_save_with_exp_zero_and_job_one_keeps_its_level(tmp_path: Path):
    from pet_hunter_server import app as A

    database = tmp_path / "game.sqlite3"
    config = {"TESTING": True, "DATABASE": database}
    client = create_app(config).test_client()
    uid = create_local_player(client, "OldSave")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE players SET lv=50, job=1, exp=0 WHERE uid=?", (uid,)
        )
        connection.commit()

    # 重新打开应用 = 老存档走一遍启动迁移：缺的列补默认值，lv 必须保留。
    reopened = create_app(config).test_client()
    _, profile = envelope(
        reopened.post("/flash.do", data={"m": "show", "showId": "510", "uid": uid})
    )

    assert (profile["lv"], profile["job"], profile["exp"]) == (50, 1, 0)
    # 等级保留后六维按新口径成长（1 级 1 称号时才是基准值），而不是被重置。
    assert profile["hp"] == round(
        A.ROLE_BASE_STATS["hp"] * (1 + A.LOCAL_HERO_LEVEL_STAT_STEP * 49)
    )
    assert profile["hp"] > A.ROLE_BASE_STATS["hp"]
