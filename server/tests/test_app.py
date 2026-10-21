from pathlib import Path
import logging
import json
import sqlite3
import xml.etree.ElementTree as ET

from pet_hunter_server import create_app


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

    assert response.status_code == 501
    assert "response source=127.0.0.1 method=POST path=/flash.do status=501" in caplog.text
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


def test_unknown_flash_command_is_observed_but_not_given_a_guessed_success(caplog):
    caplog.set_level(logging.INFO)
    client = create_app({"TESTING": True}).test_client()

    response = client.post(
        "/flash.do?m=unimplemented",
        data={"uname": "player@example.test", "pwd": "private-password", "sn": "secret-signature"},
    )

    assert response.status_code == 501
    assert response.get_json() == {"error": "protocol_not_implemented"}
    assert "command=unknown" in caplog.text
    assert "pwd" in caplog.text
    assert "private-password" not in caplog.text
    assert "player@example.test" not in caplog.text
    assert "secret-signature" not in caplog.text


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


def test_initial_task_list_returns_empty_list_for_task_track_ui(tmp_path: Path):
    client = create_app(
        {"TESTING": True, "DATABASE": tmp_path / "game.sqlite3"}
    ).test_client()

    response = client.post(
        "/flash.do",
        data={"m": "show", "showId": "511", "uid": "local-test"},
    )

    command, payload = response.get_data(as_text=True).split("\t", 1)
    assert response.status_code == 200
    assert command == "511"
    assert json.loads(payload) == {"list": []}


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
    assert home["arena_rank"] == 0
    assert home["img"] == "100001_100002_100003"


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
        "max_bag_size": 100,
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
    assert payload["max_bag_size"] == 100
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
    assert item["icon"] == "p20001"
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
    # Positive money hides the not-yet-implemented sell button (local gate).
    assert payload["money"] > 0


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
    assert [row["id"] for row in gold["list"]] == [10007, 10001, 10002]
    assert all(row["team"] == 1 and row["type"] == 1 for row in gold["list"])
    assert [row["money"] for row in gold["list"]] == [80, 90, 360]
    # ShopListUI hands the row icon to PropItem, which prefixes "p" itself.
    assert gold["list"][0]["icon"] == 10007
    assert silver["shop_type"] == 2
    assert [(row["id"], row["type"], row["point"]) for row in silver["list"]] == [
        (10010, 2, 500)
    ]
    assert mystery["shop_type"] == 4
    assert mystery["list"] == []


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
    assert bag["goods_list"][0]["icon"] == "p10007"


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
        data={"m": "show", "showId": "29", "uid": uid, "gid": "10010", "count": "1", "ttype": "2", "loc": "1"},
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


def _create_local_player(client, nick: str) -> str:
    created = client.post(
        "/flash.do", data={"m": "autoReg", "nick": nick, "sex": "1"}
    )
    return json.loads(created.get_data(as_text=True).split("\t", 1)[1])["value"]


def _envelope(response):
    command, payload = response.get_data(as_text=True).split("\t", 1)
    return int(command), json.loads(payload)


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
        # A default-named pet omits "name" so the client falls back to pet.txt.
        assert "name" not in pet


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
    assert payload == {
        "index": index,
        "star": 3,
        "is_lockable": True,
        "is_locked": False,
        "icon": 1001,
        "id": 1001,
        "lv": 1,
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
    assert _envelope(released) == (15, {"value": "ok"})
    assert listed["pet_num"] == 1
    assert [pet["id"] for pet in listed["pets"]] == [2019]


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
