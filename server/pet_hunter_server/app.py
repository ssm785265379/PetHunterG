import ipaddress
import hashlib
import hmac
import json
import secrets
import sqlite3
from pathlib import Path

from flask import Flask, Response, current_app, jsonify, request, send_file


KNOWN_COMMANDS = {
    "autoLogin",
    "autoReg",
    "buldle",
    "gcode",
    "im",
    "login",
    "pay",
    "reg",
    "regc",
    "show",
}

LOCAL_DEFAULT_BAG_CAPACITY = 100
# Local cap for bag expansion consumables (背包扩展卡). Not a recovered rule.
LOCAL_MAX_BAG_CAPACITY = 200
# Local-only pet slot rules. The original server capacities are unknown, so these
# are explicit local defaults, not recovered rules.
LOCAL_DEFAULT_PET_CAPACITY = 30
LOCAL_MAX_PET_CAPACITY = 90
LOCAL_PET_CAPACITY_STEP = 9
# Local-only starter pack. Icons p1001 and p2019 both exist in the bundled pet
# SWFs (pet2000.swf / pet4000.swf), so the client can render them without #1065.
# 2019 is five stars so the client's lock-confirmation branch (star >= 5) is reachable.
LOCAL_STARTER_PETS = (
    {"pet_id": 1001, "icon": 1001, "star": 3, "pro": 1},
    {"pet_id": 2019, "icon": 2019, "star": 5, "pro": 1},
)
LOCAL_STARTER_PET_IDS = {pet["pet_id"] for pet in LOCAL_STARTER_PETS}
# Local evolution chains and requirements. The client only displays these values;
# the original server's evolution table is not recoverable, so this is a local rule.
# Each entry maps the current config id to the next form. Levels below are local.
LOCAL_PET_EVOLUTION = {
    1001: {"id": 1002, "icon": 1002, "star": 3, "pro": 1, "need_lv": 5},
    1002: {"id": 1003, "icon": 1003, "star": 3, "pro": 1, "need_lv": 10},
    2019: {"id": 2020, "icon": 2020, "star": 5, "pro": 1, "need_lv": 5},
    2020: {"id": 2021, "icon": 2021, "star": 5, "pro": 1, "need_lv": 10},
}
# Local-only starter equipment so the equipment detail screen (39) is reachable.
# 烈焰之剑 = equip.txt id 20001 (iconId 20001, team 3, slot type 1, one star).
# Its class name p20001 exists in the bundled skin.swf, and pic.txt[id=20001] gives
# the name the client looks up. Stats below copy the bundled equip.txt row.
LOCAL_STARTER_EQUIPMENT = (
    {
        "item_id": 20001,
        "icon": 20001,
        "item_type": 1,
        "use_type": 1,
        "level": 1,
        "star": 1,
        "pro": 0,
        "hp": 0,
        "speed": 0,
        "phy_att": 20,
        "mag_att": 20,
        "phy_def": 0,
        "mag_def": 0,
    },
)
# Local-only prop catalogue: the effect type (`type` in prop.txt), the bag
# interaction mode (`useType`) and the effect amount (`value`) for every prop the
# local server can hand out. BagListUI routes by `type` (its row field `t`) and
# shows the item clickable only when `useType` is non-zero, so both must be real.
# Values copy the bundled prop.txt rows.
LOCAL_PROP_CATALOG = {
    10007: {"type": 7, "use_type": 1, "value": 20},      # 体力饮料: 恢复20点狩猎行动值
    10002: {"type": 5, "use_type": 2, "value": 1330000},  # 宠物水果: 宠物经验+133万
    10014: {"type": 14, "use_type": 1, "value": 3},       # 背包扩展卡: 背包+3
    10022: {"type": 16, "use_type": 1, "value": 10000},   # 一袋银币: 银币+10000
    10023: {"type": 17, "use_type": 1, "value": 10000},   # 一袋水晶: 水晶+10000
}
# Local-only shop stock. The original server's shop table is not recoverable, so
# these rows are explicit local defaults. `shop_type` 1 = 金币商店, 2 = 银币商店,
# 4 = 神秘商店. `price_type` 1 = money, 2 = point, 3 = crystal, 4 = goods trade.
# Only props whose effect USE_GOODS implements are stocked (see LOCAL_PROP_CATALOG).
LOCAL_SHOP_GOODS = (
    {"item_id": 10007, "team": 1, "shop_type": 1, "price_type": 1, "price": 80, "icon": 10007, "sort": 1},
    {"item_id": 10002, "team": 1, "shop_type": 1, "price_type": 1, "price": 360, "icon": 10002, "sort": 2},
    {"item_id": 10014, "team": 1, "shop_type": 1, "price_type": 1, "price": 200, "icon": 10014, "sort": 3},
    # 一袋银币 is normally loot, not shop stock; price 500 point is a local default.
    {"item_id": 10022, "team": 1, "shop_type": 2, "price_type": 2, "price": 500, "icon": 10022, "sort": 1},
)
# Local levelling rule for pet exp items: the original curve is not recoverable.
# Every LOCAL_PET_EXP_PER_LEVEL exp raises the pet one level (up to the cap); the
# remainder is kept in pets.exp. Evolution gates then read the new level.
LOCAL_PET_EXP_PER_LEVEL = 1000000
LOCAL_MAX_PET_LEVEL = 99
# EquipInfoUI hides the sell button when the detail's `money` field is positive
# (EquipInfoUI.as:191). Selling (68/69) is not implemented yet, so this local value
# keeps the unsupported button hidden. The original meaning of `money` is unknown.
LOCAL_EQUIP_SELL_HIDDEN_MONEY = 1


def _remote_address_allowed(remote_addr: str | None, networks: list[str]) -> bool:
    if remote_addr is None:
        return False

    try:
        address = ipaddress.ip_address(remote_addr)
        return any(address in ipaddress.ip_network(network) for network in networks)
    except ValueError:
        return False


def _log_request_metadata() -> None:
    fields = sorted(set(request.args.keys()) | set(request.form.keys()))
    command = request.args.get("m") or request.form.get("m")
    if command not in KNOWN_COMMANDS:
        command = "unknown"

    current_app.logger.info(
        "request source=%s method=%s path=%s command=%s fields=%s",
        request.remote_addr,
        request.method,
        request.path,
        command,
        ",".join(fields),
    )


def _request_value(name: str, default: str = "") -> str:
    return request.values.get(name, default)


def _protocol_response(command_id: int, payload: dict) -> Response:
    body = f"{command_id}\t{json.dumps(payload, separators=(',', ':'), ensure_ascii=False)}"
    return Response(body, status=200, mimetype="text/plain; charset=utf-8")


def _connect_database(database_path: Path) -> sqlite3.Connection:
    database = Path(database_path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    return connection


def _initialize_database(database_path: Path) -> None:
    with _connect_database(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT NOT NULL UNIQUE,
                nick TEXT NOT NULL UNIQUE,
                sex INTEGER NOT NULL,
                lv INTEGER NOT NULL DEFAULT 1,
                img TEXT NOT NULL,
                money INTEGER NOT NULL DEFAULT 0,
                point INTEGER NOT NULL DEFAULT 0,
                crystal INTEGER NOT NULL DEFAULT 0,
                ht_ap INTEGER NOT NULL DEFAULT 20,
                max_ht_ap INTEGER NOT NULL DEFAULT 20,
                arena_ap INTEGER NOT NULL DEFAULT 5,
                max_arena_ap INTEGER NOT NULL DEFAULT 5,
                pet_capacity INTEGER NOT NULL DEFAULT 30
            )
            """
        )
        player_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(players)")
        }
        if "account_id" not in player_columns:
            connection.execute("ALTER TABLE players ADD COLUMN account_id INTEGER")
        if "pet_capacity" not in player_columns:
            connection.execute(
                "ALTER TABLE players ADD COLUMN pet_capacity INTEGER NOT NULL DEFAULT 30"
            )
        if "bag_capacity" not in player_columns:
            connection.execute(
                f"ALTER TABLE players ADD COLUMN bag_capacity INTEGER NOT NULL DEFAULT {LOCAL_DEFAULT_BAG_CAPACITY}"
            )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                item_id INTEGER NOT NULL,
                team INTEGER NOT NULL CHECK (team IN (1, 2, 3)),
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                icon INTEGER,
                item_type INTEGER NOT NULL DEFAULT 0,
                use_type INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                star INTEGER NOT NULL DEFAULT 1,
                pro INTEGER NOT NULL DEFAULT 0,
                hp INTEGER NOT NULL DEFAULT 0,
                speed INTEGER NOT NULL DEFAULT 0,
                phy_att INTEGER NOT NULL DEFAULT 0,
                mag_att INTEGER NOT NULL DEFAULT 0,
                phy_def INTEGER NOT NULL DEFAULT 0,
                mag_def INTEGER NOT NULL DEFAULT 0,
                equipped INTEGER NOT NULL DEFAULT 0,
                UNIQUE (player_id, item_id)
            )
            """
        )
        inventory_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(inventory)")
        }
        for column, ddl in (
            ("icon", "ALTER TABLE inventory ADD COLUMN icon INTEGER"),
            ("item_type", "ALTER TABLE inventory ADD COLUMN item_type INTEGER NOT NULL DEFAULT 0"),
            ("use_type", "ALTER TABLE inventory ADD COLUMN use_type INTEGER NOT NULL DEFAULT 0"),
            ("level", "ALTER TABLE inventory ADD COLUMN level INTEGER NOT NULL DEFAULT 1"),
            ("star", "ALTER TABLE inventory ADD COLUMN star INTEGER NOT NULL DEFAULT 1"),
            ("pro", "ALTER TABLE inventory ADD COLUMN pro INTEGER NOT NULL DEFAULT 0"),
            ("hp", "ALTER TABLE inventory ADD COLUMN hp INTEGER NOT NULL DEFAULT 0"),
            ("speed", "ALTER TABLE inventory ADD COLUMN speed INTEGER NOT NULL DEFAULT 0"),
            ("phy_att", "ALTER TABLE inventory ADD COLUMN phy_att INTEGER NOT NULL DEFAULT 0"),
            ("mag_att", "ALTER TABLE inventory ADD COLUMN mag_att INTEGER NOT NULL DEFAULT 0"),
            ("phy_def", "ALTER TABLE inventory ADD COLUMN phy_def INTEGER NOT NULL DEFAULT 0"),
            ("mag_def", "ALTER TABLE inventory ADD COLUMN mag_def INTEGER NOT NULL DEFAULT 0"),
            ("equipped", "ALTER TABLE inventory ADD COLUMN equipped INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in inventory_columns:
                connection.execute(ddl)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS shop_goods (
                item_id INTEGER NOT NULL,
                team INTEGER NOT NULL,
                shop_type INTEGER NOT NULL,
                price_type INTEGER NOT NULL,
                price INTEGER NOT NULL CHECK (price >= 0),
                icon INTEGER NOT NULL,
                sort INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (item_id, team)
            )
            """
        )
        # The shop table is a local default, not player data, so it is rewritten
        # from LOCAL_SHOP_GOODS on every start. That keeps removed goods from
        # lingering in older saves (purchases go to `inventory`, not here).
        connection.execute("DELETE FROM shop_goods")
        for goods in LOCAL_SHOP_GOODS:
            connection.execute(
                """
                INSERT INTO shop_goods (
                    item_id, team, shop_type, price_type, price, icon, sort
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    goods["item_id"],
                    goods["team"],
                    goods["shop_type"],
                    goods["price_type"],
                    goods["price"],
                    goods["icon"],
                    goods["sort"],
                ),
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                pet_id INTEGER NOT NULL,
                name TEXT,
                lv INTEGER NOT NULL DEFAULT 1,
                star INTEGER NOT NULL DEFAULT 1,
                pro INTEGER NOT NULL DEFAULT 0,
                icon INTEGER NOT NULL,
                battle_state INTEGER NOT NULL DEFAULT 0,
                is_locked INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        pet_columns = {row[1] for row in connection.execute("PRAGMA table_info(pets)")}
        if "exp" not in pet_columns:
            connection.execute(
                "ALTER TABLE pets ADD COLUMN exp INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_pets_player ON pets (player_id, id)"
        )
        # Older local saves stored props with item_type/use_type 0, which makes
        # BagListUI render them grey and non-clickable. Rewrite the known ones.
        for item_id, prop in LOCAL_PROP_CATALOG.items():
            connection.execute(
                """
                UPDATE inventory SET item_type = ?, use_type = ?
                WHERE item_id = ? AND team IN (1, 2)
                """,
                (prop["type"], prop["use_type"], item_id),
            )


def _password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)


def _valid_account_credentials(username: str, password: str) -> bool:
    return (
        4 <= len(username) <= 16
        and username.isascii()
        and username.isalnum()
        and 6 <= len(password) <= 16
        and password.isascii()
        and password.isalnum()
    )


def _register_account(database_path: Path) -> Response:
    username = _request_value("acct").strip()
    password = _request_value("pwd")
    if not _valid_account_credentials(username, password):
        return Response("-1:0", status=200, mimetype="text/plain; charset=utf-8")

    salt = secrets.token_bytes(16)
    with _connect_database(database_path) as connection:
        try:
            connection.execute(
                "INSERT INTO accounts (username, password_salt, password_hash) VALUES (?, ?, ?)",
                (username, salt, _password_hash(password, salt)),
            )
        except sqlite3.IntegrityError:
            return Response("-1:0", status=200, mimetype="text/plain; charset=utf-8")
    return _protocol_response(4097, {"value": "ok"})


def _find_authenticated_account(connection: sqlite3.Connection, username: str, password: str):
    account = connection.execute(
        "SELECT id, password_salt, password_hash FROM accounts WHERE username = ?",
        (username,),
    ).fetchone()
    if account is None:
        return None
    candidate = _password_hash(password, account["password_salt"])
    if not hmac.compare_digest(candidate, account["password_hash"]):
        return None
    return account


def _login_account(database_path: Path) -> Response:
    username = _request_value("acct").strip()
    password = _request_value("pwd")
    if not _valid_account_credentials(username, password):
        return Response("-1:0", status=200, mimetype="text/plain; charset=utf-8")

    with _connect_database(database_path) as connection:
        account = _find_authenticated_account(connection, username, password)
        if account is None:
            return Response("-1:0", status=200, mimetype="text/plain; charset=utf-8")
        player = connection.execute(
            "SELECT uid FROM players WHERE account_id = ? ORDER BY id LIMIT 1",
            (account["id"],),
        ).fetchone()
    if player is None:
        return _protocol_response(4096, {"value": "reg"})
    return _protocol_response(4096, {"value": player["uid"]})


def _auto_login_account(database_path: Path) -> Response:
    uid = _request_value("uid")
    password = _request_value("pwd")
    with _connect_database(database_path) as connection:
        account = connection.execute(
            """
            SELECT a.id, a.password_salt, a.password_hash
            FROM accounts a JOIN players p ON p.account_id = a.id
            WHERE p.uid = ?
            """,
            (uid,),
        ).fetchone()
        if account is None:
            return Response("-1:0", status=200, mimetype="text/plain; charset=utf-8")
        candidate = _password_hash(password, account["password_salt"])
        if not hmac.compare_digest(candidate, account["password_hash"]):
            return Response("-1:0", status=200, mimetype="text/plain; charset=utf-8")
    return _protocol_response(4100, {"value": uid})


def _insert_starter_pets(connection: sqlite3.Connection, player_id: int) -> int:
    """Insert the local starter pack; returns how many pets were added."""
    added = 0
    for pet in LOCAL_STARTER_PETS:
        existing = connection.execute(
            "SELECT 1 FROM pets WHERE player_id = ? AND pet_id = ?",
            (player_id, pet["pet_id"]),
        ).fetchone()
        if existing is not None:
            continue
        connection.execute(
            """
            INSERT INTO pets (player_id, pet_id, lv, star, pro, icon)
            VALUES (?, ?, 1, ?, ?, ?)
            """,
            (player_id, pet["pet_id"], pet["star"], pet["pro"], pet["icon"]),
        )
        added += 1
    return added


def _insert_starter_equipment(connection: sqlite3.Connection, player_id: int) -> int:
    """Insert the local starter equipment; returns how many rows were added."""
    added = 0
    for item in LOCAL_STARTER_EQUIPMENT:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO inventory (
                player_id, item_id, team, quantity, icon, item_type, use_type,
                level, star, pro, hp, speed, phy_att, mag_att, phy_def, mag_def
            ) VALUES (?, ?, 3, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                player_id,
                item["item_id"],
                item["icon"],
                item["item_type"],
                item["use_type"],
                item["level"],
                item["star"],
                item["pro"],
                item["hp"],
                item["speed"],
                item["phy_att"],
                item["mag_att"],
                item["phy_def"],
                item["mag_def"],
            ),
        )
        added += cursor.rowcount
    return added


def grant_starter_equipment(database_path: Path) -> int:
    """Backfill the local starter equipment for every character that lacks it."""
    _initialize_database(database_path)
    seeded = 0
    with _connect_database(database_path) as connection:
        players = connection.execute("SELECT id FROM players ORDER BY id").fetchall()
        for player in players:
            if _insert_starter_equipment(connection, player["id"]):
                seeded += 1
    return seeded


def grant_starter_pets(database_path: Path) -> int:
    """Backfill the local starter pack for characters that only own starter pets.

    Idempotent. A character is skipped once any non-starter pet exists, so an
    evolved or otherwise progressed roster is never re-seeded. Used for saves
    created before a starter pet was added and by the local maintenance script.
    """
    _initialize_database(database_path)
    seeded = 0
    with _connect_database(database_path) as connection:
        players = connection.execute("SELECT id FROM players ORDER BY id").fetchall()
        for player in players:
            pet_ids = {
                row["pet_id"]
                for row in connection.execute(
                    "SELECT pet_id FROM pets WHERE player_id = ?", (player["id"],)
                )
            }
            if not pet_ids <= LOCAL_STARTER_PET_IDS:
                continue
            added = _insert_starter_pets(connection, player["id"])
            if added:
                seeded += 1
    return seeded


def _register_account_player(database_path: Path) -> Response:
    username = _request_value("acct").strip()
    password = _request_value("pwd")
    nick = _request_value("nick").strip()
    if not _valid_account_credentials(username, password):
        return Response("-1:0", status=200, mimetype="text/plain; charset=utf-8")
    if not 1 <= len(nick) <= 8 or not nick.isascii() or not nick.isalnum():
        return Response("-1:0", status=200, mimetype="text/plain; charset=utf-8")
    try:
        sex = int(_request_value("sex", "1"))
    except ValueError:
        return Response("-1:0", status=200, mimetype="text/plain; charset=utf-8")
    if sex not in (0, 1):
        return Response("-1:0", status=200, mimetype="text/plain; charset=utf-8")

    skin = "100001_100002_100003" if sex == 1 else "100001_100004_100005"
    with _connect_database(database_path) as connection:
        account = _find_authenticated_account(connection, username, password)
        if account is None:
            return Response("-1:0", status=200, mimetype="text/plain; charset=utf-8")
        player = connection.execute(
            "SELECT uid, nick FROM players WHERE account_id = ? ORDER BY id LIMIT 1",
            (account["id"],),
        ).fetchone()
        if player is not None and player["nick"] != nick:
            return Response("-1:0", status=200, mimetype="text/plain; charset=utf-8")
        if player is None:
            taken = connection.execute(
                "SELECT 1 FROM players WHERE nick = ?", (nick,)
            ).fetchone()
            if taken is not None:
                return Response("-1:0", status=200, mimetype="text/plain; charset=utf-8")
            uid = f"local-{secrets.token_hex(12)}"
            cursor = connection.execute(
                "INSERT INTO players (uid, nick, sex, img, account_id) VALUES (?, ?, ?, ?, ?)",
                (uid, nick, sex, skin, account["id"]),
            )
            _insert_starter_pets(connection, cursor.lastrowid)
            _insert_starter_equipment(connection, cursor.lastrowid)
            player = {"uid": uid}
    return _protocol_response(4098, {"value": player["uid"]})


def _auto_register_player(database_path: Path) -> Response:
    nick = _request_value("nick").strip()
    if not 1 <= len(nick) <= 8 or not nick.isascii() or not nick.isalnum():
        return _protocol_response(4099, {"error": "invalid_nickname"})
    try:
        sex = int(_request_value("sex", "1"))
    except ValueError:
        return _protocol_response(4099, {"error": "invalid_sex"})
    if sex not in (0, 1):
        return _protocol_response(4099, {"error": "invalid_sex"})

    skin = "100001_100002_100003" if sex == 1 else "100001_100004_100005"
    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT uid FROM players WHERE nick = ?", (nick,)
        ).fetchone()
        if player is None:
            uid = f"local-{secrets.token_hex(12)}"
            cursor = connection.execute(
                "INSERT INTO players (uid, nick, sex, img) VALUES (?, ?, ?, ?)",
                (uid, nick, sex, skin),
            )
            _insert_starter_pets(connection, cursor.lastrowid)
            _insert_starter_equipment(connection, cursor.lastrowid)
            player = {"uid": uid}
    return _protocol_response(4099, {"value": player["uid"]})


def _player_info(database_path: Path, command_id: int = 510) -> Response:
    uid = _request_value("uid")
    with _connect_database(database_path) as connection:
        player = connection.execute(
            """
            SELECT id, nick AS name, lv, img, money, point, crystal,
                   ht_ap, max_ht_ap, arena_ap, max_arena_ap
            FROM players WHERE uid = ?
            """,
            (uid,),
        ).fetchone()
    if player is None:
        return Response("-1:0", status=404, mimetype="text/plain; charset=utf-8")
    payload = dict(player)
    if command_id == 2:
        # Local starting state; guild and arena systems are not restored yet.
        # HomeUI resolves job through the bundled upRole configuration.
        payload.update(job=1, guild_name="", guild_position=0, arena_rank=0)
    return _protocol_response(command_id, payload)


def _player_inventory(database_path: Path) -> Response:
    uid = _request_value("uid")
    try:
        item_type = int(_request_value("ttype", "1"))
        page = int(_request_value("p", "1"))
        page_size = int(_request_value("n", "9"))
    except ValueError:
        return Response("-1:0", status=400, mimetype="text/plain; charset=utf-8")
    if item_type not in (1, 2, 3) or page < 1 or not 1 <= page_size <= 9:
        return Response("-1:0", status=400, mimetype="text/plain; charset=utf-8")

    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id, bag_capacity FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return Response("-1:0", status=404, mimetype="text/plain; charset=utf-8")
        rows = connection.execute(
            """
            SELECT id AS "index", item_id AS id, team, quantity AS num, icon,
                   item_type AS type, use_type, level
            FROM inventory WHERE player_id = ? AND team = ?
            ORDER BY id LIMIT ? OFFSET ?
            """,
            (player["id"], item_type, page_size, (page - 1) * page_size),
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) FROM inventory WHERE player_id = ? AND team = ?",
            (player["id"], item_type),
        ).fetchone()[0]

    goods = []
    for row in rows:
        item = dict(row)
        # BagListUI hands this value straight to IconItem, which resolves the
        # class name verbatim, so the list needs "p<iconId>" (unlike detail 39).
        item["icon"] = f"p{item['icon']}" if item["icon"] else ""
        if item["team"] == 3:
            # BagListUI.onMouseUpItem switches on this `type` (row `t`) and its
            # cases 1/2/9/24/25/27 are pet-item actions; equipment must fall to
            # `default`, where ttype==3 sends EQUIP_INFO (39). The original
            # server's value for equipment rows is not recoverable.
            item["type"] = 0
        goods.append(item)
    return _protocol_response(
        22,
        {
            # Local interpretation: report the slots used in the viewed tab.
            "bag_size": count,
            "max_bag_size": player["bag_capacity"],
            "goods_list": goods,
        },
    )


def _player_equipment_detail(database_path: Path) -> Response:
    uid = _request_value("uid")
    try:
        item_index = int(_request_value("index", ""))
    except ValueError:
        return _pet_error(100, status=400)

    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103, status=404)
        row = connection.execute(
            """
            SELECT id AS "index", item_id AS id, icon, level, star, pro,
                   hp, speed, phy_att, mag_att, phy_def, mag_def
            FROM inventory WHERE id = ? AND player_id = ? AND team = 3
            """,
            (item_index, player["id"]),
        ).fetchone()
    if row is None:
        return _pet_error(400)

    # EquipInfoUI looks up pic[id].name locally and instantiates "p"+icon, and has
    # no try/catch around that lookup, so only real equip ids/icons may be returned.
    return _protocol_response(
        39,
        {
            # Positive value hides the unsupported sell button (see constant note).
            "money": LOCAL_EQUIP_SELL_HIDDEN_MONEY,
            "index": row["index"],
            "id": row["id"],
            "icon": row["icon"],
            "level": row["level"],
            "star": row["star"],
            "pro": row["pro"],
            "hp": row["hp"],
            "phy_att": row["phy_att"],
            "mag_att": row["mag_att"],
            "phy_def": row["phy_def"],
            "mag_def": row["mag_def"],
            "speed": row["speed"],
        },
    )


_SHOP_PRICE_COLUMN = {1: "money", 2: "point", 3: "crystal"}


def _shop_list(database_path: Path) -> Response:
    uid = _request_value("uid")
    try:
        shop_type = int(_request_value("ttype", "1"))
        page = int(_request_value("p", "1"))
        page_size = int(_request_value("n", "9"))
    except ValueError:
        return _pet_error(100)
    if shop_type not in (1, 2, 4) or page < 1 or not 1 <= page_size <= 9:
        return _pet_error(100)

    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT 1 FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        rows = connection.execute(
            """
            SELECT item_id, team, price_type, price, icon
            FROM shop_goods WHERE shop_type = ?
            ORDER BY sort, item_id LIMIT ? OFFSET ?
            """,
            (shop_type, page_size, (page - 1) * page_size),
        ).fetchall()

    goods = []
    for row in rows:
        item = {
            "team": row["team"],
            "id": row["item_id"],
            # ShopListUI passes this to PropItem, which prefixes "p" itself.
            "icon": row["icon"],
            "type": row["price_type"],
        }
        if row["price_type"] in _SHOP_PRICE_COLUMN:
            item[_SHOP_PRICE_COLUMN[row["price_type"]]] = row["price"]
        else:
            item["need_goods_id"] = 0
            item["need_goods_num"] = row["price"]
        goods.append(item)
    return _protocol_response(27, {"shop_type": shop_type, "list": goods})


def _shop_goods_detail(database_path: Path) -> Response:
    uid = _request_value("uid")
    try:
        goods_id = int(_request_value("gid", ""))
        price_type = int(_request_value("ttype", ""))
        loc = int(_request_value("loc", ""))
    except ValueError:
        return _pet_error(100)

    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id, money, point, crystal FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        row = connection.execute(
            """
            SELECT item_id, team, shop_type, price_type, price, icon
            FROM shop_goods WHERE item_id = ? AND team = ?
            """,
            (goods_id, loc),
        ).fetchone()
    if row is None or row["price_type"] != price_type:
        return _pet_error(400)

    goods = {"id": row["item_id"], "icon": row["icon"]}
    need = {"need_money": 0, "need_point": 0, "need_crystal": 0}
    if row["price_type"] in _SHOP_PRICE_COLUMN:
        need[f"need_{_SHOP_PRICE_COLUMN[row['price_type']]}"] = row["price"]
    return _protocol_response(
        28,
        {
            "shop_type": row["shop_type"],
            "loc": row["team"],
            "goods": goods,
            "goods_ext": {
                "own_money": player["money"],
                "own_point": player["point"],
                "own_crystal": player["crystal"],
                "need_goods_id": 0,
                "own_need_goods_num": 0,
                **need,
            },
        },
    )


def _shop_buy(database_path: Path) -> Response:
    uid = _request_value("uid")
    try:
        goods_id = int(_request_value("gid", ""))
        count = int(_request_value("count", "1"))
        price_type = int(_request_value("ttype", ""))
        loc = int(_request_value("loc", ""))
    except ValueError:
        return _pet_error(100)
    if not 1 <= count <= 99:
        return _pet_error(206)

    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        row = connection.execute(
            """
            SELECT item_id, team, price_type, price, icon
            FROM shop_goods WHERE item_id = ? AND team = ?
            """,
            (goods_id, loc),
        ).fetchone()
        if row is None or row["price_type"] != price_type:
            return _pet_error(400)
        column = _SHOP_PRICE_COLUMN.get(row["price_type"])
        if column is None:
            # Goods-trade purchases need a barter flow that is not implemented.
            return _pet_error(100)
        total = row["price"] * count
        updated = connection.execute(
            f"""
            UPDATE players SET {column} = {column} - ?
            WHERE id = ? AND {column} >= ?
            """,
            (total, player["id"], total),
        )
        if updated.rowcount == 0:
            return _pet_error({1: 403, 2: 404, 3: 405}[row["price_type"]])
        prop = LOCAL_PROP_CATALOG.get(row["item_id"], {"type": 0, "use_type": 0})
        connection.execute(
            """
            INSERT INTO inventory (
                player_id, item_id, team, quantity, icon, item_type, use_type,
                level, star
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1)
            ON CONFLICT (player_id, item_id)
            DO UPDATE SET quantity = quantity + excluded.quantity
            """,
            (
                player["id"],
                row["item_id"],
                row["team"],
                count,
                row["icon"],
                prop["type"],
                prop["use_type"],
            ),
        )
    return _protocol_response(29, {"value": "ok"})


def _player_use_goods(database_path: Path) -> Response:
    """USE_GOODS (50) from the bag: `index` is the inventory row id, `index1` the
    selected pet id (0 when no target). Effects are driven by LOCAL_PROP_CATALOG,
    so only props the local server understands can be used."""
    uid = _request_value("uid")
    try:
        item_index = int(_request_value("index", ""))
        target = int(_request_value("index1", "0") or 0)
    except ValueError:
        return _pet_error(100)

    with _connect_database(database_path) as connection:
        player = connection.execute(
            """
            SELECT id, ht_ap, max_ht_ap, pet_capacity, bag_capacity
            FROM players WHERE uid = ?
            """,
            (uid,),
        ).fetchone()
        if player is None:
            return _pet_error(103)
        row = connection.execute(
            """
            SELECT id, item_id, team, quantity, item_type
            FROM inventory WHERE id = ? AND player_id = ?
            """,
            (item_index, player["id"]),
        ).fetchone()
        if row is None:
            return _pet_error(400)
        prop = LOCAL_PROP_CATALOG.get(row["item_id"])
        if prop is None or prop["type"] != row["item_type"] or row["team"] not in (1, 2):
            # Items this local server has no rule for stay in the bag untouched.
            return _pet_error(100)

        effect = prop["type"]
        amount = prop["value"]
        payload: dict[str, int] = {}
        if effect == 7:  # restore hunt action points
            if player["ht_ap"] >= player["max_ht_ap"]:
                return _pet_error(100)
            new_ap = min(player["max_ht_ap"], player["ht_ap"] + amount)
            connection.execute(
                "UPDATE players SET ht_ap = ? WHERE id = ?", (new_ap, player["id"])
            )
            payload = {"value": new_ap - player["ht_ap"], "ht_ap": new_ap}
        elif effect == 5:  # pet exp
            if target <= 0:
                return _pet_error(506)
            pet = connection.execute(
                "SELECT id, lv, exp FROM pets WHERE id = ? AND player_id = ?",
                (target, player["id"]),
            ).fetchone()
            if pet is None:
                return _pet_error(506)
            exp = pet["exp"] + amount
            lv = pet["lv"]
            while exp >= LOCAL_PET_EXP_PER_LEVEL and lv < LOCAL_MAX_PET_LEVEL:
                exp -= LOCAL_PET_EXP_PER_LEVEL
                lv += 1
            connection.execute(
                "UPDATE pets SET lv = ?, exp = ? WHERE id = ?",
                (lv, exp, pet["id"]),
            )
            payload = {"value": amount, "lv": lv, "exp": exp}
        elif effect == 14:  # bag capacity
            if player["bag_capacity"] >= LOCAL_MAX_BAG_CAPACITY:
                return _pet_error(204)
            new_capacity = min(
                LOCAL_MAX_BAG_CAPACITY, player["bag_capacity"] + amount
            )
            connection.execute(
                "UPDATE players SET bag_capacity = ? WHERE id = ?",
                (new_capacity, player["id"]),
            )
            payload = {
                "value": new_capacity - player["bag_capacity"],
                "max_bag_size": new_capacity,
            }
        elif effect in (16, 17):  # currency bags
            column = "point" if effect == 16 else "crystal"
            connection.execute(
                f"UPDATE players SET {column} = {column} + ? WHERE id = ?",
                (amount, player["id"]),
            )
            payload = {"value": amount}
        else:
            return _pet_error(100)

        if row["quantity"] > 1:
            connection.execute(
                "UPDATE inventory SET quantity = quantity - 1 WHERE id = ?",
                (row["id"],),
            )
        else:
            connection.execute("DELETE FROM inventory WHERE id = ?", (row["id"],))
        ht_ap = connection.execute(
            "SELECT ht_ap FROM players WHERE id = ?", (player["id"],)
        ).fetchone()["ht_ap"]
    payload["ht_ap"] = ht_ap
    return _protocol_response(50, payload)


def _pet_error(error_id: int, status: int = 200) -> Response:
    """Client-recognised protocol error (`-1:<error.txt key>`).

    HTTP 200 keeps Flash's URLLoader on the data path so the client shows the
    bundled error text instead of treating it as a network failure.
    """
    return Response(
        f"-1:{error_id}", status=status, mimetype="text/plain; charset=utf-8"
    )


def _pet_index_from_request() -> int | None:
    try:
        return int(_request_value("index", ""))
    except ValueError:
        return None


def _find_player_pet(
    connection: sqlite3.Connection, uid: str, pet_index: int
):
    player = connection.execute(
        "SELECT id, pet_capacity FROM players WHERE uid = ?", (uid,)
    ).fetchone()
    if player is None:
        return None, None
    row = connection.execute(
        """
        SELECT id AS "index", pet_id, icon, name, lv, star, pro, battle_state, is_locked
        FROM pets WHERE id = ? AND player_id = ?
        """,
        (pet_index, player["id"]),
    ).fetchone()
    return player, row


def _next_pet_payload(pet_id: int) -> dict | None:
    target = LOCAL_PET_EVOLUTION.get(pet_id)
    if target is None:
        return None
    return {
        "id": target["id"],
        "need_lv": target["need_lv"],
        "need_money": 0,
        "need_point": 0,
        "need_crystal": 0,
        "need_goods": [],
    }


def _pet_detail_payload(row) -> dict:
    payload = {
        "index": row["index"],
        "star": row["star"],
        "is_lockable": True,
        "is_locked": bool(row["is_locked"]),
        "icon": row["icon"],
        "id": row["pet_id"],
        "lv": row["lv"],
        "pro": row["pro"],
    }
    if row["name"] is not None:
        payload["name"] = row["name"]
    next_pet = _next_pet_payload(row["pet_id"])
    if next_pet is not None:
        payload["next_pet"] = next_pet
    return payload


def _player_pets(database_path: Path) -> Response:
    uid = _request_value("uid")
    try:
        page = int(_request_value("p", "1"))
        page_size = int(_request_value("n", "9"))
    except ValueError:
        return _pet_error(100, status=400)
    if page < 1 or not 1 <= page_size <= 9:
        return _pet_error(100, status=400)

    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id, pet_capacity FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103, status=404)
        rows = connection.execute(
            """
            SELECT pets.id AS "index", pet_id AS id, icon, name, lv, battle_state
            FROM pets WHERE player_id = ?
            ORDER BY pets.id LIMIT ? OFFSET ?
            """,
            (player["id"], page_size, (page - 1) * page_size),
        ).fetchall()
        total = connection.execute(
            "SELECT COUNT(*) FROM pets WHERE player_id = ?", (player["id"],)
        ).fetchone()[0]

    pets = []
    for row in rows:
        pet = dict(row)
        if pet["name"] is None:
            pet.pop("name")
        pets.append(pet)
    capacity = player["pet_capacity"]
    can_expand = capacity < LOCAL_MAX_PET_CAPACITY
    return _protocol_response(
        11,
        {
            "pet_num": total,
            "max_pet_num": capacity,
            # Local placeholders: capacity expansion is a free local action, so
            # the owned card count mirrors the requirement. No item is consumed.
            "add_pet_card_num": 1,
            "own_card_num": 1 if can_expand else 0,
            "pets": pets,
        },
    )


def _player_pet_detail(database_path: Path) -> Response:
    uid = _request_value("uid")
    pet_index = _pet_index_from_request()
    if pet_index is None:
        return _pet_error(100, status=400)

    with _connect_database(database_path) as connection:
        player, row = _find_player_pet(connection, uid, pet_index)
    if player is None:
        return _pet_error(103, status=404)
    if row is None:
        return _pet_error(506, status=404)
    return _protocol_response(12, _pet_detail_payload(row))


def _pet_change_name(database_path: Path) -> Response:
    uid = _request_value("uid")
    pet_index = _pet_index_from_request()
    if pet_index is None:
        return _pet_error(100)
    name = _request_value("pName").strip()
    # Client input allows up to 8 characters; error.txt 514 is the bundled text.
    if not 1 <= len(name) <= 8:
        return _pet_error(514)

    with _connect_database(database_path) as connection:
        player, row = _find_player_pet(connection, uid, pet_index)
        if player is None:
            return _pet_error(103)
        if row is None:
            return _pet_error(506)
        connection.execute(
            "UPDATE pets SET name = ? WHERE id = ? AND player_id = ?",
            (name, pet_index, player["id"]),
        )
    # Client ignores the payload for 18 and re-requests detail (12).
    return _protocol_response(18, {"value": "ok"})


def _pet_toggle_lock(database_path: Path) -> Response:
    uid = _request_value("uid")
    pet_index = _pet_index_from_request()
    if pet_index is None:
        return _pet_error(100)

    with _connect_database(database_path) as connection:
        player, row = _find_player_pet(connection, uid, pet_index)
        if player is None:
            return _pet_error(103)
        if row is None:
            return _pet_error(506)
        locked = 0 if row["is_locked"] else 1
        connection.execute(
            "UPDATE pets SET is_locked = ? WHERE id = ? AND player_id = ?",
            (locked, pet_index, player["id"]),
        )
    # The client compares value against the strings "true"/"false".
    return _protocol_response(55, {"value": "true" if locked else "false"})


def _pet_release(database_path: Path) -> Response:
    uid = _request_value("uid")
    pet_index = _pet_index_from_request()
    if pet_index is None:
        return _pet_error(100)

    with _connect_database(database_path) as connection:
        player, row = _find_player_pet(connection, uid, pet_index)
        if player is None:
            return _pet_error(103)
        if row is None:
            return _pet_error(506)
        if row["is_locked"]:
            return _pet_error(524)
        if row["battle_state"]:
            return _pet_error(517)
        connection.execute(
            "DELETE FROM pets WHERE id = ? AND player_id = ?",
            (pet_index, player["id"]),
        )
    # No free_goods_id: the client goes straight back and the list re-requests.
    return _protocol_response(15, {"value": "ok"})


def _pet_evolve(database_path: Path) -> Response:
    uid = _request_value("uid")
    pet_index = _pet_index_from_request()
    if pet_index is None:
        return _pet_error(100)

    with _connect_database(database_path) as connection:
        player, row = _find_player_pet(connection, uid, pet_index)
        if player is None:
            return _pet_error(103)
        if row is None:
            return _pet_error(506)
        if row["is_locked"]:
            return _pet_error(524)
        target = LOCAL_PET_EVOLUTION.get(row["pet_id"])
        if target is None:
            return _pet_error(504)
        if row["lv"] < target["need_lv"]:
            return _pet_error(505)
        connection.execute(
            """
            UPDATE pets SET pet_id = ?, icon = ?, star = ?, pro = ?
            WHERE id = ? AND player_id = ?
            """,
            (
                target["id"],
                target["icon"],
                target["star"],
                target["pro"],
                pet_index,
                player["id"],
            ),
        )
        updated = connection.execute(
            """
            SELECT id AS "index", pet_id, icon, name, lv, star, pro, battle_state, is_locked
            FROM pets WHERE id = ? AND player_id = ?
            """,
            (pet_index, player["id"]),
        ).fetchone()
    # Command 14 is handled by the client's detail branch: return the new detail.
    return _protocol_response(14, _pet_detail_payload(updated))


def _pet_expand_capacity(database_path: Path) -> Response:
    uid = _request_value("uid")
    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id, pet_capacity FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        if player["pet_capacity"] >= LOCAL_MAX_PET_CAPACITY:
            return _pet_error(204)
        capacity = min(
            player["pet_capacity"] + LOCAL_PET_CAPACITY_STEP,
            LOCAL_MAX_PET_CAPACITY,
        )
        connection.execute(
            "UPDATE players SET pet_capacity = ? WHERE id = ?",
            (capacity, player["id"]),
        )
    # Client re-requests the pet list (11) after this response.
    return _protocol_response(40, {"value": "ok"})


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        ALLOWED_NETWORKS=["127.0.0.0/8", "::1/128"],
        FIXTURE_DIR=Path(__file__).resolve().parent.parent / "fixtures",
        DATABASE=Path(app.instance_path) / "game.sqlite3",
    )
    if config:
        app.config.update(config)

    app.config["FIXTURE_DIR"] = Path(app.config["FIXTURE_DIR"])
    app.config["DATABASE"] = Path(app.config["DATABASE"])
    app.config["ALLOWED_NETWORKS"] = [
        str(ipaddress.ip_network(network, strict=False))
        for network in app.config["ALLOWED_NETWORKS"]
    ]
    _initialize_database(app.config["DATABASE"])

    @app.before_request
    def restrict_to_configured_networks():
        if not _remote_address_allowed(
            request.remote_addr, app.config["ALLOWED_NETWORKS"]
        ):
            current_app.logger.warning(
                "rejected request source=%s path=%s", request.remote_addr, request.path
            )
            return jsonify(error="source_network_not_allowed"), 403
        _log_request_metadata()
        return None

    @app.after_request
    def log_response_metadata(response):
        current_app.logger.info(
            "response source=%s method=%s path=%s status=%s bytes=%s",
            request.remote_addr,
            request.method,
            request.path,
            response.status_code,
            response.content_length or response.calculate_content_length(),
        )
        return response

    @app.get("/health")
    def health():
        return jsonify(mode="lan-prototype", status="ok")

    @app.get("/data/android/server.xml")
    @app.get("/data/android/<locale>/server.xml")
    @app.get("/server.xml")
    @app.get("/serverTest.xml")
    def server_list(locale: str | None = None):
        fixture_name = "serverTest.xml" if request.path.endswith("serverTest.xml") else "server.xml"
        if fixture_name == "serverTest.xml":
            fixture = app.config["FIXTURE_DIR"] / "serverTest.xml"
        else:
            fixture = app.config["FIXTURE_DIR"] / Path("data") / "android" / "server.xml"
        if not fixture.is_file():
            return jsonify(error="server_list_not_configured"), 503
        return send_file(fixture, mimetype="application/xml", conditional=True)

    @app.route("/flash.do", methods=["GET", "POST"])
    def game_api():
        command = _request_value("m")
        if command == "regc":
            return _register_account(current_app.config["DATABASE"])
        if command == "login":
            return _login_account(current_app.config["DATABASE"])
        if command == "autoLogin":
            return _auto_login_account(current_app.config["DATABASE"])
        if command == "reg":
            return _register_account_player(current_app.config["DATABASE"])
        if command == "autoReg":
            return _auto_register_player(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "510":
            return _player_info(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "2":
            return _player_info(current_app.config["DATABASE"], command_id=2)
        if command == "show" and _request_value("showId") == "22":
            return _player_inventory(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "39":
            return _player_equipment_detail(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "27":
            return _shop_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "28":
            return _shop_goods_detail(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "29":
            return _shop_buy(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "50":
            return _player_use_goods(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "11":
            return _player_pets(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "12":
            return _player_pet_detail(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "14":
            return _pet_evolve(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "15":
            return _pet_release(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "18":
            return _pet_change_name(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "40":
            return _pet_expand_capacity(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "55":
            return _pet_toggle_lock(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "511":
            return _protocol_response(511, {"list": []})
        return jsonify(error="protocol_not_implemented"), 501

    return app
