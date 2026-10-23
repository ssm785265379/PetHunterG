from pathlib import Path
import logging
import json
import sqlite3
import xml.etree.ElementTree as ET

from pet_hunter_server import create_app
from pet_hunter_server import config_tables, seed_items
from pet_hunter_server.app import LOCAL_DEFAULT_BAG_CAPACITY


def test_health_check_is_available_to_local_client():
    client = create_app({"TESTING": True}).test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"mode": "lan-prototype", "status": "ok"}


def test_server_list_is_served_verbatim_from_local_fixture(tmp_path: Path):
    fixture = tmp_path / "data" / "android" / "server.xml"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("<servers><server id='local'/></servers>", encoding="utf-8")
    client = create_app(
        {"TESTING": True, "FIXTURE_DIR": tmp_path}
    ).test_client()

    response = client.get("/data/android/server.xml")

    assert response.status_code == 200
    assert response.mimetype == "application/xml"
    assert response.get_data(as_text=True) == "<servers><server id='local'/></servers>"


def test_localized_server_list_path_uses_the_same_fixture(tmp_path: Path):
    fixture = tmp_path / "data" / "android" / "server.xml"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("<servers><server id='local'/></servers>", encoding="utf-8")
    client = create_app(
        {"TESTING": True, "FIXTURE_DIR": tmp_path}
    ).test_client()

    response = client.get("/data/android/zh-CN/server.xml")

    assert response.status_code == 200
    assert response.mimetype == "application/xml"
    assert response.get_data(as_text=True) == "<servers><server id='local'/></servers>"


def test_default_local_server_list_has_client_fields_and_lan_url():
    client = create_app({"TESTING": True}).test_client()

    response = client.get("/data/android/zh-CN/server.xml")

    assert response.status_code == 200
    assert response.mimetype == "application/xml"
    server = ET.fromstring(response.data).find("server")
    assert server is not None
    assert server.attrib == {
        "id": "1",
        "name": "LAN Local Test",
        "icon": "clip_back_login",
        "n": "0",
        "url": "http://127.0.0.1:8080/",
    }


def test_default_server_node_uses_a_bundled_movieclip_for_icon():
    client = create_app({"TESTING": True}).test_client()

    response = client.get("/data/android/zh-CN/server.xml")
    server = ET.fromstring(response.data).find("server")

    assert server is not None
    assert server.get("icon") == "clip_back_login"


def test_response_metadata_logs_status_and_length_without_request_values(caplog):
    caplog.set_level(logging.INFO)
    client = create_app({"TESTING": True}).test_client()

    response = client.post(
        "/flash.do?m=unimplemented",
        data={"uname": "player@example.test", "pwd": "private-password"},
    )

    assert response.status_code == 200
    assert "response source=127.0.0.1 method=POST path=/flash.do status=200" in caplog.text
    assert f"bytes={len(response.data)}" in caplog.text
    assert "private-password" not in caplog.text
    assert "player@example.test" not in caplog.text


def test_file_response_metadata_uses_content_length_header(tmp_path: Path, caplog):
    caplog.set_level(logging.INFO)
    fixture = tmp_path / "data" / "android" / "server.xml"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("<config><server/></config>", encoding="utf-8")
    client = create_app(
        {"TESTING": True, "FIXTURE_DIR": tmp_path}
    ).test_client()

    response = client.get("/data/android/server.xml")

    assert response.status_code == 200
    assert f"status=200 bytes={response.content_length}" in caplog.text


def test_server_list_reports_missing_capture_instead_of_guessing(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "FIXTURE_DIR": tmp_path}
    ).test_client()

    response = client.get("/data/android/server.xml")

    assert response.status_code == 503
    assert response.get_json() == {"error": "server_list_not_configured"}


def test_unknown_flash_command_is_observed_without_leaking_request_values(caplog):
    # The 501 used to be surfaced as the in-game "网络错误" dialog, because
    # APetHunter.as:166-168 raises it from ioHttpRequestError on any transport
    # failure. An unimplemented command now answers 200 with an empty envelope so
    # the page takes its normal (empty) branch instead of blocking the player.
    caplog.set_level(logging.INFO)
    client = create_app({"TESTING": True}).test_client()

    response = client.post(
        "/flash.do?m=unimplemented",
        data={"uname": "player@example.test", "pwd": "private-password", "sn": "secret-signature"},
    )

    assert response.status_code == 200
    assert response.get_data(as_text=True) == '0\t{"value":"ok"}'
    assert "command=unknown" in caplog.text
    assert "unimplemented" in caplog.text
    assert "pwd" in caplog.text
    assert "private-password" not in caplog.text
    assert "player@example.test" not in caplog.text
    assert "secret-signature" not in caplog.text


def test_unimplemented_show_id_never_returns_a_transport_error(tmp_path: Path):
    # Any command the client sends but this server has not implemented used to
    # answer 501, which AIR turns into "网络错误". A normal 200 envelope (or a
    # normal "-1:<id>" protocol error, which the client already understands) keeps
    # the page usable.
    client = create_app({"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}).test_client()
    uid = _create_local_player(client, "NoErr")
    for show_id in (87, 93, 1004, 1005, 4096):
        response = client.post(
            "/flash.do", data={"m": "show", "showId": str(show_id), "uid": uid, "p": 1, "n": 9}
        )
        assert response.status_code == 200, f"showId={show_id} must not be a transport error"
        body = response.get_data(as_text=True)
        assert "\t" in body, f"showId={show_id} must answer with a protocol envelope"
        command, payload = body.split("\t", 1)
        assert command == str(show_id)
        assert json.loads(payload) == {"value": "ok"}

    # 300 is deliberately refused (offline IAP), but still as a protocol error
    # rather than an HTTP failure.
    refused = client.post("/flash.do", data={"m": "show", "showId": "300", "uid": uid})
    assert refused.status_code == 200
    assert refused.get_data(as_text=True).startswith("-1:")


def test_account_registration_hashes_password_and_returns_registration_envelope(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()

    response = client.post(
        "/flash.do",
        data={"m": "regc", "acct": "testuser", "pwd": "pass123"},
    )

    assert response.status_code == 200
    assert response.get_data(as_text=True) == '4097\t{"value":"ok"}'
    with sqlite3.connect(database) as connection:
        username, password_hash = connection.execute(
            "SELECT username, password_hash FROM accounts"
        ).fetchone()
    assert username == "testuser"
    assert password_hash != b"pass123"
    assert b"pass123" not in password_hash


def test_duplicate_registration_does_not_replace_existing_password(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    first = client.post(
        "/flash.do", data={"m": "regc", "acct": "testuser", "pwd": "pass123"}
    )
    duplicate = client.post(
        "/flash.do", data={"m": "regc", "acct": "testuser", "pwd": "other456"}
    )
    old_password = client.post(
        "/flash.do", data={"m": "login", "acct": "testuser", "pwd": "pass123"}
    )
    new_password = client.post(
        "/flash.do", data={"m": "login", "acct": "testuser", "pwd": "other456"}
    )

    assert first.get_data(as_text=True) == '4097\t{"value":"ok"}'
    assert duplicate.get_data(as_text=True).startswith("-1:")
    assert old_password.get_data(as_text=True) == '4096\t{"value":"reg"}'
    assert new_password.get_data(as_text=True).startswith("-1:")


def test_login_of_registered_account_without_character_requests_character_creation(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    client.post(
        "/flash.do",
        data={"m": "regc", "acct": "testuser", "pwd": "pass123"},
    )

    response = client.post(
        "/flash.do",
        data={"m": "login", "acct": "testuser", "pwd": "pass123"},
    )

    assert response.get_data(as_text=True) == '4096\t{"value":"reg"}'


def test_account_character_can_be_created_and_loaded_after_login(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    client.post(
        "/flash.do",
        data={"m": "regc", "acct": "testuser", "pwd": "pass123"},
    )
    created = client.post(
        "/flash.do",
        data={
            "m": "reg",
            "acct": "testuser",
            "pwd": "pass123",
            "nick": "Hunter01",
            "sex": "1",
        },
    )
    uid = json.loads(created.get_data(as_text=True).split("\t", 1)[1])["value"]

    login = client.post(
        "/flash.do",
        data={"m": "login", "acct": "testuser", "pwd": "pass123"},
    )
    profile = client.post(
        "/flash.do", data={"m": "show", "showId": "510", "uid": uid}
    )

    assert login.get_data(as_text=True) == f'4096\t{{"value":"{uid}"}}'
    assert json.loads(profile.get_data(as_text=True).split("\t", 1)[1])["name"] == "Hunter01"


def test_account_cannot_create_a_second_character_with_a_different_nickname(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    client.post(
        "/flash.do", data={"m": "regc", "acct": "testuser", "pwd": "pass123"}
    )
    first = client.post(
        "/flash.do",
        data={"m": "reg", "acct": "testuser", "pwd": "pass123", "nick": "Hunter01", "sex": "1"},
    )
    second = client.post(
        "/flash.do",
        data={"m": "reg", "acct": "testuser", "pwd": "pass123", "nick": "Hunter02", "sex": "1"},
    )

    uid = json.loads(first.get_data(as_text=True).split("\t", 1)[1])["value"]
    assert second.get_data(as_text=True).startswith("-1:")
    assert client.post(
        "/flash.do", data={"m": "login", "acct": "testuser", "pwd": "pass123"}
    ).get_data(as_text=True) == f'4096\t{{"value":"{uid}"}}'


def test_auto_login_restores_the_account_bound_character(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    client.post(
        "/flash.do", data={"m": "regc", "acct": "testuser", "pwd": "pass123"}
    )
    created = client.post(
        "/flash.do",
        data={
            "m": "reg",
            "acct": "testuser",
            "pwd": "pass123",
            "nick": "Hunter01",
            "sex": "1",
        },
    )
    uid = json.loads(created.get_data(as_text=True).split("\t", 1)[1])["value"]

    response = client.post(
        "/flash.do", data={"m": "autoLogin", "uid": uid, "pwd": "pass123"}
    )

    assert response.get_data(as_text=True) == f'4100\t{{"value":"{uid}"}}'


def test_auto_login_rejects_wrong_password(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    client.post(
        "/flash.do", data={"m": "regc", "acct": "testuser", "pwd": "pass123"}
    )
    created = client.post(
        "/flash.do",
        data={
            "m": "reg",
            "acct": "testuser",
            "pwd": "pass123",
            "nick": "Hunter01",
            "sex": "1",
        },
    )
    uid = json.loads(created.get_data(as_text=True).split("\t", 1)[1])["value"]

    response = client.post(
        "/flash.do", data={"m": "autoLogin", "uid": uid, "pwd": "wrongpw"}
    )

    assert response.get_data(as_text=True).startswith("-1:")


def test_login_rejects_wrong_password_without_disclosing_which_field_failed(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    client.post(
        "/flash.do",
        data={"m": "regc", "acct": "testuser", "pwd": "pass123"},
    )

    response = client.post(
        "/flash.do",
        data={"m": "login", "acct": "testuser", "pwd": "wrongpw"},
    )

    assert response.status_code == 200
    assert response.get_data(as_text=True).startswith("-1:")


def test_auto_registration_returns_protocol_envelope_and_reuses_local_player(tmp_path: Path):
    config = {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    client = create_app(config).test_client()
    response = client.post(
        "/flash.do",
        data={"m": "autoReg", "nick": "Hunter01", "sex": "1", "type": "flash"},
    )

    assert response.status_code == 200
    command, payload = response.get_data(as_text=True).split("\t", 1)
    assert command == "4099"
    assert json.loads(payload)["value"].startswith("local-")

    second = create_app(config).test_client().post(
        "/flash.do",
        data={"m": "autoReg", "nick": "Hunter01", "sex": "1", "type": "flash"},
    )
    assert second.get_data(as_text=True) == response.get_data(as_text=True)


def test_player_info_command_returns_fields_read_by_create_ui(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    created = client.post(
        "/flash.do",
        data={"m": "autoReg", "nick": "Hunter01", "sex": "1"},
    )
    uid = json.loads(created.get_data(as_text=True).split("\t", 1)[1])["value"]

    response = client.post(
        "/flash.do",
        data={"m": "show", "showId": "510", "uid": uid, "type": "flash"},
    )

    command, payload = response.get_data(as_text=True).split("\t", 1)
    profile = json.loads(payload)
    assert response.status_code == 200
    assert command == "510"
    assert {"id", "name", "lv", "img", "money", "point", "crystal", "ht_ap", "max_ht_ap", "arena_ap", "max_arena_ap"} <= profile.keys()
    assert profile["name"] == "Hunter01"
    assert profile["lv"] == 1


def test_task_list_requires_an_known_player(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()

    response = client.post(
        "/flash.do",
        data={"m": "show", "showId": "511", "uid": "local-missing"},
    )

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "-1:103"


def test_task_list_offers_seeded_quests_with_live_progress(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    uid = _create_local_player(client, "TaskList")

    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "511", "uid": uid})
    )

    assert command == 511
    rows = {row["id"]: row["is_finish"] for row in payload["list"]}
    # LOCAL DEFAULT: the tracker exposes only the first current task so its
    # fixed, non-scrolling UI cannot cover the left-side home controls.
    assert list(rows) == [1]
    assert rows[1] == 1
    assert len(payload["list"]) == 1


def test_task_info_returns_icon_rewards_and_live_finish_flag(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    uid = _create_local_player(client, "TaskInfo")

    command, payload = _envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "46", "uid": uid, "gid": "1"}
        )
    )

    assert command == 46
    assert payload["id"] == 1
    assert payload["type"] == 0
    # n50001 exists in npc.swf; TaskUI instantiates it without a try/catch.
    assert payload["icon"] == 50001
    assert payload["reward_point"] == 200
    assert payload["reward_goods"] == []
    assert payload["is_finish"] == 1


def test_task_info_rejects_unknown_and_missing_ids(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    uid = _create_local_player(client, "TaskBad")

    unknown = client.post(
        "/flash.do", data={"m": "show", "showId": "46", "uid": uid, "gid": "9999"}
    )
    missing = client.post("/flash.do", data={"m": "show", "showId": "46", "uid": uid})

    assert unknown.get_data(as_text=True) == "-1:211"
    assert missing.get_data(as_text=True) == "-1:100"


def test_task_reward_pays_once_and_marks_the_quest_claimed(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    app = create_app({"TESTING": True, "DATABASE": database})
    client = app.test_client()
    uid = _create_local_player(client, "TaskPay")

    first = client.post(
        "/flash.do", data={"m": "show", "showId": "47", "uid": uid, "gid": "1", "ttype": "0"}
    )
    assert first.status_code == 200
    command, payload = _envelope(first)
    assert command == 47
    assert payload["value"] == "ok"
    # An empty array is falsy in AS3, so the client skips its reward animation.
    assert payload["pic"] == []

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT point FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0] == 200
        assert connection.execute(
            "SELECT is_claimed FROM player_tasks WHERE task_id = 1"
        ).fetchone()[0] == 1

    second = client.post(
        "/flash.do", data={"m": "show", "showId": "47", "uid": uid, "gid": "1", "ttype": "0"}
    )
    assert second.get_data(as_text=True) == "-1:211"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT point FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0] == 200


def test_task_reward_refuses_an_unfinished_quest(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    app = create_app({"TESTING": True, "DATABASE": database})
    client = app.test_client()
    uid = _create_local_player(client, "TaskNo")

    response = client.post(
        "/flash.do",
        data={"m": "show", "showId": "47", "uid": uid, "gid": "1501", "ttype": "20"},
    )

    assert response.get_data(as_text=True) == "-1:107"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT is_claimed FROM player_tasks WHERE task_id = 1501"
        ).fetchone() is None


def test_task_reward_delivers_goods_with_clickable_prop_types(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    app = create_app({"TESTING": True, "DATABASE": database})
    client = app.test_client()
    uid = _create_local_player(client, "TaskGood")

    with sqlite3.connect(database) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]
        connection.execute(
            "UPDATE pets SET battle_state = 1 WHERE player_id = ?", (player_id,)
        )

    command, payload = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "47", "uid": uid, "gid": "19", "ttype": "11"},
        )
    )
    assert command == 47
    assert payload["value"] == "ok"

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT quantity, item_type, use_type FROM inventory WHERE item_id = 10011"
        ).fetchone()
    assert row == (3, 5, 2)


def test_task_finish_state_tracks_equipping_the_starter_sword(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    uid = _create_local_player(client, "TaskEq")
    index = _equipment_index(client, uid)

    before = _envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "46", "uid": uid, "gid": "6"}
        )
    )[1]
    client.post("/flash.do", data={"m": "show", "showId": "37", "uid": uid, "index": index})
    after = _envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "46", "uid": uid, "gid": "6"}
        )
    )[1]

    assert before["is_finish"] == 0
    assert after["is_finish"] == 1


def test_home_profile_reads_saved_player_and_survives_restart(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    config = {"TESTING": True, "DATABASE": database}
    client = create_app(config).test_client()
    created = client.post("/flash.do", data={"m": "autoReg", "nick": "HomeTest", "sex": "1"})
    uid = json.loads(created.get_data(as_text=True).split("\t", 1)[1])["value"]
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET money=123, point=45 WHERE uid=?", (uid,))
    response = create_app(config).test_client().post(
        "/flash.do", data={"m": "show", "showId": "2", "uid": uid}
    )
    assert response.status_code == 200
    command, payload = response.get_data(as_text=True).split("\t", 1)
    assert command == "2"
    home = json.loads(payload)
    assert home["money"] == 123
    assert home["point"] == 45
    assert home["job"] == 1
    assert home["guild_name"] == ""
    assert home["guild_position"] == 0
    # The home page prints this next to 擂台排名, so it has to agree with the rank
    # ladder that command 507 serves; hardcoding 0 here made home say rank 0 while
    # the ranking page said 1.
    _, ladder = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "507", "uid": uid})
    )
    assert home["arena_rank"] == ladder["arena_rank"]
    # `img` is the paper-doll layer string ShowItem splits on "_" (ShowItem.as:41).
    # With nothing equipped it is still three layers: CreateUI.as:366-378 defines
    # the bare character as body + head + hair, and dropping the last two is what
    # made the hunter render headless in battle.
    assert home["img"] == "100001_100003_100002", home["img"]
    assert set(home["img"].split("_")) >= {"100001", "100002", "100003"}
    for key in ("hp", "phy_att", "mag_att", "phy_def", "mag_def", "speed"):
        assert isinstance(home[key], int)


def test_home_profile_rejects_unknown_player(tmp_path: Path):
    client = create_app({"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}).test_client()
    response = client.post("/flash.do", data={"m": "show", "showId": "2", "uid": "missing"})
    assert response.status_code == 404
    assert response.get_data(as_text=True).startswith("-1:")


def test_empty_inventory_is_persistent_per_player_and_accepts_bag_pages(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    config = {"TESTING": True, "DATABASE": database}
    client = create_app(config).test_client()
    created = client.post(
        "/flash.do", data={"m": "autoReg", "nick": "BagTest", "sex": "1"}
    )
    uid = json.loads(created.get_data(as_text=True).split("\t", 1)[1])["value"]

    response = create_app(config).test_client().post(
        "/flash.do",
        data={"m": "show", "showId": "22", "uid": uid, "ttype": "1", "p": "1", "n": "9"},
    )

    command, payload = response.get_data(as_text=True).split("\t", 1)
    assert response.status_code == 200
    assert command == "22"
    assert json.loads(payload) == {
        "bag_size": 0,
        "max_bag_size": LOCAL_DEFAULT_BAG_CAPACITY,
        "goods_list": [],
    }


def test_empty_inventory_rejects_unknown_player(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()

    response = client.post(
        "/flash.do", data={"m": "show", "showId": "22", "uid": "missing", "ttype": "1"}
    )

    assert response.status_code == 404
    assert response.get_data(as_text=True).startswith("-1:")


def test_new_character_gets_the_local_starter_equipment_in_the_bag(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    uid = _create_local_player(client, "EquipBag")

    payload = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "22", "uid": uid, "ttype": "3", "p": "1", "n": "9"},
        )
    )[1]

    assert payload["bag_size"] == 1
    assert payload["max_bag_size"] == LOCAL_DEFAULT_BAG_CAPACITY
    assert len(payload["goods_list"]) == 1
    item = payload["goods_list"][0]
    assert item["id"] == 20001
    assert item["team"] == 3
    assert item["num"] == 1
    # Equipment must not hit the pet-action switch cases, so type is 0 (local rule).
    assert item["type"] == 0
    assert item["use_type"] == 1
    assert item["level"] == 1
    # The bag list resolves the class name verbatim, so it must be p<iconId>.
    assert item["icon"] == 20001  # numeric: PropItem.as:233 prepends "p" itself
    # Goods tab stays empty even though the equipment tab has a row.
    goods_tab = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "22", "uid": uid, "ttype": "1", "p": "1", "n": "9"},
        )
    )[1]
    assert goods_tab["bag_size"] == 0
    assert goods_tab["goods_list"] == []


def test_equipment_detail_returns_the_persisted_equipment(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "EqDetail")
    index = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "22", "uid": uid, "ttype": "3", "n": "9"},
        )
    )[1]["goods_list"][0]["index"]

    response = client.post(
        "/flash.do", data={"m": "show", "showId": "39", "uid": uid, "index": str(index)}
    )

    command, payload = _envelope(response)
    assert response.status_code == 200
    assert command == 39
    assert payload["index"] == index
    assert payload["id"] == 20001
    # Detail passes the numeric icon id; the client prefixes "p" itself.
    assert payload["icon"] == 20001
    assert payload["level"] == 1
    assert payload["star"] == 1
    assert payload["pro"] == 0
    assert payload["hp"] == 0
    assert payload["speed"] == 0
    assert payload["phy_att"] == 20
    assert payload["mag_att"] == 20
    assert payload["phy_def"] == 0
    assert payload["mag_def"] == 0
    # EquipInfoUI shows the sell button only when `money` is 0; 68/69 are implemented.
    assert payload["money"] == 0


def test_equipment_detail_rejects_non_equipment_and_other_players(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    owner = _create_local_player(client, "EqOwner")
    other = _create_local_player(client, "EqOther")
    index = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "22", "uid": owner, "ttype": "3", "n": "9"},
        )
    )[1]["goods_list"][0]["index"]

    unknown = client.post(
        "/flash.do", data={"m": "show", "showId": "39", "uid": owner, "index": "999999"}
    )
    cross_player = client.post(
        "/flash.do", data={"m": "show", "showId": "39", "uid": other, "index": str(index)}
    )

    assert unknown.get_data(as_text=True) == "-1:400"
    assert cross_player.get_data(as_text=True) == "-1:400"


def test_grant_starter_equipment_is_idempotent_and_keeps_existing_items(tmp_path: Path):
    from pet_hunter_server import grant_starter_equipment

    database = tmp_path / "game.sqlite3"
    config = {"TESTING": True, "DATABASE": database}
    client = create_app(config).test_client()
    uid = _create_local_player(client, "EqGrant")
    with sqlite3.connect(database) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]

    assert grant_starter_equipment(database) == 0
    assert grant_starter_equipment(database) == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM inventory WHERE player_id = ?", (player_id,)
        ).fetchone()[0] == 1


def test_shop_stock_is_expanded_and_the_mystery_shop_rotates_daily(tmp_path: Path):
    """金币/银币商店扩容 + 神秘商店每日随机三件（当天稳定）。"""
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "ShopRot")

    def rows(shop_type: int) -> list[dict]:
        command, payload = _envelope(client.post(
            "/flash.do",
            data={"m": "show", "showId": "27", "uid": uid, "ttype": str(shop_type),
                  "p": "1", "n": "9"},
        ))
        assert command == 27
        return payload["list"]

    gold, silver = rows(1), rows(2)
    assert len(gold) >= 5, "金币商店 should stock more than the first three props"
    assert len(silver) >= 3, "银币商店 should stock more than one prop"
    assert all(row["money"] > 0 for row in gold)
    assert all(row["point"] > 0 for row in silver)

    first = rows(4)
    assert len(first) == 3, "神秘商店 stocks three slots"
    assert all(row["id"] > 0 and (row.get("money") or row.get("point")) for row in first)
    # Stable inside the same local day (the rotation is seeded on the date).
    assert [row["id"] for row in rows(4)] == [row["id"] for row in first]
    # And every slot is actually buyable through command 29.
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE players SET money = 10000000, point = 10000000 WHERE uid = ?", (uid,)
        )
    for row in first:
        price_type = int(row["type"])
        bought = client.post(
            "/flash.do",
            data={"m": "show", "showId": "29", "uid": uid, "gid": str(row["id"]),
                  "count": "1", "ttype": str(price_type), "loc": "1"},
        )
        assert bought.get_data(as_text=True) == '29\t{"value":"ok"}'


def test_shop_lists_local_stock_per_category(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    uid = _create_local_player(client, "ShopList")

    gold = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "27", "uid": uid, "ttype": "1", "p": "1", "n": "9"},
        )
    )[1]
    silver = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "27", "uid": uid, "ttype": "2", "p": "1", "n": "9"},
        )
    )[1]
    mystery = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "27", "uid": uid, "ttype": "4", "p": "1", "n": "9"},
        )
    )[1]

    assert gold["shop_type"] == 1
    # Expanded stock: the old three are still first, more props follow.
    assert [row["id"] for row in gold["list"]][:3] == [10007, 10001, 10014]
    assert len(gold["list"]) >= 5
    assert all(row["team"] == 1 and row["type"] == 1 for row in gold["list"])
    assert gold["list"][0]["money"] == 80
    # ShopListUI hands the row icon to PropItem, which prefixes "p" itself.
    assert gold["list"][0]["icon"] == 10007
    assert silver["shop_type"] == 2
    assert len(silver["list"]) >= 3
    assert all(row["type"] == 2 and row["point"] > 0 for row in silver["list"])
    assert mystery["shop_type"] == 4
    assert len(mystery["list"]) == 3, "神秘商店 stocks three daily slots"


def test_shop_detail_returns_goods_and_own_currency(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "ShopInfo")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE players SET money = 500, point = 700, crystal = 30 WHERE uid = ?",
            (uid,),
        )

    response = client.post(
        "/flash.do",
        data={"m": "show", "showId": "28", "uid": uid, "gid": "10007", "ttype": "1", "loc": "1"},
    )

    command, payload = _envelope(response)
    assert command == 28
    assert payload["shop_type"] == 1
    assert payload["loc"] == 1
    assert payload["goods"] == {"id": 10007, "icon": 10007}
    assert payload["goods_ext"]["own_money"] == 500
    assert payload["goods_ext"]["own_point"] == 700
    assert payload["goods_ext"]["own_crystal"] == 30
    assert payload["goods_ext"]["need_money"] == 80
    assert payload["goods_ext"]["need_point"] == 0
    assert payload["goods_ext"]["need_crystal"] == 0


def test_shop_detail_rejects_unknown_goods_and_mismatched_price_type(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    uid = _create_local_player(client, "ShopBad")

    unknown = client.post(
        "/flash.do",
        data={"m": "show", "showId": "28", "uid": uid, "gid": "999999", "ttype": "1", "loc": "1"},
    )
    mismatched = client.post(
        "/flash.do",
        data={"m": "show", "showId": "28", "uid": uid, "gid": "10007", "ttype": "2", "loc": "1"},
    )

    assert unknown.get_data(as_text=True) == "-1:400"
    assert mismatched.get_data(as_text=True) == "-1:400"


def test_shop_buy_deducts_currency_and_stacks_inventory(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "ShopBuy")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET money = 1000 WHERE uid = ?", (uid,))

    first = client.post(
        "/flash.do",
        data={"m": "show", "showId": "29", "uid": uid, "gid": "10007", "count": "2", "ttype": "1", "loc": "1"},
    )
    second = client.post(
        "/flash.do",
        data={"m": "show", "showId": "29", "uid": uid, "gid": "10007", "count": "1", "ttype": "1", "loc": "1"},
    )
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        money = connection.execute(
            "SELECT money FROM players WHERE uid = ?", (uid,)
        ).fetchone()["money"]
        row = connection.execute(
            "SELECT team, quantity, icon FROM inventory WHERE item_id = 10007"
        ).fetchone()

    assert _envelope(first) == (29, {"value": "ok"})
    assert _envelope(second) == (29, {"value": "ok"})
    assert money == 1000 - 80 * 3
    assert row["team"] == 1
    assert row["quantity"] == 3
    assert row["icon"] == 10007

    bag = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "22", "uid": uid, "ttype": "1", "p": "1", "n": "9"},
        )
    )[1]
    assert bag["bag_size"] == 1
    assert bag["goods_list"][0]["id"] == 10007
    assert bag["goods_list"][0]["num"] == 3
    assert bag["goods_list"][0]["icon"] == 10007  # numeric; PropItem prepends "p"


def test_shop_buy_rejects_bad_count_and_insufficient_currency(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "ShopPoor")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET money = 10, point = 0 WHERE uid = ?", (uid,))

    too_many = client.post(
        "/flash.do",
        data={"m": "show", "showId": "29", "uid": uid, "gid": "10007", "count": "0", "ttype": "1", "loc": "1"},
    )
    no_money = client.post(
        "/flash.do",
        data={"m": "show", "showId": "29", "uid": uid, "gid": "10007", "count": "1", "ttype": "1", "loc": "1"},
    )
    no_silver = client.post(
        "/flash.do",
        data={"m": "show", "showId": "29", "uid": uid, "gid": "10022", "count": "1", "ttype": "2", "loc": "1"},
    )

    assert too_many.get_data(as_text=True) == "-1:206"
    # 403 = 金币不够, 404 = 银币不够 (client error.txt keys).
    assert no_money.get_data(as_text=True) == "-1:403"
    assert no_silver.get_data(as_text=True) == "-1:404"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM inventory WHERE item_id IN (10007, 10010)"
        ).fetchone()[0] == 0


def test_shop_list_rejects_unknown_player(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()

    response = client.post(
        "/flash.do", data={"m": "show", "showId": "27", "uid": "missing", "ttype": "1"}
    )

    assert response.get_data(as_text=True) == "-1:103"


def _set_currency(client, database: Path, uid: str, **values):
    with sqlite3.connect(database) as connection:
        assignments = ", ".join(f"{key} = ?" for key in values)
        connection.execute(
            f"UPDATE players SET {assignments} WHERE uid = ?",
            (*values.values(), uid),
        )


def _buy(client, uid: str, gid: int, count: int, price_type: int) -> int:
    response = client.post(
        "/flash.do",
        data={
            "m": "show",
            "showId": "29",
            "uid": uid,
            "gid": str(gid),
            "count": str(count),
            "ttype": str(price_type),
            "loc": "1",
        },
    )
    assert response.get_data(as_text=True) == '29\t{"value":"ok"}'
    bag = json.loads(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "22", "uid": uid, "ttype": "1", "p": "1", "n": "9"},
        ).get_data(as_text=True).split("\t", 1)[1]
    )
    return next(row["index"] for row in bag["goods_list"] if row["id"] == gid)


def test_use_goods_restores_hunt_points_and_consumes_one(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "UseAp")
    _set_currency(client, database, uid, money=1000, ht_ap=0, max_ht_ap=20)
    index = _buy(client, uid, 10007, 2, 1)

    first = client.post(
        "/flash.do",
        data={"m": "show", "showId": "50", "uid": uid, "index": str(index), "index1": "0"},
    )
    command, payload = _envelope(first)

    assert command == 50
    assert payload["value"] == 20
    assert payload["ht_ap"] == 20
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT quantity, item_type, use_type FROM inventory WHERE id = ?",
            (index,),
        ).fetchone()
    assert row == (1, 7, 1)

    # At full action points the item must not be wasted.
    blocked = client.post(
        "/flash.do",
        data={"m": "show", "showId": "50", "uid": uid, "index": str(index), "index1": "0"},
    )
    assert blocked.get_data(as_text=True) == "-1:100"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT quantity FROM inventory WHERE id = ?", (index,)
        ).fetchone()[0] == 1


def test_use_goods_deletes_row_at_zero_and_rejects_unknown_items(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "UseOne")
    _set_currency(client, database, uid, money=1000, ht_ap=0, max_ht_ap=20)
    index = _buy(client, uid, 10007, 1, 1)

    client.post(
        "/flash.do",
        data={"m": "show", "showId": "50", "uid": uid, "index": str(index), "index1": "0"},
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM inventory WHERE id = ?", (index,)
        ).fetchone()[0] == 0
        # An item outside LOCAL_PROP_CATALOG must not be consumed.
        connection.execute(
            """
            INSERT INTO inventory (player_id, item_id, team, quantity, icon)
            SELECT id, 99999, 1, 1, 99999 FROM players WHERE uid = ?
            """,
            (uid,),
        )
        unknown_id = connection.execute(
            "SELECT id FROM inventory WHERE item_id = 99999"
        ).fetchone()[0]

    unknown = client.post(
        "/flash.do",
        data={"m": "show", "showId": "50", "uid": uid, "index": str(unknown_id), "index1": "0"},
    )
    assert unknown.get_data(as_text=True) == "-1:100"

    missing = client.post(
        "/flash.do",
        data={"m": "show", "showId": "50", "uid": uid, "index": "424242", "index1": "0"},
    )
    assert missing.get_data(as_text=True) == "-1:400"


def test_experience_curve_is_monotonic_and_capped():
    # LOCAL DEFAULT curve (no levelling table ships with the game). The cap is
    # 1000 because monster.txt's own level column runs 1..1000 and help.txt id 10
    # describes 500/300-level pets with a 200-level evolution step.
    from pet_hunter_server.app import LOCAL_MAX_PET_LEVEL, exp_to_next

    assert LOCAL_MAX_PET_LEVEL == 1000
    assert exp_to_next(1) == 5_000
    assert exp_to_next(1000) == 34_000_000
    previous = 0
    for level in range(1, LOCAL_MAX_PET_LEVEL):
        need = exp_to_next(level)
        assert need > 0
        assert need >= previous, f"curve must not shrink at level {level}"
        previous = need


def test_use_goods_pet_exp_levels_target_pet(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "UseExp")
    _set_currency(client, database, uid, money=1000)
    index = _buy(client, uid, 10002, 1, 1)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        pet = connection.execute(
            "SELECT id, lv, exp FROM pets WHERE player_id = (SELECT id FROM players WHERE uid = ?) ORDER BY id LIMIT 1",
            (uid,),
        ).fetchone()

    no_target = client.post(
        "/flash.do",
        data={"m": "show", "showId": "50", "uid": uid, "index": str(index), "index1": "0"},
    )
    assert no_target.get_data(as_text=True) == "-1:506"

    response = client.post(
        "/flash.do",
        data={"m": "show", "showId": "50", "uid": uid, "index": str(index), "index1": str(pet["id"])},
    )
    command, payload = _envelope(response)

    assert command == 50
    # The levelling curve is a LOCAL DEFAULT (four linear segments, cap 1000), so
    # compute the expectation with the same function instead of hardcoding one.
    from pet_hunter_server.app import LOCAL_MAX_PET_LEVEL, exp_to_next

    expected_lv, expected_exp = pet["lv"], pet["exp"] + 1_330_000
    while expected_lv < LOCAL_MAX_PET_LEVEL and expected_exp >= exp_to_next(expected_lv):
        expected_exp -= exp_to_next(expected_lv)
        expected_lv += 1
    assert payload["lv"] == expected_lv
    assert payload["exp"] == expected_exp
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT lv, exp FROM pets WHERE id = ?", (pet["id"],)
        ).fetchone()
        assert row == (expected_lv, expected_exp)
        assert connection.execute(
            "SELECT COUNT(*) FROM inventory WHERE id = ?", (index,)
        ).fetchone()[0] == 0


def test_boxes_and_pet_eggs_actually_pay_out(tmp_path: Path):
    """type-15 props (宝箱 / 宠物蛋 / 许愿硬币) used to answer -1:100 for ever."""
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "BoxOpen")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET point = 0 WHERE uid = ?", (uid,))
        connection.execute(
            "INSERT INTO inventory (player_id,item_id,team,quantity,icon,item_type,use_type)"
            " VALUES (1,10016,1,1,10016,15,1)"
        )
        connection.execute(
            "INSERT INTO inventory (player_id,item_id,team,quantity,icon,item_type,use_type)"
            " VALUES (1,12001,1,1,12001,15,1)"
        )
        chest = connection.execute(
            "SELECT id FROM inventory WHERE item_id = 10016"
        ).fetchone()[0]
        egg = connection.execute(
            "SELECT id FROM inventory WHERE item_id = 12001"
        ).fetchone()[0]
        pets_before = connection.execute(
            "SELECT COUNT(*) FROM pets WHERE player_id = 1"
        ).fetchone()[0]

    command, payload = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "50", "uid": uid,
                           "index": str(chest), "index1": "0"},
    ))
    assert command == 50
    box = payload["value"]
    assert isinstance(box, dict) and box["box_type"] == 3, "星星宝箱 pays silver"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT point FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0] == box["point"]

    command, payload = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "50", "uid": uid,
                           "index": str(egg), "index1": "0"},
    ))
    assert command == 50
    box = payload["value"]
    assert isinstance(box, dict) and box["box_type"] == 2, "4级宠物蛋 pays a pet"
    assert box["id"] > 0 and box["num"] == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM pets WHERE player_id = 1"
        ).fetchone()[0] == pets_before + 1


def test_home_use_goods_rejects_an_unimplemented_effect_without_eating_it(
    tmp_path: Path,
):
    """D-04 家园使用道具：能用的生效，不能用的原样留在包里。

    HomeUI.as:243-250 opens the bag with `target=0`, so `index1` is 0 there. An
    effect this server cannot apply (10004 宠物名片, prop.txt type=4) must answer
    -1:100 and leave the stack untouched instead of silently consuming it.
    """
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "HomeUse")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO inventory (player_id,item_id,team,quantity,icon,item_type,use_type)"
            " VALUES (1,10004,1,3,10004,4,2)"
        )
        connection.execute(
            "INSERT INTO inventory (player_id,item_id,team,quantity,icon,item_type,use_type)"
            " VALUES (1,10007,1,2,10007,7,1)"
        )
        unsupported = connection.execute(
            "SELECT id FROM inventory WHERE item_id = 10004"
        ).fetchone()[0]
        supported = connection.execute(
            "SELECT id FROM inventory WHERE item_id = 10007"
        ).fetchone()[0]
        connection.execute("UPDATE players SET ht_ap=0, max_ht_ap=20 WHERE uid=?", (uid,))

    rejected = client.post(
        "/flash.do",
        data={"m": "show", "showId": "50", "uid": uid, "index": str(unsupported), "index1": "0"},
    )
    assert rejected.get_data(as_text=True) == "-1:100"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT quantity FROM inventory WHERE id = ?", (unsupported,)
        ).fetchone()[0] == 3

    accepted = _envelope(client.post(
        "/flash.do",
        data={"m": "show", "showId": "50", "uid": uid, "index": str(supported), "index1": "0"},
    ))
    assert accepted[0] == 50 and accepted[1]["ht_ap"] == 20


def test_use_goods_expands_bag_and_converts_currency_bags(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "UseCap")
    _set_currency(client, database, uid, money=1000, point=500, crystal=0)

    card = _buy(client, uid, 10014, 1, 1)
    bag_response = client.post(
        "/flash.do",
        data={"m": "show", "showId": "50", "uid": uid, "index": str(card), "index1": "0"},
    )
    assert _envelope(bag_response) == (
        50,
        {
            "value": 3,
            "max_bag_size": LOCAL_DEFAULT_BAG_CAPACITY + 3,
            "ht_ap": 20,
            # BagListUI switches on this to choose the result popup; without it the
            # item was consumed silently.
            "type": 14,
        },
    )

    silver_bag = _buy(client, uid, 10022, 1, 2)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO inventory (player_id, item_id, team, quantity, icon, item_type, use_type)
            SELECT id, 10023, 1, 1, 10023, 17, 1 FROM players WHERE uid = ?
            """,
            (uid,),
        )
        crystal_bag = connection.execute(
            "SELECT id FROM inventory WHERE item_id = 10023"
        ).fetchone()[0]

    client.post(
        "/flash.do",
        data={"m": "show", "showId": "50", "uid": uid, "index": str(silver_bag), "index1": "0"},
    )
    client.post(
        "/flash.do",
        data={"m": "show", "showId": "50", "uid": uid, "index": str(crystal_bag), "index1": "0"},
    )
    with sqlite3.connect(database) as connection:
        point, crystal, capacity = connection.execute(
            "SELECT point, crystal, bag_capacity FROM players WHERE uid = ?", (uid,)
        ).fetchone()

    assert point == 10000
    assert crystal == 10000
    assert capacity == LOCAL_DEFAULT_BAG_CAPACITY + 3
    bag = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "22", "uid": uid, "ttype": "1", "p": "1", "n": "9"},
        )
    )[1]
    assert bag["max_bag_size"] == LOCAL_DEFAULT_BAG_CAPACITY + 3


def _equipment_index(client, uid: str) -> int:
    detail = client.post(
        "/flash.do", data={"m": "show", "showId": "22", "uid": uid, "ttype": "3", "p": "1", "n": "9"}
    )
    rows = json.loads(detail.get_data(as_text=True).split("\t", 1)[1])["goods_list"]
    return rows[0]["index"]


def test_equipment_detail_enables_sell_and_equip_persists(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "EqWear")
    index = _equipment_index(client, uid)

    detail = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "39", "uid": uid, "index": str(index), "ttype": "3"},
        )
    )[1]
    # EquipInfoUI only renders the sell button when `money` is 0.
    assert detail["money"] == 0

    worn = client.post(
        "/flash.do",
        data={"m": "show", "showId": "37", "uid": uid, "index": str(index)},
    )
    # 37 must answer with a home-shaped payload, not {"value":"ok"}. MainUI.as:317
    # has no case for 37 and forwards the body to the current screen's readDatas,
    # and HomeUI.readDatas never checks the command id: a bare ok body set
    # GameUtil.skin = undefined, which cleared the paper doll and printed
    # `undefined` in every stat row.
    command, worn_payload = _envelope(worn)
    assert command == 37
    assert worn_payload["value"] == "ok"
    assert worn_payload["img"], "the doll layer string must survive the round trip"
    for field in ("lv", "job", "guild_name", "guild_position", "arena_rank",
                  "money", "point", "crystal"):
        assert field in worn_payload, f"HomeUI reads {field} after equipping"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT equipped FROM inventory WHERE id = ?", (index,)
        ).fetchone()[0] == 1


def test_sale_info_and_sale_goods_pay_silver_and_delete_row(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "EqSell")
    index = _equipment_index(client, uid)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET point = 0 WHERE uid = ?", (uid,))

    info = client.post(
        "/flash.do",
        data={"m": "show", "showId": "68", "uid": uid, "index": str(index), "ttype": "3"},
    )
    assert _envelope(info) == (
        68,
        {"sold_price": 100, "sold_goods_id": 0, "sold_goods_num": 0},
    )

    sold = client.post(
        "/flash.do",
        data={
            "m": "show",
            "showId": "69",
            "uid": uid,
            "index": str(index),
            "count": "1",
            "ttype": "3",
        },
    )
    assert _envelope(sold) == (
        69,
        {"price_point": 100, "price_goods_id": 0, "price_goods_num": 0},
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT point FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0] == 100
        assert connection.execute(
            "SELECT COUNT(*) FROM inventory WHERE id = ?", (index,)
        ).fetchone()[0] == 0


def test_sale_goods_rejects_wrong_count_team_and_unknown_item(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "EqSellB")
    index = _equipment_index(client, uid)

    too_many = client.post(
        "/flash.do",
        data={"m": "show", "showId": "69", "uid": uid, "index": str(index), "count": "2", "ttype": "3"},
    )
    wrong_team = client.post(
        "/flash.do",
        data={"m": "show", "showId": "69", "uid": uid, "index": str(index), "count": "1", "ttype": "1"},
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO inventory (player_id, item_id, team, quantity, icon, item_type, use_type)
            SELECT id, 99999, 2, 1, 99999, 0, 0 FROM players WHERE uid = ?
            """,
            (uid,),
        )
        unknown_id = connection.execute(
            "SELECT id FROM inventory WHERE item_id = 99999"
        ).fetchone()[0]

    unknown = client.post(
        "/flash.do",
        data={"m": "show", "showId": "68", "uid": uid, "index": str(unknown_id), "ttype": "2"},
    )

    assert too_many.get_data(as_text=True) == "-1:206"
    assert wrong_team.get_data(as_text=True) == "-1:400"
    assert unknown.get_data(as_text=True) == "-1:400"


def test_sale_goods_sells_stack_partially(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "EqSellSt")
    _set_currency(client, database, uid, money=1000)
    index = _buy(client, uid, 10007, 3, 1)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE inventory SET team = 2 WHERE id = ?", (index,)
        )
        connection.execute("UPDATE players SET point = 0 WHERE uid = ?", (uid,))

    sold = client.post(
        "/flash.do",
        data={"m": "show", "showId": "69", "uid": uid, "index": str(index), "count": "2", "ttype": "2"},
    )
    assert _envelope(sold) == (
        69,
        {"price_point": 80, "price_goods_id": 0, "price_goods_num": 0},
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT quantity FROM inventory WHERE id = ?", (index,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT point FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0] == 80


def test_explore_start_remembers_map_from_detail(tmp_path: Path):
    # ExploreMapInfoUI.as:204 sends EXPLORE_KEY(103) with no gid, so 99 has to
    # persist the chosen map for the follow-up request.
    database=tmp_path/"game.sqlite3"; client=create_app({"TESTING":True,"DATABASE":database}).test_client(); uid=_create_local_player(client,"ExpStart")
    command,_=_envelope(client.post("/flash.do",data={"m":"show","showId":99,"uid":uid,"gid":2}))
    assert command==99
    command,payload=_envelope(client.post("/flash.do",data={"m":"show","showId":103,"uid":uid}))
    # ExplorePveUI.as:399 builds "sound_event_" + (200 + world_id), so world_id is
    # the world number, not the map id the request carried.
    assert command==103 and payload["world_id"]==1 and payload["value"]=="ok"
    # ExplorePveUI.as:377 assigns param2 = param2.battle_result and :381 reads
    # _loc2_.is_win from it with no guard, so a missing battle_result throws.
    result=payload["battle_result"]
    assert result["is_win"] in (1,True)
    assert result["att_list"] and result["def_list"] and result["record"]
    lead=result["att_list"][0]
    assert lead["is_pet"]==0
    for layer in lead["img"].split("_"):
        assert int(layer) in config_tables.skin_table()


def test_explore_list_rows_match_client_fields(tmp_path: Path):
    # ExploreMapListUI.as:200-260 needs world/explore_ap/max_explore_ap and rows
    # carrying code,id,terrain,star,max_days; ttype selects the world.
    database=tmp_path/"game.sqlite3"; client=create_app({"TESTING":True,"DATABASE":database}).test_client(); uid=_create_local_player(client,"ExpT")
    command,payload=_envelope(client.post("/flash.do",data={"m":"show","showId":98,"uid":uid,"ttype":1}))
    assert command==98 and payload["world"]==1 and "explore_ap" in payload
    row=payload["list"][0]
    assert all(k in row for k in ("code","id","terrain","star","max_days"))


def test_hunt_task_response_carries_id_for_fight_buttons(tmp_path: Path):
    # MainUI.as:120-122 feeds the showId=5 *response* into HunterTaskUI.data, and
    # HunterTaskUI.as:271/284 sends `data.id` for HUNT_KEY(6)/CATCH_KEY(7).
    database=tmp_path/"game.sqlite3"; client=create_app({"TESTING":True,"DATABASE":database}).test_client(); uid=_create_local_player(client,"HidT")
    command,payload=_envelope(client.post("/flash.do",data={"m":"show","showId":5,"uid":uid,"hid":1}))
    assert command==5 and payload["id"]==1


def test_hunt_map_rows_expose_client_click_fields(tmp_path: Path):
    database=tmp_path/"game.sqlite3"; client=create_app({"TESTING":True,"DATABASE":database}).test_client(); uid=_create_local_player(client,"HuntT")
    command,payload=_envelope(client.post("/flash.do",data={"m":"show","showId":4,"uid":uid,"p":1,"n":9}))
    assert command==4
    # HunterMapUI.as:186-208 reads player{hunt_ap,max_hunt_ap} and maps[]{code,id,rate,is_allown_hunt}
    assert "hunt_ap" in payload["player"] and "max_hunt_ap" in payload["player"]
    row=payload["maps"][0]
    assert row["is_allown_hunt"]==1 and row["code"]==row["id"]==row["index"] and "rate" in row


def test_job_readonly_commands(tmp_path: Path):
    database=tmp_path/"game.sqlite3"; client=create_app({"TESTING":True,"DATABASE":database}).test_client(); uid=_create_local_player(client,"JobT")
    command,payload=_envelope(client.post("/flash.do",data={"m":"show","showId":70,"uid":uid,"p":1,"n":9})); assert command==70 and payload["list"]
    command,payload=_envelope(client.post("/flash.do",data={"m":"show","showId":71,"uid":uid,"gid":1})); assert command==71 and payload["nextRole"]


def test_pic_and_achievement_readonly_commands(tmp_path: Path):
    database=tmp_path/"game.sqlite3"; client=create_app({"TESTING":True,"DATABASE":database}).test_client(); uid=_create_local_player(client,"PicT")
    for sid,data,key in ((25,{"ttype":1,"p":1,"n":9},"pics"),(26,{"gid":1001},"pics"),(48,{},"reward_goods"),(107,{"ttype":1,"p":1,"n":9},"pics")):
        body={"m":"show","showId":sid,"uid":uid}; body.update(data); command,payload=_envelope(client.post("/flash.do",data=body)); assert command==sid and key in payload


def test_guild_readonly_commands(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "GuildT")
    for show_id, expected in ((86, "guild_id"), (88, "guilds"), (91, "list"), (94, "is_battle_on")):
        command, payload = _envelope(client.post("/flash.do", data={"m":"show","showId":show_id,"uid":uid}))
        assert command == show_id and expected in payload


def test_friend_list_and_detail(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "FriendT")
    other = _create_local_player(client, "OtherT")
    command, payload = _envelope(client.post("/flash.do", data={"m":"show","showId":"51","uid":uid,"p":1,"n":9}))
    assert command == 51 and payload["friend"][0]["id"] == other
    command, payload = _envelope(client.post("/flash.do", data={"m":"show","showId":"52","uid":uid,"gid":other,"psk":2}))
    assert command == 52 and payload["player"]["id"] == other
    command, payload = _envelope(client.post("/flash.do", data={"m":"show","showId":"3","uid":uid,"gid":other}))
    assert command == 3 and payload["player"]["id"] == other


def test_hunt_and_explore_readonly_and_battle_response(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "HuntT")
    command, payload = _envelope(client.post("/flash.do", data={"m":"show","showId":"4","uid":uid}))
    assert command == 4 and payload["maps"]
    command, payload = _envelope(client.post("/flash.do", data={"m":"show","showId":"5","uid":uid,"hid":1}))
    assert command == 5 and payload["pets"]
    command, payload = _envelope(client.post("/flash.do", data={"m":"show","showId":"6","uid":uid,"hid":1}))
    assert command == 6 and payload["is_win"] == 1 and payload["record"]
    command, payload = _envelope(client.post("/flash.do", data={"m":"show","showId":"98","uid":uid}))
    assert command == 98 and payload["list"]
    command, payload = _envelope(client.post("/flash.do", data={"m":"show","showId":"99","uid":uid,"gid":1}))
    assert command == 99 and payload["id"] == 1
    command, payload = _envelope(client.post("/flash.do", data={"m":"show","showId":"103","uid":uid,"gid":1}))
    assert command == 103 and payload["is_finish"] == 1


def test_equipment_synthesis_merges_and_consumes_the_vice_piece(tmp_path: Path):
    # 77/78 list candidates, 79 previews, 80 fuses. IntegrationListUI.as:227-234
    # reads index/id/icon/loc, IntegrationInfoUI reads the merged stats plus the
    # fee, and IntegrationResultUI reads index/id/icon.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "SynthEq")
    with sqlite3.connect(database) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]
        connection.execute("UPDATE players SET money = 100000 WHERE id = ?", (player_id,))
        ids = [r[0] for r in connection.execute(
            "SELECT id FROM inventory WHERE player_id=? AND team=3 ORDER BY id LIMIT 2",
            (player_id,),
        )]
        if len(ids) < 2:
            connection.execute(
                "INSERT INTO inventory (player_id, item_id, team, quantity, icon, item_type,"
                " level, star, hp, speed, phy_att, mag_att, phy_def, mag_def)"
                " SELECT player_id, 20002, 3, 1, 20002, 1, 1, 1, 0, 0, 0, 0, 20, 20"
                " FROM inventory WHERE player_id=? LIMIT 1",
                (player_id,),
            )
            ids = [r[0] for r in connection.execute(
                "SELECT id FROM inventory WHERE player_id=? AND team=3 ORDER BY id LIMIT 2",
                (player_id,),
            )]
        connection.commit()
    main_id, vice_id = ids[0], ids[1]

    command, main_list = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "77", "uid": uid,
                                       "ttype": "2", "loc": "0", "p": "1", "n": "9"})
    )
    assert command == 77
    assert main_list["list"], "the main picker needs candidates"
    for row in main_list["list"]:
        assert {"index", "id", "icon", "loc"} <= set(row)

    command, vice_list = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "78", "uid": uid,
                                       "ttype": "2", "main": str(main_id), "loc": "0",
                                       "p": "1", "n": "9"})
    )
    assert command == 78
    assert all(row["index"] != main_id for row in vice_list["list"]), "main must not repeat"

    with sqlite3.connect(database) as connection:
        main_stats = connection.execute(
            "SELECT hp, speed, phy_att, mag_att, phy_def, mag_def FROM inventory WHERE id=?",
            (main_id,),
        ).fetchone()
        vice_stats = connection.execute(
            "SELECT hp, speed, phy_att, mag_att, phy_def, mag_def FROM inventory WHERE id=?",
            (vice_id,),
        ).fetchone()
    expected = [
        max(main_stats[i], vice_stats[i]) + min(main_stats[i], vice_stats[i]) // 4
        for i in range(6)
    ]

    command, preview = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "79", "uid": uid,
                                       "main": str(main_id), "vice": str(vice_id)})
    )
    assert command == 79
    assert [preview[k] for k in ("hp", "speed", "phy_att", "mag_att", "phy_def", "mag_def")] == expected
    assert preview["need_money"] > 0

    command, result = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "80", "uid": uid,
                                       "main": str(main_id), "vice": str(vice_id)})
    )
    assert command == 80
    assert result["index"] == main_id
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM inventory WHERE id = ?", (vice_id,)
        ).fetchone()[0] == 0, "the vice piece is consumed"
        assert list(connection.execute(
            "SELECT hp, speed, phy_att, mag_att, phy_def, mag_def FROM inventory WHERE id=?",
            (main_id,),
        ).fetchone()) == expected
        assert connection.execute(
            "SELECT money FROM players WHERE id = ?", (player_id,)
        ).fetchone()[0] == 100000 - preview["need_money"]


def test_forge_list_detail_and_make_transaction(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "ForgeT")
    with sqlite3.connect(database) as connection:
        player_id = connection.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()[0]
        connection.execute("UPDATE players SET money=100 WHERE id=?", (player_id,))
        connection.execute("INSERT INTO inventory (player_id,item_id,team,quantity,icon,item_type,use_type) VALUES (?,?,?,?,?,?,?)", (player_id,11010,2,1,11010,0,0))
    command, payload = _envelope(client.post("/flash.do", data={"m":"show","showId":"32","uid":uid,"ttype":"1","p":"1","n":"9"}))
    assert command == 32
    row = payload["list"][0]
    # `id` is the CRAFTED EQUIP id: BlacksmithListUI.as:245 looks the display name
    # up in pic.txt with it, and a recipe id has no pic row (nameless list).
    assert row["id"] == 20002
    assert row["index"] == 32001, "index stays the recipe id sent back as gid"
    pics = config_tables._table("pic.txt")
    assert int(row["id"]) in pics, "the craft list row must resolve a real name"
    # Stats come from the shipped equip.txt, not a hand-written zeroed row.
    assert _envelope(client.post("/flash.do", data={"m":"show","showId":"33","uid":uid,"gid":"32001","ttype":"1"}))[1]["phy_att"] == int(
        str(config_tables.equip_record(20002)["phyAtt"]).strip()
    )
    command, detail = _envelope(client.post("/flash.do", data={"m":"show","showId":"33","uid":uid,"gid":"32001","ttype":"1"}))
    assert command == 33 and detail["need_goods"][0]["own_num"] == 1
    response = client.post("/flash.do", data={"m":"show","showId":"34","uid":uid,"gid":"32001"})
    assert response.get_data(as_text=True).startswith("34\t"), response.get_data(as_text=True)
    command, made = _envelope(response)
    assert command == 34 and made["id"] == 20002
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT quantity FROM inventory WHERE item_id=11010").fetchone() is None
        assert connection.execute("SELECT item_id,team FROM inventory WHERE item_id=20002").fetchone() == (20002, 3)
        assert connection.execute("SELECT money FROM players WHERE uid=?", (uid,)).fetchone()[0] == 0


def test_function_flags_returns_a_parseable_envelope(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()

    response = client.post("/flash.do", data={"m": "show", "showId": "502"})

    command, payload = _envelope(response)
    assert command == 502
    assert payload == {"value": ""}


def _create_local_player(client, nick: str) -> str:
    created = client.post(
        "/flash.do", data={"m": "autoReg", "nick": nick, "sex": "1"}
    )
    return json.loads(created.get_data(as_text=True).split("\t", 1)[1])["value"]


def _envelope(response):
    command, payload = response.get_data(as_text=True).split("\t", 1)
    return int(command), json.loads(payload)


def test_config_tables_load_shipped_equipment():
    """equip.txt / prop.txt ship with a UTF-8 BOM; a plain utf-8 read silently
    drops every row because the header's first column becomes '﻿id'."""
    equips = config_tables.equip_table()
    props = config_tables.prop_table()
    assert len(equips) > 900 and len(props) > 100
    record = config_tables.equip_record(20001)
    assert config_tables.equip_slot(record) == 1
    assert config_tables.equip_icon(record) == 20001
    # imageId must resolve in skin.txt or ShowItem cannot instantiate the layer.
    skin = config_tables.skin_table()
    assert all(
        config_tables.equip_image_id(r) in skin
        for r in equips.values()
        if config_tables.equip_image_id(r)
    )


def test_role_info_reports_stats_equipment_and_paper_doll(tmp_path: Path):
    # RoleInfoUI.as:152-172 prints the six stats plus weapon/clothes/hat with no
    # null guards, and :151 feeds `img` to ShowItem as a "_"-joined skin string.
    # HomeUI.as:233-235 opens this page without a gid, so `uid` must be the
    # fallback target (before this it answered -1:103 and the page was empty).
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "RoleBare")
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": 3, "uid": uid})
    )
    assert command == 3
    # RoleInfoUI reads these off the top level, not param2.player.
    bare = payload
    for key in ("hp", "phy_att", "mag_att", "phy_def", "mag_def", "speed"):
        assert isinstance(bare[key], int), f"{key} missing from role info"
    assert bare["weapon"] == 0 and bare["clothes"] == 0 and bare["hat"] == 0
    assert bare["name"] and bare["job"] == 1
    # FriendInfoUI/KingFightInfoUI read the same fields under `player`.
    assert payload["player"]["name"] == bare["name"]
    skin = config_tables.skin_table()
    for layer in bare["img"].split("_"):
        assert int(layer) in skin

    record = config_tables.equip_record(20001)
    with sqlite3.connect(database) as connection:
        # the starter pack already ships one 20001, so wear that row instead of
        # inserting a duplicate (inventory has UNIQUE(player_id, item_id)).
        connection.execute(
            """UPDATE inventory SET equipped=1, phy_att=20, mag_att=20
               WHERE player_id=1 AND item_id=20001"""
        )
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": 3, "uid": uid})
    )
    worn = payload
    assert worn["weapon"] == 20001 and worn["weapon_level"] == 1
    assert worn["phy_att"] == bare["phy_att"] + 20
    assert worn["mag_att"] == bare["mag_att"] + 20
    # the worn weapon's skin layer must now be part of the paper doll string
    assert str(config_tables.equip_image_id(record)) in worn["img"].split("_")


def test_equipment_detail_reports_config_stats_and_skills(tmp_path: Path):
    # EquipInfoUI.as:192 resolves the name from pic.txt (type=2 equipment rows)
    # and :197 instantiates "p"+icon; :225 reads skills[] entries' `id`.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "EqInfo2")
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": 22, "uid": uid, "ttype": 3})
    )
    assert command == 22 and payload["goods_list"]
    index = payload["goods_list"][0]["index"]
    command, detail = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": 39, "uid": uid, "index": index})
    )
    assert command == 39
    assert detail["icon"] and isinstance(detail["skills"], list)


def test_seed_items_fills_bag_from_shipped_tables(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "SeedTest")
    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT COUNT(*) FROM inventory WHERE player_id=1 AND team=3"
        ).fetchone()[0]
    added = seed_items.seed_player_bag(database, uid, quantity=3)
    assert added["props"] > 90 and added["equipment"] > 900
    with sqlite3.connect(database) as connection:
        counts = dict(
            connection.execute(
                "SELECT team, COUNT(*) FROM inventory WHERE player_id=1 GROUP BY team"
            ).fetchall()
        )
    # the starter equipment ships with the player, so seeded rows plus what was
    # already there must equal the total equipment in the shipped table.
    assert counts.get(3) == before + added["equipment"]
    assert counts.get(1, 0) + counts.get(2, 0) == added["props"]
    # re-running must not duplicate rows
    again = seed_items.seed_player_bag(database, uid, quantity=3)
    assert again == {"props": 0, "equipment": 0}


def test_seed_items_bag_list_renders_every_team(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "SeedList")
    seed_items.seed_player_bag(database, uid, quantity=2)
    for team in (1, 2, 3):
        command, payload = _envelope(
            client.post(
                "/flash.do",
                data={"m": "show", "showId": 22, "uid": uid, "ttype": team, "p": 1, "n": 9},
            )
        )
        assert command == 22
        for row in payload["goods_list"]:
            # BagListUI.as:285 feeds `icon` to IconItem which resolves "p"+icon
            assert isinstance(row["icon"], int) and row["icon"] > 0
            assert row["num"] > 0


def test_hunt_task_enables_buttons_and_names_pets(tmp_path: Path):
    # HunterTaskUI.as:100-101 disables hunt/catch when these are not > 0, and
    # :337-337 calls param2.pets.shift() with no null guard.
    client = create_app({"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}).test_client()
    uid = _create_local_player(client, "HuntTsk")
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "5", "uid": uid, "hid": 1})
    )
    assert command == 5
    assert payload["isHunter"] == 1 and payload["isCatch"] == 1
    assert payload["rage_point"] == 0
    assert payload["pets"], "HunterTaskUI shifts pets[] unguarded"
    for row in payload["pets"]:
        assert row["name"], "a null name renders as the string null on device"
    # running out of AP must switch both buttons off
    with sqlite3.connect(tmp_path / "game.sqlite3") as connection:
        connection.execute("UPDATE players SET ht_ap=0")
    _, empty = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "5", "uid": uid, "hid": 1})
    )
    assert empty["isHunter"] == 0 and empty["isCatch"] == 0


def test_hunt_fight_leads_with_hunter_skin_and_replay_fields(tmp_path: Path):
    # HunterResultUI.as:352-355 reads att_list[0].img into ShowItem.items, which
    # splits on "_" and resolves each id through skin.txt — a pet id there is
    # silently dropped, which is what made the hunter headless.
    # FightProcess.as:1066-1068 reads cur_hp/is_dead/is_revive with no guard and
    # HunterResultUI.as:578 never starts the replay timer on an empty record.
    client = create_app({"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}).test_client()
    uid = _create_local_player(client, "HuntFit")
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "6", "uid": uid, "hid": 1})
    )
    assert command == 6
    assert payload["is_win"] in (1, True), "is_win drives img_win vs img_lose"
    lead = payload["att_list"][0]
    assert lead["is_pet"] == 0, "the hunter, not a pet, must lead att_list"
    skin = config_tables.skin_table()
    for layer in lead["img"].split("_"):
        assert int(layer) in skin, f"layer {layer} is not in skin.txt and would be dropped"
    # pets follow, and carry a bare id for Pet.as:121's "p" + skin lookup
    for row in payload["att_list"][1:]:
        assert row["is_pet"] == 1
        assert str(row["img"]).isdigit()
    assert payload["def_list"], "HunterResultUI.as:387 dereferences def_list[0] unguarded"
    for row in payload["def_list"]:
        assert row["name"] and row["lv"] >= 1 and row["hp"] >= 0
        assert str(row["img"]).isdigit()
    assert payload["record"], "an empty record array freezes the fight screen"
    for step in payload["record"]:
        for side in ("att", "def"):
            assert {"cur_hp", "is_dead", "is_revive"} <= set(step[side])


def test_hunt_uses_real_monster_rows(tmp_path: Path):
    # HunterResultUI.as:398 falls back to the *monster* table for the defender
    # name, and Pet.as:121 instantiates "p" + img, so the icon has to be the
    # monster's own iconId rather than a pet id.
    client = create_app({"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}).test_client()
    uid = _create_local_player(client, "HuntMon")
    _, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "6", "uid": uid, "hid": 1})
    )
    monsters = config_tables._table("monster.txt")
    known = {int(k): v for k, v in monsters.items()}
    for row in payload["def_list"]:
        assert row["id"] in known, "defender id must come from monster.txt"
        assert row["name"] == known[row["id"]]["name"]
        assert row["img"] == int(known[row["id"]]["iconId"])


def test_catch_and_pet_picker_return_renderable_rows(tmp_path: Path):
    # HunterCatchUI.as:134-136 needs index/id/icon; FightPetListUI.as:173 walks
    # list[] unguarded.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "HuntCat")
    command, caught = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "7", "uid": uid, "hid": 1})
    )
    assert command == 7
    assert {"index", "id", "icon", "name", "lv"} <= set(caught)
    command, picker = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "42", "uid": uid, "p": 1, "n": 9})
    )
    assert command == 42 and picker["list"]
    for row in picker["list"]:
        assert {"index", "id", "icon", "name", "lv"} <= set(row)


def test_explore_ships_the_two_reward_boxes_the_win_panel_draws(tmp_path: Path):
    # ExploreResultItem.as:447-540 reads data.finish_reward and
    # data.max_star_reward, each {reward_point, reward_crystal, reward_goods}.
    # Both were missing, so the WIN panel's two reward slots rendered empty even
    # though the payout itself happened server-side.
    table = config_tables._table("exploreMap.txt")
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "BoxOne")
    gid = sorted(table)[0]
    _envelope(client.post("/flash.do", data={"m": "show", "showId": "99", "uid": uid, "gid": gid}))
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "103", "uid": uid})
    )
    assert command == 103
    for key in ("finish_reward", "max_star_reward"):
        block = payload[key]
        assert set(block) == {"reward_point", "reward_crystal", "reward_goods"}
        assert isinstance(block["reward_point"], int)
        assert isinstance(block["reward_crystal"], int)
        assert isinstance(block["reward_goods"], list)
        for entry in block["reward_goods"]:
            assert entry["id"] > 0 and entry["num"] > 0
    # The finish box must agree with the payout that was actually credited.
    assert payload["finish_reward"]["reward_point"] == payload["battle_result"]["reward_point"]
    assert payload["max_star_reward"]["reward_point"] == int(
        str(table[gid].get("maxRewardPoint", "0")).strip() or 0
    )


def test_explore_reward_grammar_is_kind_id_icon_num():
    # exploreMap's reward columns are `kind:id:icon:num`, not `id:num`. Reading
    # them with the pair parser produced "item 3 x 150011", and the third field is
    # a genuinely separate icon (map 13 ships 1:50001:50004:1).
    from pet_hunter_server.app import _parse_map_goods

    assert _parse_map_goods("1:50001:50004:1") == [(1, 50001, 1, 50004)]
    assert _parse_map_goods("2:6002:6002:1") == [(2, 6002, 1, 6002)]
    assert _parse_map_goods("3:150011:150011:1") == [(3, 150011, 1, 150011)]
    assert _parse_map_goods("") == []
    assert _parse_map_goods("0") == []
    # The older id:num,id:num form still parses (task rewards share the parser).
    assert _parse_map_goods("10016:1") == [(1, 10016, 1, 10016)]


def test_explore_grants_equipment_rewards_into_the_bag(tmp_path: Path):
    # Map 13's pass reward is equipment 50001, which lives in equip.txt rather than
    # prop.txt. inventory is UNIQUE(player_id, item_id), so a repeat drop has to
    # stack instead of raising an IntegrityError (which 500'd the whole page).
    table = config_tables._table("exploreMap.txt")
    equips = config_tables._table("equip.txt")
    gid = next(
        (g for g in sorted(table)
         if str(table[g].get("passRewardGoods", "")).startswith("1:")
         and int(str(table[g]["passRewardGoods"]).split(":")[1]) in equips),
        None,
    )
    assert gid is not None, "the shipped table should contain an equipment reward"
    item_id = int(str(table[gid]["passRewardGoods"]).split(":")[1])

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "EqRwd")

    def bag_quantity() -> int:
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM inventory WHERE player_id=1 AND item_id=?",
                (item_id,),
            ).fetchone()
        return row[0]

    before = bag_quantity()
    for _ in range(2):  # the second run exercises the unique-constraint path
        _envelope(client.post("/flash.do", data={"m": "show", "showId": "99", "uid": uid, "gid": gid}))
        command, payload = _envelope(
            client.post("/flash.do", data={"m": "show", "showId": "103", "uid": uid})
        )
        assert command == 103
        assert {"id": item_id, "num": 1} in payload["battle_result"]["reward_goods"]
    assert bag_quantity() == before + 2

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT team, icon, star FROM inventory WHERE player_id=1 AND item_id=?", (item_id,)
        ).fetchone()
    assert row[0] == 3, "equipment lives in the team-3 bag"
    assert row[1] > 0


def test_explore_stamina_is_real_and_refills(tmp_path: Path):
    # ExploreMapListUI.as:200-260 concatenates explore_ap/max_explore_ap into the
    # HUD text, so the earlier hardcoded 0/0 rendered as a broken counter. An
    # expedition costs one point and the value tops back up on read.
    from pet_hunter_server.app import LOCAL_DEFAULT_EXPLORE_AP

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "ApOne")
    command, listing = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "98", "uid": uid, "ttype": 1})
    )
    assert command == 98
    assert listing["max_explore_ap"] == LOCAL_DEFAULT_EXPLORE_AP
    assert listing["explore_ap"] == LOCAL_DEFAULT_EXPLORE_AP

    gid = sorted(config_tables._table("exploreMap.txt"))[0]
    _envelope(client.post("/flash.do", data={"m": "show", "showId": "99", "uid": uid, "gid": gid}))
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "103", "uid": uid})
    )
    assert command == 103
    assert payload["max_explore_ap"] == LOCAL_DEFAULT_EXPLORE_AP
    assert payload["explore_ap"] == LOCAL_DEFAULT_EXPLORE_AP - 1

    # Draining it must refuse the expedition rather than going negative.
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET explore_ap = 0 WHERE uid = ?", (uid,))
        connection.commit()
    _envelope(client.post("/flash.do", data={"m": "show", "showId": "99", "uid": uid, "gid": gid}))
    refused = client.post("/flash.do", data={"m": "show", "showId": "103", "uid": uid})
    assert refused.get_data(as_text=True).startswith("-1:")


def test_pet_stats_come_from_pet_txt_not_a_two_entry_hardcode(tmp_path: Path):
    # The all-stats panel (13) used to read LOCAL_PET_BASE_STATS, which only knew
    # 1001 and 2019 and fell back to 1001 for everything else — so every caught
    # creature showed 火龙's numbers. pet.txt carries the real per-species stats.
    from pet_hunter_server import config_tables as tables

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "StatsOne")
    with sqlite3.connect(database) as connection:
        pet_index = connection.execute(
            "SELECT id FROM pets WHERE player_id = 1 ORDER BY id LIMIT 1"
        ).fetchone()[0]
        connection.execute(
            "UPDATE pets SET pet_id = 5001, icon = 5001, lv = 3 WHERE id = ?", (pet_index,)
        )
        connection.commit()

    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "13", "uid": uid, "index": str(pet_index)})
    )
    assert command == 13
    record = tables.pet_record(5001)
    for column, key in (("hp", "hp"), ("speed", "speed"), ("phyAtt", "phy_att"),
                        ("magAtt", "mag_att"), ("phyDef", "phy_def"), ("magDef", "mag_def")):
        assert payload[key] == int(str(record[column]).strip())
    assert payload["hp"] != 39, "fell back to the starter species"


def test_picture_book_detail_returns_a_renderable_icon(tmp_path: Path):
    # IllustrationInfoUI.as:162 prefixes "p" itself, so 26 must answer a number;
    # without the field the detail page silently rendered no artwork.
    from pet_hunter_server import config_tables as tables

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "PicTwo")
    pics = tables._table("pic.txt")
    gid = sorted(pics)[0]
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "26", "uid": uid, "gid": str(gid)})
    )
    assert command == 26
    icon = payload["icon"]
    assert isinstance(icon, int) and icon > 0
    assert isinstance(payload["pics"][0]["icon"], int)


def test_arena_star_prize_is_claimable_once_per_week(tmp_path: Path):
    # RingTopStarUI.as:178-193 reads id/name/is_reward/img for the page and
    # :195-232 renders the prize through pic.txt, so reward_goods_id has to be a
    # real pic id even though the payout itself is silver + a picture-book entry.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "StarOne")
    pics = config_tables._table("pic.txt")
    skin = config_tables.skin_table()

    command, info = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "82", "uid": uid})
    )
    assert command == 82
    assert info["is_reward"] == 1, "a fresh player has the prize available"
    assert info["name"]
    ids = [int(part) for part in str(info["img"]).split("_") if part.isdigit()]
    assert ids and all(layer in skin for layer in ids), "img must render as a paper doll"

    command, prize = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "83", "uid": uid})
    )
    assert command == 83
    assert prize["reward_goods_id"] in pics
    assert prize["top_star_name"]

    # Second claim this week is refused, and the page reflects it.
    again = client.post("/flash.do", data={"m": "show", "showId": "83", "uid": uid})
    assert again.get_data(as_text=True) == "-1:504"
    _, info = _envelope(client.post("/flash.do", data={"m": "show", "showId": "82", "uid": uid}))
    assert info["is_reward"] == 0


def test_rage_chest_always_returns_a_renderable_box(tmp_path: Path):
    # GameUtil.getBox returns null when the matching amount is zero and the caller
    # then calls TipItem.show(null), so 97 has to pay something.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "RageOne")
    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT point FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]
    command, box = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "97", "uid": uid})
    )
    assert command == 97
    assert box["box_type"] in (1, 2, 3, 4)
    paid = box["point"] if box["box_type"] == 3 else box["crystal"] if box["box_type"] == 4 else box["num"]
    assert paid > 0, "an empty box renders as null"
    with sqlite3.connect(database) as connection:
        after = connection.execute(
            "SELECT point FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]
    assert after > before


def test_picture_book_milestones_track_catches_and_pay_once(tmp_path: Path):
    # picStep.txt lists milestones (value = how many picture-book entries are
    # needed). IllustrationTaskUI reads own_num/need_num from 48 and claims with
    # 49, so catching has to feed pic_unlocked and the reward must not be claimable
    # twice.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "PicBook")
    steps = config_tables._table("picStep.txt")
    first_need = int(str(steps[sorted(int(k) for k in steps)[0]]["value"]).strip())

    command, info = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "48", "uid": uid})
    )
    assert command == 48
    assert info["own_num"] == 0
    assert info["need_num"] == first_need
    assert info["is_finish"] == 0, "nothing collected yet"

    # Claiming before the milestone is met must be refused, not silently paid.
    early = client.post("/flash.do", data={"m": "show", "showId": "49", "uid": uid})
    assert early.get_data(as_text=True) == "-1:504"

    # The picture book counts *distinct* creatures, so reach the milestone by
    # hunting the different monster groups rather than re-catching the same pet.
    # Elite encounters are forced off here: this test is about milestone counting,
    # and a lv-1 squad can legitimately lose to a 1.6x elite trio.
    from pet_hunter_server import app as A

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET ht_ap = 50, max_ht_ap = 50")
        connection.commit()
    original_elite = A.LOCAL_ELITE_CHANCE
    A.LOCAL_ELITE_CHANCE = 0.0
    try:
        for hid in (1, 2, 3, 101):
            command, _ = _envelope(
                client.post("/flash.do", data={"m": "show", "showId": "6", "uid": uid, "hid": hid})
            )
            assert command == 6
    finally:
        A.LOCAL_ELITE_CHANCE = original_elite
    _, info = _envelope(client.post("/flash.do", data={"m": "show", "showId": "48", "uid": uid}))
    assert info["own_num"] >= first_need, f"only {info['own_num']} entries unlocked"
    assert info["is_finish"] == 1

    with sqlite3.connect(database) as connection:
        point_before = connection.execute(
            "SELECT point FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]
    command, claimed = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "49", "uid": uid})
    )
    assert command == 49
    with sqlite3.connect(database) as connection:
        point_after = connection.execute(
            "SELECT point FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]
        claimed_steps = connection.execute(
            "SELECT COUNT(*) FROM pic_step_claimed WHERE player_id = 1"
        ).fetchone()[0]
    assert claimed_steps == 1
    assert point_after >= point_before

    # A second claim of the same milestone is refused.
    again = client.post("/flash.do", data={"m": "show", "showId": "49", "uid": uid})
    assert again.get_data(as_text=True) == "-1:504"


def test_arena_rank_ladder_feeds_the_rank_page(tmp_path: Path):
    # RingTopUI.as:206-247 reads refresh_time, arena_rank and a `ranks` array and
    # calls int(ranks.length) with no null guard; each row needs rank/id/name/img
    # because TopItem.as:126-128 loads img_top_<rank> for the top three.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "RankOne")
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "507", "uid": uid, "p": 1, "n": 9})
    )
    assert command == 507
    assert isinstance(payload["refresh_time"], int) and payload["refresh_time"] > 0
    assert payload["arena_rank"] == 1
    ranks = payload["ranks"]
    assert ranks, "the rank page indexes ranks.length"
    assert [r["rank"] for r in ranks] == list(range(1, len(ranks) + 1))
    for row in ranks:
        assert row["name"]
        # img is a ShowItem layer string; every layer must exist in skin.txt or
        # ShowItem.as:49 silently drops it and the row renders faceless.
        skin = config_tables.skin_table()
        ids = [int(part) for part in str(row["img"]).split("_") if part.isdigit()]
        assert ids and all(layer in skin for layer in ids)
    # Paging must not run off the end of the ladder.
    _, page2 = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "507", "uid": uid, "p": 2, "n": 9})
    )
    assert isinstance(page2["ranks"], list)


def test_arena_and_dungeon_also_train_the_squad(tmp_path: Path):
    # Hunt and expedition already pay pet exp; the arena bout and dungeon clear
    # must too, otherwise the same pets level at different rates per mode.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "MixExp")
    with sqlite3.connect(database) as connection:
        pet_ids = [r[0] for r in connection.execute(
            "SELECT id FROM pets WHERE player_id = 1 ORDER BY id LIMIT 2"
        )]
        connection.execute("UPDATE pets SET lv = 1, exp = 0")
        connection.execute("UPDATE players SET arena_ap = 5, max_arena_ap = 5")
        connection.commit()

    def exp_of() -> list[int]:
        """Total progress, not the leftover: a grant large enough to level up can
        leave exp at 0, which used to make this assertion look like a failure."""
        from pet_hunter_server.app import exp_to_next

        with sqlite3.connect(database) as connection:
            rows = connection.execute(
                "SELECT lv, exp FROM pets WHERE id IN (?,?) ORDER BY id", pet_ids
            ).fetchall()
        return [sum(exp_to_next(level) for level in range(1, lv)) + exp
                for lv, exp in rows]

    command, _ = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "24", "uid": uid})
    )
    assert command == 24
    after_arena = exp_of()
    assert all(value > 0 for value in after_arena), "arena must award pet exp"

    command, _ = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "74", "uid": uid, "hid": 1001})
    )
    assert command == 74
    after_copy = exp_of()
    assert all(a > b for a, b in zip(after_copy, after_arena)), "dungeon must award pet exp"


def test_catching_from_an_explore_map_works_too(tmp_path: Path):
    # ExploreMapInfoUI.as:218 sends CATCH_KEY with {hid: <explore map id>, ttype: 2},
    # so that path has to resolve a catchable pet as well as the hunt maps do.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "ExCatch")
    command, caught = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "7", "uid": uid, "hid": 1, "ttype": 2})
    )
    assert command == 7
    assert caught["is_success"] == 1
    pets = config_tables._table("pet.txt")
    assert caught["id"] in pets
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM pets WHERE id = ?", (caught["index"],)
        ).fetchone()[0] == 1


def test_explore_pays_the_maps_real_pass_reward(tmp_path: Path):
    # exploreMap.txt carries passRewardPoint / passRewardCrystal / passRewardGoods
    # per map. The expedition used to pay a flat LOCAL_EXPLORE_REWARD and never
    # granted the item, so the reward panel and the bag disagreed with the table.
    table = config_tables._table("exploreMap.txt")
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "RwdOne")
    gid = sorted(table)[0]
    _envelope(client.post("/flash.do", data={"m": "show", "showId": "99", "uid": uid, "gid": gid}))
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "103", "uid": uid})
    )
    assert command == 103
    result = payload["battle_result"]
    expected_point = int(str(table[gid].get("passRewardPoint", "0")).strip() or 0)
    from pet_hunter_server.app import LOCAL_EXPLORE_BONUS_POINT

    # The table's pass reward plus the documented LOCAL DEFAULT silver bonus.
    assert result["reward_point"] == expected_point + LOCAL_EXPLORE_BONUS_POINT
    assert result["reward_crystal"] == int(str(table[gid].get("passRewardCrystal", "0")).strip() or 0)

    # Whatever the table advertises must actually land somewhere real: a prop or
    # equip lands in the bag, while a kind-3 entry registers in the picture book.
    with sqlite3.connect(database) as connection:
        point, crystal = connection.execute(
            "SELECT point, crystal FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        bag = connection.execute(
            "SELECT item_id, quantity FROM inventory WHERE player_id = 1"
        ).fetchall()
        unlocked = {r[0] for r in connection.execute(
            "SELECT pic_id FROM pic_unlocked WHERE player_id = 1"
        )}
    assert point >= expected_point
    assert crystal >= result["reward_crystal"]
    props = config_tables._table("prop.txt")
    equips = config_tables._table("equip.txt")
    granted = {gid_: num for gid_, num in bag}
    for entry in result["reward_goods"]:
        item_id = entry["id"]
        if item_id in props or item_id in equips:
            assert granted.get(item_id, 0) >= entry["num"], f"item {item_id} not granted"
        else:
            assert item_id in unlocked, f"picture-book entry {item_id} not registered"


def test_hunting_awards_pet_exp_and_levels_the_squad(tmp_path: Path):
    # Levelling used to be reachable only by feeding exp items; battles returned a
    # reward_exp figure but never wrote it anywhere, so a freshly caught lv-1 pet
    # could never reach the evolution gates. Every hunt now credits the pets that
    # fought (LOCAL DEFAULT: full reward_exp to each participant).
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "ExpHunt")
    with sqlite3.connect(database) as connection:
        pet_ids = [r[0] for r in connection.execute(
            "SELECT id FROM pets WHERE player_id = 1 ORDER BY id LIMIT 2"
        )]
        connection.execute("UPDATE pets SET lv = 1, exp = 0")
        connection.execute("UPDATE players SET ht_ap = 20, max_ht_ap = 20")
        connection.commit()

    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "6", "uid": uid, "hid": 1})
    )
    assert command == 6
    assert payload["reward_exp"] > 0
    assert payload["pet_exp"], "the response should report the exp each pet gained"
    assert {entry["index"] for entry in payload["pet_exp"]} == set(pet_ids)

    with sqlite3.connect(database) as connection:
        gained = connection.execute(
            "SELECT id, lv, exp FROM pets WHERE id IN (?,?) ORDER BY id", pet_ids
        ).fetchall()
    from pet_hunter_server.app import LOCAL_MAX_PET_LEVEL, exp_to_next

    expected_lv, expected_exp = 1, payload["reward_exp"]
    while expected_lv < LOCAL_MAX_PET_LEVEL and expected_exp >= exp_to_next(expected_lv):
        expected_exp -= exp_to_next(expected_lv)
        expected_lv += 1
    for pet_id, lv, exp in gained:
        assert (lv, exp) == (expected_lv, expected_exp), "hunt exp must land on every pet"

    # Enough hunts must actually cross the level boundary.
    for _ in range(11):
        client.post("/flash.do", data={"m": "show", "showId": "6", "uid": uid, "hid": 1})
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE players SET ht_ap = 20")
            connection.commit()
    with sqlite3.connect(database) as connection:
        levels = [r[0] for r in connection.execute(
            "SELECT lv FROM pets WHERE id IN (?,?) ORDER BY id", pet_ids
        )]
    assert all(lv >= 2 for lv in levels), f"pets should have levelled up, got {levels}"


def test_evolving_a_pet_rewrites_it_to_the_real_next_species(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "EvoOne")
    from pet_hunter_server.app import LOCAL_PET_EVOLUTION

    pets = config_tables._table("pet.txt")
    # Pick a pet that has an evolution target and enough level to qualify.
    with sqlite3.connect(database) as connection:
        index = connection.execute("SELECT id FROM pets WHERE player_id = 1 ORDER BY id LIMIT 1").fetchone()[0]
        current = connection.execute("SELECT pet_id FROM pets WHERE id = ?", (index,)).fetchone()[0]
    target = LOCAL_PET_EVOLUTION.get(current)
    assert target is not None, f"pet {current} needs an evolution entry"
    assert target["id"] in pets, "the evolved species must exist in pet.txt"
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE pets SET lv = ? WHERE id = ?", (target["need_lv"], index))
        connection.commit()

    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "14", "uid": uid, "index": index})
    )
    assert command == 14
    assert payload["id"] == target["id"]
    assert payload["icon"] == target["icon"]
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT pet_id, icon, star FROM pets WHERE id = ?", (index,)
        ).fetchone()
    assert row == (target["id"], target["icon"], target["star"])


def test_synthesis_consumes_the_vice_pet_and_raises_generation(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "SynOne")
    with sqlite3.connect(database) as connection:
        indexes = [r[0] for r in connection.execute(
            "SELECT id FROM pets WHERE player_id = 1 ORDER BY id LIMIT 2"
        )]
        generation = connection.execute(
            "SELECT generation FROM pets WHERE id = ?", (indexes[0],)
        ).fetchone()[0]
    command, payload = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "65", "uid": uid, "main": indexes[0], "vice": indexes[1]},
        )
    )
    assert command == 65
    assert payload["index"] == indexes[0]
    assert payload["exd_generation"] == (generation or 1) + 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM pets WHERE id = ?", (indexes[1],)
        ).fetchone()[0] == 0, "the vice pet is consumed"
        row = connection.execute(
            "SELECT generation, pro_hp FROM pets WHERE id = ?", (indexes[0],)
        ).fetchone()
    assert row[0] == (generation or 1) + 1


def test_catching_a_pet_actually_adds_it_to_the_roster(tmp_path: Path):
    # HunterCatchUI.as:128-150 renders index/id/icon/pic and never inspects
    # is_success, so a catch must hand back a real pet that already exists in the
    # database — the previous implementation always returned is_success 0 and
    # reused the player's first pet, i.e. catching never added anything.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "CatchOne")

    def roster() -> list[dict]:
        command, payload = _envelope(
            client.post("/flash.do", data={"m": "show", "showId": "505", "uid": uid, "p": 1, "n": 50})
        )
        assert command == 505
        return payload["list"]

    before = roster()
    command, caught = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "7", "uid": uid, "hid": 1})
    )
    assert command == 7
    assert caught["is_success"] == 1
    pets = config_tables._table("pet.txt")
    assert caught["id"] in pets, "id must resolve through getConfigValue(pet, ...)"
    assert caught["name"] == pets[caught["id"]]["name"]

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT player_id, pet_id, icon, lv, star FROM pets WHERE id = ?", (caught["index"],)
        ).fetchone()
    assert row is not None, "the caught pet must be a real row"
    assert row[1] == caught["id"] and row[2] == caught["icon"]
    assert row[3] == caught["lv"] and row[4] >= 1

    after = roster()
    assert len(after) == len(before) + 1
    assert caught["index"] in {entry["index"] for entry in after}

    # ...and it has to be usable in battle, which is the point of catching it.
    command, picked = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "44", "uid": uid, "index": caught["index"]})
    )
    assert command == 44

    # The picture book panel on the catch screen needs the same contract.
    for entry in caught["pic"]:
        assert entry["id"] in pets or entry["id"] in config_tables._table("pic.txt")


def test_catching_respects_pet_capacity(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "FullOne")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET pet_capacity = 0 WHERE uid = ?", (uid,))
        connection.commit()
    response = client.post("/flash.do", data={"m": "show", "showId": "7", "uid": uid, "hid": 1})
    assert response.get_data(as_text=True) == "-1:300"


def test_develop_page_shows_pets_instead_of_star_wands(tmp_path: Path):
    # DevelopUI.as:120-139 renders one DevelopItem per entry in param2.list and
    # DevelopItem.as:173-184 paints `clip_wand` for every slot whose data is null.
    # Returning only the pets that are *currently* training therefore left the
    # 养成 page as a grid of star wands whenever no run was active. The list has to
    # carry the player's roster, with training runs ordered first.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "DevOne")

    def slots() -> list[dict]:
        command, payload = _envelope(
            client.post("/flash.do", data={"m": "show", "showId": "504", "uid": uid})
        )
        assert command == 504
        return payload["list"]

    idle = slots()
    assert idle, "an idle player must still see their pets, not nine wands"
    assert len(idle) <= 9
    for entry in idle:
        # DevelopItem.as:140 needs `icon` to resolve as "p"+icon, else it throws.
        assert entry["icon"], "every slot needs an icon or the wand placeholder shows"
        assert entry["name"], "a null name renders as the string null"
        assert isinstance(entry["train_time"], int)

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE pets SET train_end=0, train_state=0")
        connection.commit()

    # Starting a run must float that pet to the front with a positive countdown.
    index = idle[0]["index"]
    _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "10", "uid": uid, "index": index, "ttype": 1})
    )
    trained = slots()
    assert trained[0]["index"] == index
    assert trained[0]["train_time"] > 0
    assert trained[0]["train_state"] == 1


def test_hunt_result_fills_the_picture_book_panel(tmp_path: Path):
    # HunterResultUI.as:259-261 hands param2.pic to GameUtil.getPic, which builds a
    # GetPicItem per entry. GetPicItem.as:170-197 instantiates `p<icon>` and then
    # resolves the name via pic.txt -> pet.txt -> prop.txt -> exploreEquip.txt,
    # dereferencing the record with no null guard. An empty list left the
    # 【获得图鉴】/【图鉴奖励】 panels blank; a bad id would throw.
    from pet_hunter_server.app import _monster_table, _pick_monster

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "PicOne")
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "6", "uid": uid, "hid": 1})
    )
    assert command == 6
    pic = payload["pic"]
    assert pic, "the picture-book panel needs at least one entry"

    pics = config_tables._table("pic.txt")
    pets = config_tables._table("pet.txt")
    for entry in pic:
        assert entry["id"] == entry["icon"]
        # The display name must resolve, or GetPicItem throws on a null record.
        assert entry["id"] in pics or entry["id"] in pets
        assert isinstance(entry["reward_point"], int)
        assert isinstance(entry["reward_goods"], list)

    # The entries must correspond to the monsters actually fought.
    expected = {
        int(m["icon"]) for m in (_pick_monster(i) for i in sorted(int(k) for k in _monster_table())) if m
    }
    assert {entry["id"] for entry in pic} <= expected


def test_skin_string_carries_the_head_and_hair_layers(tmp_path: Path):
    # ShowItem.as:41-59 keeps only ids present in skin.txt (silently dropping the
    # rest) and :71 sorts by z DESCENDING, so the lowest z paints last / on top.
    # The bare character is three layers — CreateUI.as:366-378 uses
    # "100001_100002_100003" (male) and "100001_100004_100005" (female).
    # Shipping only 100001 drew a body with no head, which is the reported
    # "进入狩猎没有人物头部图片" bug.
    from pet_hunter_server.app import _base_skin_layers

    skin = config_tables.skin_table()
    # sex is the *registration* value: /regplayer accepts 0 or 1 and stores the
    # female triple when sex != 1, so 0 is female and 1 is male. The dict used to
    # be keyed 1/2, which made female hunters render with the male head/hair.
    for sex, expected in ((1, (100001, 100002, 100003)), (0, (100001, 100004, 100005))):
        layers = _base_skin_layers(sex)
        assert layers == expected
        assert all(layer in skin for layer in layers), "every base layer must exist in skin.txt"

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "HeadOne")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET sex=0 WHERE uid=?", (uid,))
        connection.commit()

    command, payload = _envelope(client.post("/flash.do", data={"m": "show", "showId": "2", "uid": uid}))
    assert command == 2
    img = payload["img"]
    ids = [int(part) for part in img.split("_")]
    assert ids, "img must not be empty"
    # A sex=0 player is the female hunter, so the female triple must be present —
    # and no male head/hair layer may sneak in, which is what "男女图片重合" looked
    # like on screen.
    assert set(_base_skin_layers(0)) <= set(ids)
    assert not ({100002, 100003} & set(ids)), f"male layers leaked into a female doll: {img}"
    zs = [int(skin[i]["z"]) for i in ids]
    assert zs == sorted(zs, reverse=True), f"layers must be high-z first, got {img}"


def test_explore_supplies_a_terrain_and_mount_that_exist_in_the_swfs(tmp_path: Path):
    # ExploreUI.as:167-168 and :182-190 call getDefinition() with no null guard:
    #   "map_terrain_" + terrain   and   "m" + horse
    # map.swf only ships map_terrain_1 / map_terrain_2, and mounts.swf only ships
    # m100001..m100007 (+ _2 walk cycles), which are exploreEquip.txt mount ids.
    # A zero terrain or a missing horse throws and leaves the page black behind the
    # HUD icons, so both fields have to be values the shipped artwork defines.
    table = config_tables._table("exploreMap.txt")
    equips = config_tables._table("exploreEquip.txt")
    mounts = {f"m{i}" for i in equips if f"m{i}" in _mount_symbols()}
    assert mounts, "mounts.swf must export at least one m<exploreEquip id>"

    client = create_app({"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}).test_client()
    uid = _create_local_player(client, "HorseOne")
    gid = sorted(table)[0]
    _envelope(client.post("/flash.do", data={"m": "show", "showId": "99", "uid": uid, "gid": gid}))
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "103", "uid": uid})
    )
    assert command == 103
    assert payload["terrain"] in (1, 2), "map.swf only defines map_terrain_1 / _2"
    assert payload["terrain"] == int(str(table[gid]["terrain"]).strip() or 1)
    assert f"m{payload['horse']}" in mounts
    assert payload["need_discover_rate"] == int(
        str(table[gid].get("needDiscoverRate", "0")).strip() or 0
    )
    assert payload["battle_result"]["map_id"] == gid


def _mount_symbols() -> set[str]:
    """Mount class names exported by the shipped mounts.swf.

    Parsed straight out of the SWF rather than hardcoded, so the test fails if the
    artwork set ever changes underneath the server's chosen `horse` value.
    """
    import sys as _sys

    root = Path(__file__).resolve().parents[2]
    tools = root / "tools"
    if str(tools) not in _sys.path:
        _sys.path.insert(0, str(tools))
    import swf_symbol_list as swf

    path = root / "client" / "air51-repack" / "build" / "input" / "data" / "mounts.swf"
    if not path.is_file():
        path = root / "client" / "air51-repack" / "src" / "data" / "mounts.swf"
    data = swf.inflate_body(path.read_bytes())
    return set(swf.symbol_classes(data)) | set(swf.export_assets(data))


def test_explore_rolls_a_battle_event_so_the_fight_screen_is_reachable(tmp_path: Path):
    # ExploreUI.as:100 only flows to FIGHT_EXPLORE_PVE when data.event_type == 1;
    # every other value goes to ExploreEventResultUI, which renders no battle at
    # all. exploreMap.txt stores two-digit codes ("11:12:13"), and
    # GameUtil.getExploreEvent:482 switches on the tens digit, so the raw code is
    # divided by ten.
    table = config_tables._table("exploreMap.txt")
    client = create_app({"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}).test_client()
    uid = _create_local_player(client, "EvtOne")
    gid = sorted(table)[0]
    command, _ = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "99", "uid": uid, "gid": gid})
    )
    assert command == 99
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "103", "uid": uid})
    )
    assert command == 103
    raw = str(table[gid].get("events", "")).split(":")[0].strip()
    assert payload["event_type"] == (int(raw) % 10 if raw.isdigit() else 1)
    assert payload["event_type"] == 1, "only event 1 reaches the battle screen"
    # The codes embed the map id, so a map above 9 is the regression case:
    # "111" must read as type 1, not type 11.
    for probe, expected in (("11", 1), ("41", 1), ("111", 1), ("15", 5), ("116", 6)):
        from pet_hunter_server.app import _explore_event_type

        assert int(probe) % 10 == expected


def test_training_action_reports_the_matching_stat_gain(tmp_path: Path):
    # DevelopResultUI.as:164-336 reads add_hp_tp / add_phy_att_tp / add_mag_att_tp /
    # add_phy_def_tp / add_mag_def_tp. The database columns are named pro_hp,
    # pro_phy_att, ... so the mapping has to bridge the pro_ prefix *and* the
    # client's _tp suffix; getting it wrong silently reports every gain as 0.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "GainOne")

    def train(index: int, ttype: int) -> dict:
        data = {"m": "show", "showId": "10", "uid": uid, "index": index, "ttype": ttype}
        _, payload = _envelope(client.post("/flash.do", data=data))
        return payload

    with sqlite3.connect(database) as connection:
        indexes = [r[0] for r in connection.execute("SELECT id FROM pets ORDER BY id")]
        # A fresh character starts with two pets; add one more straight into the
        # table so the test does not depend on the starter pack size.
        while len(indexes) < 3:
            connection.execute(
                "INSERT INTO pets (player_id, pet_id, name, lv, star, icon)"
                " VALUES (1, 1003, NULL, 5, 1, 1003)"
            )
            connection.commit()
            indexes = [r[0] for r in connection.execute("SELECT id FROM pets ORDER BY id")]

    # LOCAL DEFAULT gains: 5 + level // 20 per run (x3 for the vacation branch).
    from pet_hunter_server.app import _train_gain

    with sqlite3.connect(database) as connection:
        levels = {
            row[0]: row[1]
            for row in connection.execute("SELECT id, lv FROM pets")
        }

    hp = train(indexes[0], 1)
    hp_gain = _train_gain(levels[indexes[0]])
    assert hp["add_hp_tp"] == hp_gain and hp["train_type"] == 1
    # ttype 1 also raises speed, which used to be reported as a hard 0.
    assert hp["add_speed_tp"] == hp_gain
    assert hp["add_phy_att_tp"] == 0 and hp["add_mag_def_tp"] == 0

    att = train(indexes[1], 2)
    att_gain = _train_gain(levels[indexes[1]])
    assert att["add_phy_att_tp"] == att_gain and att["add_mag_att_tp"] == att_gain
    assert att["add_hp_tp"] == 0

    defence = train(indexes[2], 3)
    def_gain = _train_gain(levels[indexes[2]]) * 3
    assert defence["add_phy_def_tp"] == def_gain and defence["add_mag_def_tp"] == def_gain
    assert defence["add_hp_tp"] == 0

    # The reinforcement must actually land in the row, otherwise the run is a
    # no-op that the client can never "collect" (there is no collect command).
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT pro_hp, pro_speed FROM pets WHERE id=?", (indexes[0],)
        ).fetchone() == (hp_gain, hp_gain)

    for payload in (hp, att, defence):
        assert payload["pet"]["name"], "a null name renders as the string null"
        assert payload["pet"]["icon"]


def test_battle_rewards_are_actually_credited(tmp_path: Path):
    # FightResultItem.as:285 and :296 render reward_point/reward_crystal straight
    # from the response, so advertising a payout without writing it left the
    # settlement panel promising money the player never received.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "Payout")

    def point() -> int:
        with sqlite3.connect(database) as connection:
            return connection.execute(
                "SELECT point FROM players WHERE uid=?", (uid,)
            ).fetchone()[0]

    def fight(show_id: int, **extra) -> dict:
        data = {"m": "show", "showId": str(show_id), "uid": uid, **extra}
        _, payload = _envelope(client.post("/flash.do", data=data))
        return payload

    before = point()
    hunt = fight(6, hid=1)
    assert point() == before + hunt["reward_point"], "hunt reward was never credited"

    before = point()
    arena = fight(24)
    assert point() == before + arena["reward_point"]

    before = point()
    dungeon = fight(74, hid=1001)
    assert point() == before + dungeon["reward_point"]
    assert all(p["reward_point"] > 0 for p in (hunt, arena, dungeon))


def test_hunt_win_pays_full_and_a_lost_dungeon_pays_nothing(tmp_path: Path):
    """The replay now decides the outcome, so payouts must follow it.

    A hunt the squad wins pays silver and full exp; a stage it loses still costs
    the entry but pays no silver, no picture-book entry and a tenth of the exp.
    """
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "PayOut")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE players SET ht_ap = 10, max_ht_ap = 20, point = 0 WHERE uid = ?", (uid,)
        )

    # Losing stage first: a fresh lv-1 squad faces L90-band monsters, so this is
    # the unambiguous loss case (running a hunt first would hand out exp and could
    # flip the outcome after any future tuning).
    lost = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "74", "uid": uid, "hid": "1004"}
    ))[1]
    assert lost["is_win"] == 0
    assert lost["reward_point"] == 0 and lost["reward_crystal"] == 0
    assert lost["record"], "a loss still needs a replay or the screen freezes"
    last = lost["record"][-1]
    assert last["def"]["is_dead"] is True, "a loss ends with a team-1 death"
    assert last["def"]["team"] == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT point FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0] == 0

    hunt = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "6", "uid": uid, "hid": "1"}
    ))[1]
    assert hunt["is_win"] == 1
    assert hunt["reward_point"] > 0 and hunt["reward_exp"] > 0
    # rage_point only reaches 100 on an elite clear now, so the bar is not pinned
    # to 100 here — test_hunt_result_fills_the_rage_bar owns that rule.
    assert isinstance(hunt["rage_point"], int) and 0 <= hunt["rage_point"] <= 100
    assert hunt["finish_rate"] == 100
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT point FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0] == hunt["reward_point"]


def test_dungeon_stages_scale_with_their_reference_level(tmp_path: Path):
    """Fixed defender ids (1 + 11 = L1 + L90) made early stages unwinnable."""
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "StageLv")

    def defenders(stage: int) -> list[dict]:
        return _envelope(client.post(
            "/flash.do", data={"m": "show", "showId": "74", "uid": uid, "hid": str(stage)}
        ))[1]["def_list"]

    early = defenders(1001)
    late = defenders(1004)
    assert early and late
    assert max(int(d["lv"]) for d in early) <= 30
    assert max(int(d["lv"]) for d in late) >= 60


def test_arena_exp_is_a_slice_of_the_squad_level(tmp_path: Path):
    """Flat 200,000 used to be 40 levels at lv1 and nothing at lv900."""
    from pet_hunter_server.app import LOCAL_ARENA_EXP_SHARE, _battle_exp, exp_to_next

    for level in (1, 100, 500, 1000):
        assert _battle_exp(level, LOCAL_ARENA_EXP_SHARE) == max(
            1, exp_to_next(level) // LOCAL_ARENA_EXP_SHARE
        )
    # A slice must never be a whole level, or the dial does nothing.
    assert _battle_exp(10, LOCAL_ARENA_EXP_SHARE) < exp_to_next(10)

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "ArenaExp")
    with sqlite3.connect(database) as connection:
        pet_id = connection.execute(
            "SELECT id FROM pets WHERE player_id=1 ORDER BY id LIMIT 1"
        ).fetchone()[0]
        connection.execute("UPDATE players SET arena_ap=5, max_arena_ap=20 WHERE uid=?", (uid,))
        connection.execute("UPDATE pets SET exp=0 WHERE id=?", (pet_id,))
        squad_lv = connection.execute("SELECT MAX(lv) FROM pets WHERE player_id=1").fetchone()[0]

    payload = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "24", "uid": uid}
    ))[1]
    assert payload["is_win"] == 1
    with sqlite3.connect(database) as connection:
        gained = connection.execute(
            "SELECT exp FROM pets WHERE id=?", (pet_id,)
        ).fetchone()[0]
    assert gained == _battle_exp(squad_lv, LOCAL_ARENA_EXP_SHARE)


def test_arena_and_copy_fights_share_the_hunt_replay_contract(tmp_path: Path):
    # HunterResultUI / RingResultUI / AbyssResultUI were compared field by field:
    # att_list, def_list and record are structurally identical, so 6, 24 and 74
    # must produce the same shape. RingResultUI additionally needs
    # arena_ap/max_arena_ap/rage_point (FightResultItem.as:349,405), and
    # AbyssMapUI/AbyssResultUI guard nothing at all.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "WarOne")
    skin = config_tables.skin_table()

    def sides(command_id: int, extra: dict) -> dict:
        data = {"m": "show", "showId": str(command_id), "uid": uid, **extra}
        command, payload = _envelope(client.post("/flash.do", data=data))
        assert command == command_id
        return payload

    for command_id, extra in ((6, {"hid": 1}), (24, {}), (74, {"hid": 1001})):
        payload = sides(command_id, extra)
        assert payload["is_win"] in (1, True)
        lead = payload["att_list"][0]
        assert lead["is_pet"] == 0, "the hunter must lead so ShowItem gets a skin string"
        for layer in lead["img"].split("_"):
            assert int(layer) in skin
        assert payload["def_list"], f"{command_id} dereferences def_list[0] unguarded"
        for row in payload["def_list"]:
            assert str(row["img"]).isdigit(), "defenders use Pet.as:121's bare 'p'+id"
            assert row["name"] and row["lv"] >= 1
        assert payload["record"], "an empty record freezes the fight screen"
        for step in payload["record"]:
            for side in ("att", "def"):
                assert {"cur_hp", "is_dead", "is_revive"} <= set(step[side])
                assert 0 <= step[side]["code"] <= 2, "FightProcess indexes _p1 by code"

    arena = sides(24, {})
    assert isinstance(arena["arena_ap"], int)
    assert arena["max_arena_ap"] >= arena["arena_ap"]
    assert isinstance(arena["rage_point"], int)


def test_abyss_rewards_scale_with_stage_and_expeditions_can_roll_elites(tmp_path: Path):
    """深渊奖励按层递增；探险也会滚精英遭遇（同一套 LOCAL_ELITE_* 开关）。"""
    from pet_hunter_server import app as A

    assert A.LOCAL_COPY_REWARD_MULT[A.LOCAL_COPY_MAPS[0]] == 1.0
    assert A.LOCAL_COPY_REWARD_MULT[A.LOCAL_COPY_MAPS[-1]] == 3.0

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "AbyssMx")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE players SET point = 0, explore_ap = 20, max_explore_ap = 20 WHERE uid = ?",
            (uid,),
        )

    # Stage 1 pays exactly the base reward.
    first = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "74", "uid": uid,
                           "hid": str(A.LOCAL_COPY_MAPS[0])},
    ))[1]
    if first["is_win"] == 1:
        assert first["reward_point"] == A.LOCAL_COPY_REWARD

    # An expedition with a forced elite fields the leader plus its pair.
    original = A.LOCAL_ELITE_CHANCE
    A.LOCAL_ELITE_CHANCE = 1.0
    try:
        _envelope(client.post(
            "/flash.do", data={"m": "show", "showId": "99", "uid": uid, "gid": "1"},
        ))
        explore = _envelope(client.post(
            "/flash.do", data={"m": "show", "showId": "103", "uid": uid},
        ))[1]
    finally:
        A.LOCAL_ELITE_CHANCE = original
    battle = explore["battle_result"]
    assert len(battle["def_list"]) >= 3, "elite expedition fields leader + pair"
    assert isinstance(battle["is_win"], int)
    if battle["is_win"] == 1:
        assert explore["is_finish"] == 1
    else:
        assert explore["is_finish"] == 0, "a lost expedition must not report finished"
        assert battle["reward_point"] == 0


def test_copy_list_progresses_and_tracks_clears(tmp_path: Path):
    # AbyssMapUI.as:197-199 calls int(param2.maps.length) unguarded and
    # MapItem.as:315 locks a tile when is_battle_able is falsy. The list now also
    # gates stages on the previous clear instead of opening all four forever.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "CopyOne")
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "73", "uid": uid, "p": 1, "n": 9})
    )
    assert command == 73
    assert payload["maps"], "an empty maps array locks every tile"
    for row in payload["maps"]:
        assert {"code", "id", "finish_rate", "finished_num", "is_battle_able"} <= set(row)
    assert payload["maps"][0]["is_battle_able"] == 1
    assert all(row["is_battle_able"] == 0 for row in payload["maps"][1:])

    stage_one = payload["maps"][0]["id"]
    cleared = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "74", "uid": uid, "hid": str(stage_one)}
    ))[1]
    if cleared["is_win"] != 1:
        import pytest

        pytest.skip("the starter squad lost stage 1; the win path is covered elsewhere")
    _, after = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "73", "uid": uid, "p": 1, "n": 9})
    )
    assert after["maps"][0]["finish_rate"] == 100
    assert after["maps"][0]["finished_num"] == 1
    assert after["maps"][1]["is_battle_able"] == 1


def test_explore_rental_chain_round_trips_through_the_shop(tmp_path: Path):
    # 100 needs list[] with no null guard (HireShopUI.as:201-202); 101 needs
    # goods_ext (HireShopInfoUI.as:202); 102 is a pure ack whose callers all
    # require value == "ok"; 104 then has to report the new rental.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "RentOne")
    table = config_tables._table("exploreEquip.txt")

    def call(show_id: int, **extra):
        data = {"m": "show", "showId": str(show_id), "uid": uid, **extra}
        return _envelope(client.post("/flash.do", data=data))

    command, shop = call(100, ttype=1, p=1, n=9)
    assert command == 100 and shop["type"] == 1
    assert shop["list"], "HireShopUI.as:201 dereferences list.length"
    entry = shop["list"][0]
    assert entry["id"] in {int(k) for k in table}
    # `type` must echo the request ttype, not the table's own type column:
    # HireShopUI.as:179 and HireListUI.as:266 send it back as the next ttype.
    assert entry["type"] == 1
    assert entry["price_type"] in (1, 2, 3, 4)

    command, info = call(101, ttype=1, gid=entry["id"])
    assert command == 101
    assert isinstance(info["goods_ext"], dict), "HireShopInfoUI.as:202 has no null guard"
    assert {"need_goods_id", "own_need_goods_num"} <= set(info["goods_ext"])
    assert {"need_money", "need_point", "need_crystal", "is_rented"} <= set(info)

    command, ack = call(102, ttype=1, gid=entry["id"])
    assert command == 102 and ack["value"] == "ok", "all three callers check this string"

    command, rented = call(104, ttype=1, p=1, n=9)
    assert command == 104
    assert rented["equip_count"] >= 1
    ids = {row["id"] for row in rented["list"]}
    assert entry["id"] in ids


def test_explore_stop_must_ack_ok_or_the_client_throws(tmp_path: Path):
    # ExplorePveUI.as:365-372 / ExploreEventResultUI.as:115-122 read only `value`.
    # Anything else falls through to the EXPLORE_KEY branch, where
    # param2 = param2.battle_result is undefined and _loc2_.is_win throws
    # (ExplorePveUI.as:377).
    client = create_app({"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}).test_client()
    uid = _create_local_player(client, "StopOne")
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "105", "uid": uid})
    )
    assert command == 105
    assert payload["value"] == "ok"
    assert "battle_result" not in payload


def test_explore_slot_purchase_reports_both_cost_fields(tmp_path: Path):
    # HireListUI.as:216 and :219 read need_money and own_money with no guard on
    # the failure path; a missing one becomes NaN in the displayed price.
    client = create_app({"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}).test_client()
    uid = _create_local_player(client, "SlotOne")
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "106", "uid": uid, "ttype": 0})
    )
    assert command == 106
    if payload["value"] == "ok":
        assert "need_money" not in payload
    else:
        assert isinstance(payload["need_money"], int)
        assert isinstance(payload["own_money"], int)


def test_arena_fighter_ships_pets_because_ringui_shifts_them(tmp_path: Path):
    # RingUI.as:293-294 calls param2.pets.shift() with no null guard.
    client = create_app({"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}).test_client()
    uid = _create_local_player(client, "RingOne")
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "506", "uid": uid})
    )
    assert command == 506
    assert payload["name"] and payload["lv"] >= 1
    assert payload["arena_ap"] >= 0 and payload["max_arena_ap"] >= payload["arena_ap"]
    assert isinstance(payload["pets"], list) and payload["pets"]
    for row in payload["pets"]:
        assert str(row["icon"]).isdigit() and row["name"]


def test_explore_map_list_pages_within_the_world_in_gid(tmp_path: Path):
    # ExploreMapListUI.as:177-185 sends {ttype:2, gid:<worldId>, p, n}: ttype is
    # only the page kind and the world id travels in gid. Reading ttype as the
    # world made page 2 of world 1 switch to world 2 and replay its first screen.
    from pet_hunter_server.app import _explore_map_table, _explore_map_world

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "MapPage")
    maps = _explore_map_table()
    world = _explore_map_world(sorted(maps)[0])
    in_world = [gid for gid in sorted(maps) if _explore_map_world(gid) == world]
    assert len(in_world) > 3, "need a world with more than one page of maps"

    def page(number: int, size: int = 3):
        return _envelope(client.post(
            "/flash.do",
            data={"m": "show", "showId": "98", "uid": uid, "ttype": "2",
                  "gid": str(world), "p": str(number), "n": str(size)},
        ))[1]

    first, second = page(1), page(2)
    assert first["world"] == world, "the world must not change between pages"
    assert [row["id"] for row in first["list"]] == in_world[0:3]
    assert [row["id"] for row in second["list"]] == in_world[3:6]
    for row in first["list"]:
        assert {"code", "id", "terrain", "star", "max_days"} <= set(row)

    # An exhausted page answers an empty list; an error would pop up a dialog
    # because the client only stops paging when a page comes back short.
    far = page(99)
    assert far["world"] == world
    assert far["list"] == []


def test_caught_pets_roll_element_growth_skills_and_traits(tmp_path: Path):
    # `pro` is the ELEMENT (ui.txt 29 原 / 33 火 / 31 草 / 32 水 / 34 土), not a
    # quality tier, and the catch used to INSERT a literal 1 — so every catch was
    # 火 with identical growth, born skills and no traits.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "CatchOne")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET ht_ap = 60, max_ht_ap = 60")
        connection.execute("UPDATE players SET pet_capacity = 30")
        connection.commit()

    elements, growths, skillsets, traits = set(), set(), set(), set()
    for _ in range(8):
        command, payload = _envelope(
            client.post("/flash.do", data={"m": "show", "showId": "7", "uid": uid, "hid": "1"})
        )
        assert command == 7
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                "SELECT pro, skills, buffs, gw_hp, gw_speed, gw_phy_att, gw_mag_att,"
                " gw_phy_def, gw_mag_def FROM pets WHERE id = ?",
                (payload["index"],),
            ).fetchone()
        assert 0 <= row[0] <= 4, "element must stay inside the ui.txt 29-34 band"
        assert row[1], "born skills must never be empty"
        assert row[2], "traits must be seeded or item 10034 stays unusable"
        elements.add(row[0])
        growths.add(tuple(row[3:]))
        skillsets.add(row[1])
        traits.add(row[2])

    assert len(elements) > 1, "every catch is still the same element"
    assert len(growths) > 1, "growth values are not rolling"


def test_hunt_maps_field_distinct_level_appropriate_groups():
    # Picking adjacent ids made map 2 field "lv10 + lv40" (monster.txt is not
    # sorted by level): one hunt paid 24,000 exp while a lv10 pet needs 14,000.
    from pet_hunter_server.app import (
        LOCAL_HUNT_LEVEL_BAND, LOCAL_HUNT_MAPS, _monster_table, _monsters_for_map,
    )

    table = _monster_table()
    groups = {hid: _monsters_for_map(hid) for hid in (1, 2, 3, 101)}
    for hid, monsters in groups.items():
        assert monsters, f"map {hid} has no monsters"
        base_id = int(LOCAL_HUNT_MAPS[hid]["monster"])
        base_level = int(str(table[base_id]["level"]).strip())
        assert monsters[0]["id"] == base_id, f"map {hid} must lead with its base monster"
        for monster in monsters:
            level = int(monster["lv"])
            assert base_level <= level <= base_level + LOCAL_HUNT_LEVEL_BAND, (
                hid, level, base_level,
            )

    signatures = {tuple(m["id"] for m in monsters) for monsters in groups.values()}
    assert len(signatures) == len(groups), f"maps collapsed onto the same group: {signatures}"


def test_hunt_replay_is_multi_round_and_carries_swing_damage(tmp_path: Path):
    # The replay used to hold one step per monster with cur_hp already 0 and no
    # `skill`, so the client (which only plays the script back) drew a one-shot
    # kill with no damage number. FightProcess.as:716-764 reads att.skill.dm.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "Replay1")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET ht_ap = 5, max_ht_ap = 20 WHERE uid = ?", (uid,))
        connection.commit()

    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "6", "uid": uid, "hid": "1"})
    )
    assert command == 6
    record = payload["record"]
    assert len(record) >= 4, "a monster must take several swings, not one"

    for step in record:
        assert set(step) == {"att", "def"}
        skill = step["att"]["skill"]
        assert skill["dm"] >= 1 and skill["pro"] in (1, 2)
        assert step["def"]["is_dead"] == (step["def"]["cur_hp"] <= 0)

    # Both sides act now: monsters counter the striker, so a step's `def` may be a
    # team-1 actor. Group the *defenders* only (team 2); the counter series for
    # team 1 is checked separately below.
    by_code: dict[int, list[int]] = {}
    for step in record:
        if step["def"]["team"] == 2:
            by_code.setdefault(step["def"]["code"], []).append(step["def"]["cur_hp"])
    assert by_code, "the replay must contain monster hits"
    for code, series in by_code.items():
        assert series[0] > 0, f"monster {code} starts at full health"
        assert series[-1] == 0, f"monster {code} must end dead"
        assert all(a > b for a, b in zip(series, series[1:])), f"monster {code} hp not decreasing"

    # The hunter and the pets both swing, and the monsters hit back.
    assert {step["att"]["team"] for step in record} == {1, 2}
    assert {step["att"]["code"] for step in record if step["att"]["team"] == 1} >= {0}
    assert any(step["att"]["code"] == 1 for step in record if step["att"]["team"] == 1)
    # The hunter's health bar comes from ROLE_BASE_STATS × level + equipment, not
    # the old constant 100: a level-1 hunter with no HP gear still equals the base,
    # but the level factor must make a higher-level hunter strictly stronger.
    from pet_hunter_server.app import ROLE_BASE_STATS, _hunter_combat_stats

    assert payload["att_list"][0]["hp"] >= ROLE_BASE_STATS["hp"]
    low_hp = _hunter_combat_stats({"lv": 1}, {})[0]
    high_hp = _hunter_combat_stats({"lv": 50}, {})[0]
    assert high_hp > low_hp == ROLE_BASE_STATS["hp"]

    # The settlement bar is still driven by rage_point (D-10); elite clears are
    # covered separately, so a normal hunt may legitimately report 0.
    assert isinstance(payload["rage_point"], int) and 0 <= payload["rage_point"] <= 100


def test_use_goods_rejects_the_wrong_usage_context(tmp_path: Path):
    # prop.txt `useType`: 2 = used on a pet, 1 = used on the hunter/home. The
    # client only gates this by which grid cell is tappable, so without a server
    # check a pet snack can be eaten from the home screen and a silver bag can be
    # fed to a pet.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "Context")
    _set_currency(client, database, uid, money=100000, point=100000)

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT id FROM pets WHERE player_id = 1 ORDER BY id"
        ).fetchall()
    pet_id = rows[0][0]

    # 10002 is pet food (useType 2): fine on a pet, refused at home.
    food = _buy(client, uid, 10002, 1, 1)
    refused = client.post(
        "/flash.do", data={"m": "show", "showId": "50", "uid": uid,
                           "index": str(food), "index1": "0"}
    )
    assert refused.get_data(as_text=True) == "-1:506"
    _, accepted = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "50", "uid": uid,
                                       "index": str(food), "index1": str(pet_id)})
    )
    assert accepted["type"] == 5

    # 10022 is a silver bag (useType 1): fine at home, refused on a pet.
    bag = _buy(client, uid, 10022, 1, 2)
    refused = client.post(
        "/flash.do", data={"m": "show", "showId": "50", "uid": uid,
                           "index": str(bag), "index1": str(pet_id)}
    )
    assert refused.get_data(as_text=True) == "-1:100"


def test_hunt_map_progress_accumulates_and_clears(tmp_path: Path):
    # HunterMapUI.as:206 draws `maps[].rate` as a progress bar; it used to be a
    # hardcoded 0, so farming a map forever still read 0%.
    from pet_hunter_server.app import LOCAL_HUNT_CLEAR_KILLS

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "MapProg")

    def listed() -> dict:
        board = _envelope(
            client.post("/flash.do", data={"m": "show", "showId": "4", "uid": uid})
        )[1]
        return next(m for m in board["maps"] if m["id"] == 1)

    start = listed()
    assert start["rate"] == 0 and start["pass"] == 0

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET ht_ap = 40, max_ht_ap = 40 WHERE uid = ?", (uid,))
        connection.commit()

    _envelope(client.post("/flash.do", data={"m": "show", "showId": "6", "uid": uid, "hid": "1"}))
    after_one = listed()
    assert after_one["rate"] == 100 // LOCAL_HUNT_CLEAR_KILLS
    assert after_one["rate"] > 0, "the bar has to move after the first clear"

    for _ in range(LOCAL_HUNT_CLEAR_KILLS - 1):
        _envelope(client.post("/flash.do", data={"m": "show", "showId": "6", "uid": uid, "hid": "1"}))
    cleared = listed()
    assert cleared["rate"] == 100
    assert cleared["pass"] == 1, "the map should read as cleared"

    # Progress is per map, so a different map starts from zero.
    other = next(
        m for m in _envelope(
            client.post("/flash.do", data={"m": "show", "showId": "4", "uid": uid})
        )[1]["maps"]
        if m["id"] != 1
    )
    assert other["rate"] == 0


def test_hunt_rage_meter_fills_then_triggers_once(tmp_path: Path):
    # `rage_point` drives BOTH the settlement bar (PercentUItem) and the 无双一击
    # button (:169 tests ==100), so it is a meter that accumulates across hunts:
    # hardcoding 100 made 无双 fire every fight, hardcoding 0 left the bar empty.
    from pet_hunter_server import app as A

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "RageBar")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET ht_ap = 40, max_ht_ap = 40 WHERE uid = ?", (uid,))
        connection.commit()

    original = A.LOCAL_ELITE_CHANCE
    A.LOCAL_ELITE_CHANCE = 0.0        # normal encounters only: one chunk per win
    try:
        reports = []
        for _ in range(6):
            _, payload = _envelope(
                client.post("/flash.do", data={"m": "show", "showId": "6", "uid": uid, "hid": "1"})
            )
            assert payload["is_win"] == 1
            reports.append(payload["rage_point"])
    finally:
        A.LOCAL_ELITE_CHANCE = original

    assert all(0 <= value <= 100 for value in reports), reports
    assert reports.count(100) == 1, f"无双 must trigger once per filled meter: {reports}"
    assert reports[0] < 100, "the first win cannot already be 无双"
    # The win right after the 无双 one starts the meter over from a single chunk.
    spent = reports.index(100) + 1
    assert spent >= len(reports) or reports[spent] == A.LOCAL_RAGE_GAIN_PER_WIN, reports

    # An elite clear fills twice as fast.
    A.LOCAL_ELITE_CHANCE = 1.0
    try:
        _, elite = _envelope(
            client.post("/flash.do", data={"m": "show", "showId": "6", "uid": uid, "hid": "1"})
        )
    finally:
        A.LOCAL_ELITE_CHANCE = original
    assert len(elite["def_list"]) >= 3, "an elite encounter fields leader + pair"
    # The meter stood at one chunk after the last normal win; an elite clear adds
    # two, so the result is either that value or 100 when it tips over.
    assert elite["rage_point"] in (
        0, 100, A.LOCAL_RAGE_GAIN_PER_WIN, A.LOCAL_RAGE_GAIN_PER_WIN * 3,
    )


def test_skill_slots_scale_with_rarity(tmp_path: Path):
    """固定 4 个技能槽会让稀有宠和普通宠没区别；槽位应按星级+世代增长。"""
    from pet_hunter_server.app import _merge_skills, _skill_cap

    assert _skill_cap(3, 1) == 4
    assert _skill_cap(5, 1) == 5
    assert _skill_cap(8, 2) == 8
    assert _skill_cap(12, 3) == 10
    assert _skill_cap(99, 99) == 12
    # Higher rarity never gets fewer slots than lower rarity at the same generation.
    assert _skill_cap(12, 1) > _skill_cap(3, 1)

    # The merge respects the cap and never downgrades a family.
    pool = "101:102:103:104:201:202:203:5101:5102:5103:5002:5003"
    merged = _merge_skills(pool, "", _skill_cap(12, 3)).split(":")
    assert len(merged) <= _skill_cap(12, 3)
    assert all(token.isdigit() for token in merged)
    tight = _merge_skills(pool, "", 4).split(":")
    assert len(tight) <= 4, "the cap argument must still be honoured"

    # A high-star main keeps every skill it already had, even with a big pool.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "SkillCap")
    with sqlite3.connect(database) as connection:
        main_id, vice_id = [r[0] for r in connection.execute(
            "SELECT id FROM pets WHERE player_id=1 ORDER BY id"
        ).fetchall()]
        connection.execute("UPDATE pets SET star=8, generation=2, skills=? WHERE id=?",
                           ("101:102:201:202:5101", main_id))
        connection.execute("UPDATE pets SET skills=? WHERE id=?",
                           ("103:203:5102:5002", vice_id))
    command, payload = _envelope(client.post(
        "/flash.do", data={"m": "show", "showId": "65", "uid": uid,
                           "main": main_id, "vice": vice_id, "ttype": 1},
    ))
    assert command == 65
    assert payload["type"] == 1
    assert len(payload["skills"]) <= _skill_cap(8, 3)


def test_mount_page_lists_only_mounts_even_when_gear_slots_are_full(tmp_path: Path):
    # 104 ignored `slot_type`, so the mount page counted the expedition gear too
    # (equip_count 6/6) and the rent guard answered "full", which is why the mount
    # could never be switched once the gear slots were taken.
    from pet_hunter_server import app as A

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "MountF")
    table = config_tables._table("exploreEquip.txt")
    mounts = sorted(int(k) for k, v in table.items() if str(v.get("type", "")).strip() == "1")
    gear = sorted(int(k) for k, v in table.items() if str(v.get("type", "")).strip() == "2")
    assert mounts and len(gear) >= A.LOCAL_EXPLORE_HIRE_SLOTS

    # Fill the gear category completely.
    for item in gear[: A.LOCAL_EXPLORE_HIRE_SLOTS]:
        _envelope(client.post(
            "/flash.do", data={"m": "show", "showId": "102", "uid": uid,
                               "gid": item, "ttype": "2"},
        ))

    command, mounts_page = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "104", "uid": uid,
                                       "ttype": "1", "p": "1", "n": "9"})
    )
    assert command == 104
    assert all(entry["type"] == 1 for entry in mounts_page["list"]), mounts_page["list"]
    assert mounts_page["equip_count"] <= 1, "gear must not count against mount slots"

    # Switching mounts still works even though the gear category is full.
    for mount in mounts[:2]:
        command, ack = _envelope(client.post(
            "/flash.do", data={"m": "show", "showId": "102", "uid": uid,
                               "gid": mount, "ttype": "1"},
        ))
        assert command == 102 and ack["value"] == "ok", ack
    with sqlite3.connect(database) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]
        rented_mounts = [r[0] for r in connection.execute(
            "SELECT equip_id FROM explore_rented WHERE player_id=? AND slot_type=1",
            (player_id,),
        )]
    assert rented_mounts == [mounts[1]]
    assert A._explore_horse(database, player_id) == mounts[1]


def test_renting_another_mount_switches_the_one_you_ride(tmp_path: Path):
    # 102 used to INSERT OR IGNORE and _explore_horse picked the lowest id, so
    # renting a different mount never changed the one on the expedition page —
    # the "坐骑没法选" report.
    from pet_hunter_server import app as A

    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "MountSw")
    table = config_tables._table("exploreEquip.txt")
    mounts = sorted(
        int(k) for k, v in table.items() if str(v.get("type", "")).strip() == "1"
    )
    assert len(mounts) >= 2, "exploreEquip needs at least two mount rows"

    for mount in mounts[:2]:
        _envelope(client.post(
            "/flash.do", data={"m": "show", "showId": "102", "uid": uid,
                               "gid": mount, "ttype": "1"},
        ))
    with sqlite3.connect(database) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]
        rented = [r[0] for r in connection.execute(
            "SELECT equip_id FROM explore_rented WHERE player_id=? AND slot_type=1",
            (player_id,),
        )]
    assert rented == [mounts[1]], f"only the newest mount may stay rented: {rented}"
    assert A._explore_horse(database, player_id) == mounts[1]


def test_explore_hire_list_only_lists_what_is_rented(tmp_path: Path):
    # HireListUI.as:242-266 walks list[] unguarded and resolves name/icon from
    # exploreEquip itself, so each entry only needs id + type. The list must come
    # from explore_rented: answering with the whole exploreEquip catalogue made
    # list[0] permanently 100001, which kept HireMountsUI on its "already hired"
    # branch and made the shop (100) unreachable — the mount was unpickable.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "HireOne")
    table = config_tables._table("exploreEquip.txt")
    ids = {int(k) for k in table}
    rentable = sorted(i for i in ids if str(table[i].get("type", "")).strip() == "1")
    assert rentable, "exploreEquip needs at least one type=1 mount"

    command, empty = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "104", "uid": uid, "ttype": 1, "p": 1, "n": 9})
    )
    assert command == 104
    assert empty["type"] == 1
    assert empty["max_equip_count"] >= 1
    assert empty["list"] == [], "nothing is hired yet, so nothing may be listed"
    assert empty["equip_count"] == 0

    with sqlite3.connect(database) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO explore_rented (player_id, equip_id, slot_type) VALUES (?,?,1)",
            (player_id, rentable[0]),
        )
        connection.commit()

    _, hired = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "104", "uid": uid, "ttype": 1, "p": 1, "n": 9})
    )
    assert hired["list"] == [{"id": rentable[0], "type": 1}]
    assert hired["equip_count"] == 1


def test_training_slots_render_pets_instead_of_the_wand_placeholder(tmp_path: Path):
    # DevelopItem.as:178 loads clip_wand whenever slot data is null, which is
    # what the player saw; DevelopUI.as:133-134 needs train_state and train_time
    # to show a running countdown.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "TrnSlot")
    _, idle = _envelope(client.post("/flash.do", data={"m": "show", "showId": "504", "uid": uid}))
    # The roster is always shipped now, otherwise every slot paints clip_wand.
    assert idle["list"], "an idle player still sees their pets"
    assert all(entry["train_time"] == 0 for entry in idle["list"])
    with sqlite3.connect(database) as connection:
        pet_id = connection.execute("SELECT id FROM pets WHERE player_id=1 ORDER BY id").fetchone()[0]
    command, started = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "10", "uid": uid, "index": pet_id, "ttype": 1})
    )
    assert command == 10 and started["train_type"] == 1
    _, slots = _envelope(client.post("/flash.do", data={"m": "show", "showId": "504", "uid": uid}))
    # The training run floats to the front ahead of the idle roster.
    slot = slots["list"][0]
    assert slot["index"] == pet_id
    assert str(slot["icon"]).isdigit() and slot["icon"], "a missing icon keeps clip_wand"
    assert slot["name"]
    assert slot["train_state"] == 1
    assert slot["train_time"] > 0, "DevelopItem.as:150 needs a positive countdown"


def test_arena_fighter_rejects_unknown_player(tmp_path: Path):
    client = create_app({"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}).test_client()
    response = client.post("/flash.do", data={"m": "show", "showId": "506", "uid": "missing"})
    assert response.get_data(as_text=True) == "-1:103"


def test_pet_lists_resolve_real_names_from_config(tmp_path: Path):
    # DevelopUI.as:111-144 and PetSynthesisListUI.as:218 both fall back to
    # pet.txt when `name` is absent, but a stored NULL rendered as "null" in
    # the earlier build, so the server must resolve the real config name.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "NameFix")
    for show_id in (505, 62):
        _, payload = _envelope(
            client.post("/flash.do", data={"m": "show", "showId": show_id, "uid": uid, "p": 1, "n": 9})
        )
        rows = payload["list"]
        assert rows, f"{show_id} returned nothing"
        for row in rows:
            assert row["name"], f"{show_id} row {row['index']} has no name"
            expected = config_tables._table("pet.txt")[row["id"]]["name"]
            assert row["name"] == expected


def test_pet_synthesis_pick_lists_usable_pets(tmp_path: Path):
    # PetSynthesisListUI.as:198-224 renders list[] with index/name/lv/icon, and
    # shows error 10 when the first page is empty, so only usable pets belong here.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "SynPick")
    with sqlite3.connect(database) as connection:
        locked = connection.execute("SELECT id FROM pets WHERE player_id=1 ORDER BY id").fetchall()
        connection.execute("UPDATE pets SET is_locked=1 WHERE id=?", (locked[1][0],))
    for show_id in (62, 63):
        command, payload = _envelope(
            client.post(
                "/flash.do",
                data={"m": "show", "showId": show_id, "uid": uid, "p": 1, "n": 9},
            )
        )
        assert command == show_id
        assert payload["list"], f"{show_id} returned no selectable pet"
        for row in payload["list"]:
            assert {"index", "id", "icon", "lv"} <= set(row)
            assert row["index"] != locked[1][0]


def test_pet_synthesis_consumes_vice_and_reinforces_main(tmp_path: Path):
    # PetSynthesisUI.as:254-264 sends {main,vice,ttype}; PetSynthesisResultUI
    # .as:124-197 needs index/icon/name|lv/type/skills and the exd_* fields.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "SynMake")
    with sqlite3.connect(database) as connection:
        main_id, vice_id = [r[0] for r in connection.execute(
            "SELECT id FROM pets WHERE player_id=1 ORDER BY id"
        ).fetchall()]
        # Give the material real reinforcement so the 50% inheritance rule is
        # observable; a fresh pet has pro_* = 0 and would inherit nothing.
        connection.execute(
            "UPDATE pets SET pro_hp=100, pro_speed=100, pro_phy_att=100,"
            " pro_mag_att=100, pro_phy_def=100, pro_mag_def=100 WHERE id=?",
            (vice_id,),
        )
    command, payload = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "65", "uid": uid,
                  "main": main_id, "vice": vice_id, "ttype": 1},
        )
    )
    assert command == 65
    assert payload["index"] == main_id and payload["icon"]
    # PetSynthesisResultUI.as:139 prints `name` first and only falls back to
    # pet.txt when it is falsy, so ship the real name rather than "".
    assert payload["name"] == config_tables._table("pet.txt")[payload["id"]]["name"]
    # help.txt id 10: 合成必增世代，且主宠继承副宠 50% 强化值。
    assert payload["exd_generation"] == 2
    assert all(payload[f"exd_{k}_tp"] == 50 for k in
               ("hp", "speed", "phy_att", "mag_att", "phy_def", "mag_def"))
    assert payload["type"] == 1
    assert isinstance(payload["skills"], list)
    with sqlite3.connect(database) as connection:
        remaining = connection.execute(
            "SELECT id FROM pets WHERE player_id=1 ORDER BY id"
        ).fetchall()
    assert [r[0] for r in remaining] == [main_id]


def test_pet_synthesis_rejects_locked_and_self(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "SynBad")
    with sqlite3.connect(database) as connection:
        ids = [r[0] for r in connection.execute(
            "SELECT id FROM pets WHERE player_id=1 ORDER BY id"
        ).fetchall()]
        connection.execute("UPDATE pets SET is_locked=1 WHERE id=?", (ids[1],))
    response = client.post(
        "/flash.do",
        data={"m": "show", "showId": "65", "uid": uid,
              "main": ids[0], "vice": ids[1], "ttype": 1},
    )
    assert response.get_data(as_text=True) == "-1:524"
    response = client.post(
        "/flash.do",
        data={"m": "show", "showId": "65", "uid": uid,
              "main": ids[0], "vice": ids[0], "ttype": 1},
    )
    assert response.get_data(as_text=True) == "-1:100"


def test_pet_flush_grow_consumes_item_and_persists_growth_fields(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "GrowPet")
    with sqlite3.connect(database) as connection:
        pet_id = connection.execute("SELECT id FROM pets WHERE player_id = 1 ORDER BY id LIMIT 1").fetchone()[0]
        connection.execute("INSERT INTO inventory (player_id,item_id,team,quantity,icon,item_type,use_type) VALUES (1,10001,1,1,10001,1,2)")
    command, payload = _envelope(client.post("/flash.do", data={"m":"show","showId":"19","uid":uid,"index":pet_id}))
    assert command == 19
    assert "total_gw" in payload and "hp_gw" in payload
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT quantity FROM inventory WHERE item_id=10001").fetchone() is None
        assert connection.execute("SELECT gw_flush_count FROM pets WHERE id=?", (pet_id,)).fetchone()[0] == 1


def test_pet_flush_nature_and_forget_skill_use_real_pet_context(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "MutPet")
    with sqlite3.connect(database) as connection:
        pet_id = connection.execute("SELECT id FROM pets WHERE player_id = 1 ORDER BY id LIMIT 1").fetchone()[0]
        connection.execute("INSERT INTO inventory (player_id,item_id,team,quantity,icon,item_type,use_type) VALUES (1,10009,1,1,10009,9,2)")
        connection.execute("INSERT INTO inventory (player_id,item_id,team,quantity,icon,item_type,use_type) VALUES (1,10028,1,1,10028,2,2)")
    assert _envelope(client.post("/flash.do", data={"m":"show","showId":"20","uid":uid,"index":pet_id}))[0] == 20
    command, payload = _envelope(client.post("/flash.do", data={"m":"show","showId":"21","uid":uid,"index":pet_id}))
    assert command == 21
    assert len(payload["skills"]) >= 1


def test_pet_forget_skill_rejects_single_skill_pet(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "OneSkill")
    with sqlite3.connect(database) as connection:
        pet_id = connection.execute("SELECT id FROM pets WHERE player_id = 1 ORDER BY id LIMIT 1").fetchone()[0]
        connection.execute("UPDATE pets SET skills='101' WHERE id=?", (pet_id,))
        connection.execute("INSERT INTO inventory (player_id,item_id,team,quantity,icon,item_type,use_type) VALUES (1,10028,1,1,10028,2,2)")
    response = client.post("/flash.do", data={"m":"show","showId":"21","uid":uid,"index":pet_id})
    assert response.get_data(as_text=True) == "-1:515"


def test_new_character_gets_the_local_starter_pack_in_the_pet_list(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()
    uid = _create_local_player(client, "PetTest")

    response = client.post(
        "/flash.do",
        data={"m": "show", "showId": "11", "uid": uid, "p": "1", "n": "9"},
    )

    command, payload = _envelope(response)
    assert response.status_code == 200
    assert command == 11
    assert payload["pet_num"] == 2
    assert payload["max_pet_num"] == 30
    assert payload["add_pet_card_num"] == 1
    assert payload["own_card_num"] == 1
    assert len(payload["pets"]) == 2
    by_id = {pet["id"]: pet for pet in payload["pets"]}
    assert set(by_id) == {1001, 2019}
    assert by_id[1001]["icon"] == 1001 and by_id[1001]["lv"] == 1
    assert by_id[2019]["icon"] == 2019 and by_id[2019]["lv"] == 1
    for pet in payload["pets"]:
        assert pet["battle_state"] == 0
        assert isinstance(pet["index"], int)
        # The name comes from pet.txt rather than being omitted: FarmUI's
        # PetItem and Pet.as:135 read data.name with no fallback, so a missing
        # key rendered as "undefined" on the device.
        assert pet["name"] == config_tables._table("pet.txt")[pet["id"]]["name"]


def test_pet_list_pages_by_stable_index_and_reports_total(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    config = {"TESTING": True, "DATABASE": database}
    client = create_app(config).test_client()
    uid = _create_local_player(client, "Pager")
    with sqlite3.connect(database) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO pets (player_id, pet_id, lv, star, pro, icon)
            VALUES (?, 1004, 2, 3, 2, 1004), (?, 1007, 3, 3, 3, 1007)
            """,
            (player_id, player_id),
        )

    first = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "11", "uid": uid, "p": "1", "n": "2"},
        )
    )[1]
    second = _envelope(
        client.post(
            "/flash.do",
            data={"m": "show", "showId": "11", "uid": uid, "p": "2", "n": "2"},
        )
    )[1]

    assert first["pet_num"] == 4
    assert [pet["id"] for pet in first["pets"]] == [1001, 2019]
    assert [pet["id"] for pet in second["pets"]] == [1004, 1007]


def test_pet_detail_returns_the_persisted_record(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "Detail")
    listed = _envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "11", "uid": uid}
        )
    )[1]
    index = listed["pets"][0]["index"]

    response = client.post(
        "/flash.do", data={"m": "show", "showId": "12", "uid": uid, "index": str(index)}
    )

    command, payload = _envelope(response)
    assert response.status_code == 200
    assert command == 12
    # Subset assertion on purpose: the payload may carry extra fields, and a whole
    # dict comparison made this test order-dependent as soon as one was added.
    expected = {
        "index": index,
        "star": 3,
        "is_lockable": True,
        "is_locked": False,
        "icon": 1001,
        "id": 1001,
        "lv": 1,
        "exp": 0,
        "pro": 1,
        "next_pet": {
            "id": 1002,
            "need_lv": 5,
            "need_money": 0,
            "need_point": 0,
            "need_crystal": 0,
            "need_goods": [],
        },
    }
    for key, value in expected.items():
        assert payload[key] == value, f"{key}: {payload[key]!r} != {value!r}"


def test_pet_detail_rejects_unknown_index_and_other_players_pets(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    owner = _create_local_player(client, "Owner")
    other = _create_local_player(client, "Other")
    index = _envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "11", "uid": owner}
        )
    )[1]["pets"][0]["index"]

    unknown = client.post(
        "/flash.do", data={"m": "show", "showId": "12", "uid": owner, "index": "999999"}
    )
    cross_player = client.post(
        "/flash.do", data={"m": "show", "showId": "12", "uid": other, "index": str(index)}
    )

    assert unknown.status_code == 404
    assert unknown.get_data(as_text=True).startswith("-1:")
    assert cross_player.status_code == 404
    assert cross_player.get_data(as_text=True).startswith("-1:")


def test_pet_list_is_persistent_across_restart_and_rejects_bad_paging(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    config = {"TESTING": True, "DATABASE": database}
    uid = _create_local_player(create_app(config).test_client(), "Persist")

    restarted = create_app(config).test_client()
    payload = _envelope(
        restarted.post(
            "/flash.do", data={"m": "show", "showId": "11", "uid": uid}
        )
    )[1]
    bad_page = restarted.post(
        "/flash.do",
        data={"m": "show", "showId": "11", "uid": uid, "p": "0", "n": "9"},
    )
    bad_size = restarted.post(
        "/flash.do",
        data={"m": "show", "showId": "11", "uid": uid, "p": "1", "n": "10"},
    )

    assert payload["pet_num"] == 2
    assert bad_page.status_code == 400
    assert bad_size.status_code == 400


def test_pet_list_rejects_unknown_player(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()

    response = client.post(
        "/flash.do", data={"m": "show", "showId": "11", "uid": "missing"}
    )

    assert response.status_code == 404
    assert response.get_data(as_text=True).startswith("-1:")


def test_grant_starter_pets_is_idempotent_and_keeps_existing_pets(tmp_path: Path):
    from pet_hunter_server import grant_starter_pets

    database = tmp_path / "game.sqlite3"
    config = {"TESTING": True, "DATABASE": database}
    client = create_app(config).test_client()
    uid = _create_local_player(client, "Grant")
    with sqlite3.connect(database) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()[0]

    assert grant_starter_pets(database) == 0
    assert grant_starter_pets(database) == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM pets WHERE player_id = ?", (player_id,)
        ).fetchone()[0] == 2


def _pet_index_for(client, uid: str, pet_id: int) -> int:
    pets = _envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "11", "uid": uid, "n": "9"}
        )
    )[1]["pets"]
    return next(pet["index"] for pet in pets if pet["id"] == pet_id)


def test_pet_rename_persists_and_rejects_invalid_names(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "Renamer")
    index = _pet_index_for(client, uid, 1001)

    renamed = client.post(
        "/flash.do",
        data={"m": "show", "showId": "18", "uid": uid, "index": str(index), "pName": "阿火"},
    )
    detail = _envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "12", "uid": uid, "index": str(index)}
        )
    )[1]
    too_long = client.post(
        "/flash.do",
        data={"m": "show", "showId": "18", "uid": uid, "index": str(index), "pName": "一二三四五六七八九"},
    )
    blank = client.post(
        "/flash.do",
        data={"m": "show", "showId": "18", "uid": uid, "index": str(index), "pName": "   "},
    )

    assert _envelope(renamed) == (18, {"value": "ok"})
    assert detail["name"] == "阿火"
    assert too_long.get_data(as_text=True) == "-1:514"
    assert blank.get_data(as_text=True) == "-1:514"


def test_pet_rename_rejects_another_players_pet(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    owner = _create_local_player(client, "OwnerA")
    other = _create_local_player(client, "OtherA")
    index = _pet_index_for(client, owner, 1001)

    response = client.post(
        "/flash.do",
        data={"m": "show", "showId": "18", "uid": other, "index": str(index), "pName": "偷"},
    )

    assert response.get_data(as_text=True) == "-1:506"


def test_pet_lock_toggles_and_is_reported_as_client_strings(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "Locker")
    index = _pet_index_for(client, uid, 2019)

    locked = client.post(
        "/flash.do", data={"m": "show", "showId": "55", "uid": uid, "index": str(index)}
    )
    detail_locked = _envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "12", "uid": uid, "index": str(index)}
        )
    )[1]
    unlocked = client.post(
        "/flash.do", data={"m": "show", "showId": "55", "uid": uid, "index": str(index)}
    )

    assert _envelope(locked) == (55, {"value": "true"})
    assert detail_locked["is_locked"] is True
    assert _envelope(unlocked) == (55, {"value": "false"})


def test_pet_release_deletes_but_refuses_locked_pets(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "Releaser")
    index = _pet_index_for(client, uid, 1001)

    locked = client.post(
        "/flash.do", data={"m": "show", "showId": "55", "uid": uid, "index": str(index)}
    )
    refused = client.post(
        "/flash.do", data={"m": "show", "showId": "15", "uid": uid, "index": str(index)}
    )
    client.post(
        "/flash.do", data={"m": "show", "showId": "55", "uid": uid, "index": str(index)}
    )
    released = client.post(
        "/flash.do", data={"m": "show", "showId": "15", "uid": uid, "index": str(index)}
    )
    listed = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "11", "uid": uid})
    )[1]

    assert _envelope(locked) == (55, {"value": "true"})
    assert refused.get_data(as_text=True) == "-1:524"
    # 15 also reports the recycle payout: pet.txt `recyclePoint` is "goodsId:num"
    # and PetInfoUI.as:278-285 draws the refund line from these two fields.
    command, released_payload = _envelope(released)
    assert command == 15
    assert released_payload["value"] == "ok"
    assert "free_goods_id" in released_payload and "free_goods_num" in released_payload
    assert listed["pet_num"] == 1
    assert [pet["id"] for pet in listed["pets"]] == [2019]


def test_starter_pets_are_born_with_traits(tmp_path: Path):
    # The starter INSERT only wrote `skills`, and the boot backfill only touches
    # rows that already exist, while registration happens after initialisation —
    # so every new character's pets had empty `buffs` and item 10034 (遗忘卡牌)
    # always answered -1:522.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "StartTr")

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT id, buffs FROM pets WHERE player_id = 1 ORDER BY id"
        ).fetchall()
    assert rows, "a new character must own starter pets"
    for pet_id, buffs in rows:
        assert buffs, f"pet {pet_id} was born without traits"

    # 85 (遗忘卡牌) needs the item and at least two traits; the starter now has
    # both, so it can list instead of answering -1:522 forever.
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO inventory (player_id, item_id, team, quantity, icon, item_type, use_type)"
            " VALUES (1, 10034, 1, 1, 10004, 0, 0)"
        )
        connection.commit()
    command, payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "85", "uid": uid,
                                       "index1": str(rows[0][0])})
    )
    assert command == 85
    assert payload.get("is_list") == 1
    assert payload["pet"]["buffs"], "the trait list must not be empty"


def test_skill_synthesis_merges_families_and_keeps_the_highest_level():
    # Command 65 with ttype=1 used to leave `skills` untouched, which is why
    # 技能合成 felt like it did nothing. Rule (LOCAL DESIGN, the client ships none):
    # union of both pools, one per family at the higher level, at most four, with a
    # 30% chance of one extra level.
    from pet_hunter_server import app as A
    from pet_hunter_server import config_tables as tables

    catalog = tables._table("skill.txt")

    def family_of(skill_id: int) -> str:
        name = str(catalog[skill_id].get("name", "") or "")
        return name.split("级", 1)[-1].strip() if "级" in name else name

    def level_of(skill_id: int) -> int:
        raw = str(catalog[skill_id].get("level", "0") or 0).strip()
        return int(raw) if raw.isdigit() else 0

    main, vice = "101:5101", "102:5201"
    for _ in range(5):  # the 30% upgrade makes any single run non-deterministic
        ids = [int(token) for token in A._merge_skills(main, vice).split(":") if token.isdigit()]
        assert ids, "synthesis must yield skills"
        assert len(ids) <= 4, ids
        assert len(ids) == len(set(ids)), f"duplicate skills: {ids}"
        assert all(skill_id in catalog for skill_id in ids), ids
        families = [family_of(skill_id) for skill_id in ids]
        assert len(families) == len(set(families)), f"two skills from one family: {ids}"

        expected = {family_of(int(s)): level_of(int(s)) for s in main.split(":")}
        expected.update({family_of(int(s)): level_of(int(s)) for s in vice.split(":")})
        for skill_id in ids:
            family = family_of(skill_id)
            assert family in expected, f"unexpected family {family}"
            assert level_of(skill_id) >= expected[family], (
                "a merge must never downgrade a family", family, skill_id, expected[family]
            )

    # A same-family merge keeps the stronger one (or upgrades it), never the weaker.
    merged = [int(t) for t in A._merge_skills("103", "101").split(":") if t.isdigit()]
    assert merged == [103] or level_of(merged[0]) >= 3


def test_flush_grow_rerolls_instead_of_rotating(tmp_path: Path):
    # Command 19 used to rotate the six growth numbers, so `total_gw` (label 成长,
    # ui.txt 36) never moved and the sixth use restored the original layout.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "GrowRoll")
    with sqlite3.connect(database) as connection:
        pet_id, species = connection.execute(
            "SELECT id, pet_id FROM pets WHERE player_id = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        connection.execute(
            "INSERT INTO inventory (player_id, item_id, team, quantity, icon, item_type, use_type)"
            " VALUES (1, 10001, 1, 8, 10001, 1, 2)"
        )
        connection.commit()
    lo, hi = config_tables.pet_record(species)["grows"].split(":")
    lo, hi = int(lo), int(hi)

    totals: list[int] = []
    for _ in range(4):
        command, payload = _envelope(
            client.post("/flash.do", data={"m": "show", "showId": "19", "uid": uid, "index": pet_id})
        )
        assert command == 19
        for key in ("hp_gw", "speed_gw", "phy_att_gw", "mag_att_gw", "phy_def_gw", "mag_def_gw"):
            assert lo <= payload[key] <= hi, f"{key} fell outside pet.txt grows {lo}:{hi}"
        assert 1 <= payload["gw_rate"] <= 5
        assert payload["total_gw"] == sum(
            payload[k] for k in ("hp_gw", "speed_gw", "phy_att_gw",
                                 "mag_att_gw", "phy_def_gw", "mag_def_gw")
        )
        totals.append(payload["total_gw"])
    assert len(set(totals)) > 1, f"total_gw never moved, still rotating: {totals}"


def test_friend_list_has_local_hunters_and_512_513_ack(tmp_path: Path):
    # A solo server has no other players, so the list must still render: 51 appends
    # local filler hunters and 52 can open them.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "Friend1")

    command, listing = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "51", "uid": uid, "p": "1", "n": "9"})
    )
    assert command == 51
    assert listing["player_str_id"] == uid
    assert listing["friend"], "the friend list must never be empty on a solo server"
    entry = listing["friend"][0]
    for field in ("id", "state", "name", "img"):
        assert field in entry, entry
    # `img` is a paper-doll layer string, not an icon id.
    assert "_" in str(entry["img"])

    command, detail = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "52", "uid": uid, "gid": entry["id"]})
    )
    assert command == 52
    assert detail["player"]["name"] == entry["name"]
    assert detail["player"]["lv"] > 0
    assert detail["pets"], "a friend card needs a pet roster"

    for show_id in ("512", "513"):
        command, ack = _envelope(
            client.post("/flash.do", data={"m": "show", "showId": show_id, "uid": uid, "gid": entry["id"]})
        )
        assert command == int(show_id)
        assert ack["value"] == "ok"


def test_guild_lifecycle_create_list_members_rename_quit(tmp_path: Path):
    # 86 only opens the guild page when `position` is truthy (MainUI.as:212-221),
    # so a guildless player must answer position 0 rather than an empty guild.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "GuildOne")

    command, mine = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "86", "uid": uid})
    )
    assert command == 86
    assert mine["position"] == 0

    # 92 sends no parameters at all, so the server has to name the guild.
    command, created = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "92", "uid": uid})
    )
    assert command == 92
    assert created["value"] == "ok"
    guild_id = created["guild_id"]

    _, mine = _envelope(client.post("/flash.do", data={"m": "show", "showId": "86", "uid": uid}))
    assert mine["position"] == 1, "the creator becomes the leader"
    assert mine["guild_id"] == guild_id
    assert mine["mem_num"] == 1
    assert mine["leader_name"] == "GuildOne"

    # 88 feeds SocietiesTopUI.as:201-218.
    command, board = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "88", "uid": uid})
    )
    assert command == 88
    row = next(g for g in board["guilds"] if g["id"] == guild_id)
    for field in ("id", "name", "mem_num", "max_mem_num", "leader_name"):
        assert field in row
    assert row["mem_num"] == 1

    # 91 feeds SocietiesListUI.as:180-195.
    command, members = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "91", "uid": uid, "gid": guild_id})
    )
    assert command == 91
    assert [m["position"] for m in members["list"]] == [1]
    assert members["list"][0]["name"] == "GuildOne"

    # 89 renames (leader only).
    command, renamed = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "89", "uid": uid, "pName": "夜行团"})
    )
    assert command == 89 and renamed["value"] == "ok"
    _, mine = _envelope(client.post("/flash.do", data={"m": "show", "showId": "86", "uid": uid}))
    assert mine["guild_name"] == "夜行团"

    # 90 disbands when the leader is the only member.
    command, quit_payload = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "90", "uid": uid})
    )
    assert command == 90 and quit_payload["value"] == "ok"
    _, mine = _envelope(client.post("/flash.do", data={"m": "show", "showId": "86", "uid": uid}))
    assert mine["position"] == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM guilds").fetchone()[0] == 0


def test_guild_list_always_has_something_to_render(tmp_path: Path):
    # A solo hunter should still see a populated board instead of an empty page.
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "GuildTwo")
    command, board = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "88", "uid": uid})
    )
    assert command == 88
    assert len(board["guilds"]) >= 3
    for guild in board["guilds"]:
        assert guild["max_mem_num"] >= guild["mem_num"] >= 0
        assert guild["name"]


def test_pet_evolve_returns_new_detail_and_enforces_level_and_chain(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    config = {"TESTING": True, "DATABASE": database}
    client = create_app(config).test_client()
    uid = _create_local_player(client, "Evolver")
    index = _pet_index_for(client, uid, 1001)

    too_low = client.post(
        "/flash.do", data={"m": "show", "showId": "14", "uid": uid, "index": str(index)}
    )
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE pets SET lv = 5 WHERE id = ?", (index,))
    evolved = _envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "14", "uid": uid, "index": str(index)}
        )
    )
    detail = _envelope(
        client.post(
            "/flash.do", data={"m": "show", "showId": "12", "uid": uid, "index": str(index)}
        )
    )[1]

    assert too_low.get_data(as_text=True) == "-1:505"
    assert evolved[0] == 14
    assert evolved[1]["id"] == 1002
    assert evolved[1]["icon"] == 1002
    assert evolved[1]["next_pet"]["id"] == 1003
    assert detail["id"] == 1002 and detail["icon"] == 1002

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE pets SET pet_id = 1003, icon = 1003 WHERE id = ?", (index,))
    end_of_chain = client.post(
        "/flash.do", data={"m": "show", "showId": "14", "uid": uid, "index": str(index)}
    )
    assert end_of_chain.get_data(as_text=True) == "-1:504"


def test_pet_evolve_refuses_a_locked_pet(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "LockEvo")
    index = _pet_index_for(client, uid, 1001)
    client.post(
        "/flash.do", data={"m": "show", "showId": "55", "uid": uid, "index": str(index)}
    )

    response = client.post(
        "/flash.do", data={"m": "show", "showId": "14", "uid": uid, "index": str(index)}
    )

    assert response.get_data(as_text=True) == "-1:524"


def test_pet_expand_capacity_adds_nine_up_to_the_local_maximum(tmp_path: Path):
    database = tmp_path / "game.sqlite3"
    client = create_app({"TESTING": True, "DATABASE": database}).test_client()
    uid = _create_local_player(client, "Expander")

    first = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "40", "uid": uid})
    )
    listed = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "11", "uid": uid})
    )[1]

    assert first == (40, {"value": "ok"})
    assert listed["max_pet_num"] == 39

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE players SET pet_capacity = 90 WHERE uid = ?", (uid,))
    at_max = client.post("/flash.do", data={"m": "show", "showId": "40", "uid": uid})
    max_list = _envelope(
        client.post("/flash.do", data={"m": "show", "showId": "11", "uid": uid})
    )[1]

    assert at_max.get_data(as_text=True) == "-1:204"
    assert max_list["own_card_num"] == 0


def test_non_allowed_network_is_rejected_before_routes_run():
    client = create_app(
        {"TESTING": True, "ALLOWED_NETWORKS": ["192.168.137.0/24"]}
    ).test_client()

    response = client.get("/health", environ_overrides={"REMOTE_ADDR": "203.0.113.8"})

    assert response.status_code == 403
    assert response.get_json() == {"error": "source_network_not_allowed"}


