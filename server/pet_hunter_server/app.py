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
    10011: {"type": 5, "use_type": 2, "value": 1000000},  # 宠物饼干: 宠物经验道具
    10032: {"type": 23, "use_type": 0, "value": 0},       # 蓝色晶石: 材料
    10001: {"type": 1, "use_type": 2, "value": 0},       # 魔幻沐浴露: 洗练成长
    10009: {"type": 9, "use_type": 2, "value": 0},       # 小丑面具: 洗练性格
    10028: {"type": 2, "use_type": 2, "value": 0},       # 遗忘之锤: 遗忘技能
    10035: {"type": 25, "use_type": 2, "value": 0},      # 推磨钱袋: 增加世代
    10034: {"type": 24, "use_type": 2, "value": 0},      # 遗忘卡牌: 遗忘特性
    10505: {"type": 27, "use_type": 2, "value": 0},      # 转换水晶球: 转换资质
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
# Local sell prices for commands 68 (preview) and 69 (execute). The bundled
# configs carry `recyclePoint = 0` for every local item, so the original sell
# value is not recoverable; these defaults are half the item's reference price
# (equip 20001 has point=200, so it sells for 100 silver). Items not listed here
# cannot be sold and return the client's 物品不存在 error.
LOCAL_SELL_PRICES = {
    20001: 100,
    10007: 40,
    10002: 180,
    10014: 100,
    10022: 250,
}

# Local quest catalogue seeded into the `tasks` table. Every row below is a real
# `task.txt` entry (id, name, type, iconId, needLevel, questId, value, rewards are
# copied verbatim from client/air51-repack/src/data/zh-CN/config/task.txt), and
# only condition types the local server can evaluate honestly are offered:
#   0 = no condition, 7 = own a pet id, 8 = equip id, 11 = battle_state set,
#   20 = money threshold, 21 = silver threshold.
# Types that would require inventing facts (UI clicks, crafting, map completion,
# item-use history, monster kills, illustrations, friends, trading, account
# binding) are deliberately NOT seeded, so the client is never offered a task the
# server cannot honestly judge.
LOCAL_TASKS = (
    {"id": 1, "type": 0, "icon": 50001, "need_level": 0, "quest_id": 0,
     "value": "", "reward_money": 0, "reward_point": 200, "reward_crystal": 0,
     "reward_goods": ()},
    {"id": 6, "type": 8, "icon": 50001, "need_level": 0, "quest_id": 5,
     "value": "20001:20004", "reward_money": 0, "reward_point": 500,
     "reward_crystal": 0, "reward_goods": ()},
    {"id": 15, "type": 7, "icon": 50005, "need_level": 0, "quest_id": 14,
     "value": "1001", "reward_money": 0, "reward_point": 500, "reward_crystal": 0,
     "reward_goods": ()},
    {"id": 19, "type": 11, "icon": 50005, "need_level": 0, "quest_id": 18,
     "value": "0", "reward_money": 0, "reward_point": 0, "reward_crystal": 0,
     "reward_goods": ((10011, 3),)},
    {"id": 1012, "type": 21, "icon": 50005, "need_level": 1, "quest_id": 1011,
     "value": "2000", "reward_money": 0, "reward_point": 0, "reward_crystal": 0,
     "reward_goods": ((10014, 1),)},
    {"id": 1501, "type": 20, "icon": 50003, "need_level": 1, "quest_id": 1017,
     "value": "3000", "reward_money": 0, "reward_point": 0, "reward_crystal": 0,
     "reward_goods": ((10032, 60),)},
    {"id": 1502, "type": 20, "icon": 50003, "need_level": 1, "quest_id": 1501,
     "value": "5000", "reward_money": 0, "reward_point": 0, "reward_crystal": 0,
     "reward_goods": ((10032, 100),)},
)
# TaskTrackUI draws every tracked row with no paging (TaskTrackUI.as:45-47), so
# the tracker is capped (LOCAL DEFAULT) to keep the panel readable.
# The bundled MainUI places TaskTrackUI over the left-side home controls. The
# client has no scrolling in TaskTrackUI, and each row is 100 logical pixels
# tall; showing the full local catalogue obscures the friend/home buttons.
# LOCAL DEFAULT: expose one current task at a time.
LOCAL_TASK_TRACKER_LIMIT = 1
# Prop ids used as quest rewards; 10011/10014 are absent from LOCAL_PROP_CATALOG,
# so their use_type/item_type are declared here to keep rewards clickable.
LOCAL_FORGE_RECIPES = {
    32001: {"output": 20002, "money": 100, "point": 0, "crystal": 0, "goods": ((11010, 1),)},
}

LOCAL_FORGE_EQUIPMENT = {
    20002: {"icon": 20002, "level": 1, "star": 1, "pro": 0, "hp": 0, "speed": 0, "phy_att": 0, "mag_att": 0, "phy_def": 20, "mag_def": 20},
}

LOCAL_TASK_REWARD_PROPS = {
    10011: {"icon": 10011, "type": 5, "use_type": 2},
    10014: {"icon": 10014, "type": 14, "use_type": 1},
    10032: {"icon": 10032, "type": 23, "use_type": 0},
}


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

    show_id = request.args.get("showId") or request.form.get("showId")
    # hid/gid are gameplay ids, not credentials; logging them makes device
    # failures (e.g. a hunt cell sending the wrong map id) diagnosable.
    target = request.args.get("hid") or request.form.get("hid") or request.args.get("gid") or request.form.get("gid") or ""
    current_app.logger.info(
        "request source=%s method=%s path=%s command=%s showId=%s target=%s fields=%s",
        request.remote_addr,
        request.method,
        request.path,
        command,
        show_id or "",
        target,
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
    connection.execute("PRAGMA foreign_keys = ON")
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
        for column, ddl in (
            ("nature", "ALTER TABLE pets ADD COLUMN nature INTEGER NOT NULL DEFAULT 0"),
            ("skills", "ALTER TABLE pets ADD COLUMN skills TEXT NOT NULL DEFAULT ''"),
            ("gw_hp", "ALTER TABLE pets ADD COLUMN gw_hp INTEGER NOT NULL DEFAULT 0"),
            ("gw_speed", "ALTER TABLE pets ADD COLUMN gw_speed INTEGER NOT NULL DEFAULT 0"),
            ("gw_phy_att", "ALTER TABLE pets ADD COLUMN gw_phy_att INTEGER NOT NULL DEFAULT 0"),
            ("gw_mag_att", "ALTER TABLE pets ADD COLUMN gw_mag_att INTEGER NOT NULL DEFAULT 0"),
            ("gw_phy_def", "ALTER TABLE pets ADD COLUMN gw_phy_def INTEGER NOT NULL DEFAULT 0"),
            ("gw_mag_def", "ALTER TABLE pets ADD COLUMN gw_mag_def INTEGER NOT NULL DEFAULT 0"),
            ("gw_flush_count", "ALTER TABLE pets ADD COLUMN gw_flush_count INTEGER NOT NULL DEFAULT 0"),
            ("generation", "ALTER TABLE pets ADD COLUMN generation INTEGER NOT NULL DEFAULT 1"),
            ("buffs", "ALTER TABLE pets ADD COLUMN buffs TEXT NOT NULL DEFAULT ''"),
            ("pro_hp", "ALTER TABLE pets ADD COLUMN pro_hp INTEGER NOT NULL DEFAULT 0"),
            ("pro_speed", "ALTER TABLE pets ADD COLUMN pro_speed INTEGER NOT NULL DEFAULT 0"),
            ("pro_phy_att", "ALTER TABLE pets ADD COLUMN pro_phy_att INTEGER NOT NULL DEFAULT 0"),
            ("pro_mag_att", "ALTER TABLE pets ADD COLUMN pro_mag_att INTEGER NOT NULL DEFAULT 0"),
            ("pro_phy_def", "ALTER TABLE pets ADD COLUMN pro_phy_def INTEGER NOT NULL DEFAULT 0"),
            ("pro_mag_def", "ALTER TABLE pets ADD COLUMN pro_mag_def INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in pet_columns:
                connection.execute(ddl)
        for seeded_pet_id, seeded_skills in (
            (1001, "101:5101"), (1002, "101:102:5101:5102"),
            (1003, "101:102:103:5101:5102"), (2019, "103:5101"),
            (2020, "103:5101:5102"), (2021, "103:5101:5102"),
        ):
            connection.execute(
                "UPDATE pets SET skills = ? WHERE skills = '' AND pet_id = ?",
                (seeded_skills, seeded_pet_id),
            )
        # Reference table re-seeded at startup (no player data lives here), the
        # same way shop_goods is, so removed quests cannot linger in old saves.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY,
                type INTEGER NOT NULL,
                icon INTEGER NOT NULL,
                need_level INTEGER NOT NULL DEFAULT 0,
                quest_id INTEGER NOT NULL DEFAULT 0,
                value TEXT NOT NULL DEFAULT '',
                reward_money INTEGER NOT NULL DEFAULT 0,
                reward_point INTEGER NOT NULL DEFAULT 0,
                reward_crystal INTEGER NOT NULL DEFAULT 0,
                reward_goods TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS player_tasks (
                player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                task_id INTEGER NOT NULL,
                is_claimed INTEGER NOT NULL DEFAULT 0,
                claimed_at TEXT,
                PRIMARY KEY (player_id, task_id)
            )
            """
        )
        connection.execute("DELETE FROM tasks")
        for task in LOCAL_TASKS:
            connection.execute(
                """
                INSERT INTO tasks (
                    id, type, icon, need_level, quest_id, value,
                    reward_money, reward_point, reward_crystal, reward_goods
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task["id"],
                    task["type"],
                    task["icon"],
                    task["need_level"],
                    task["quest_id"],
                    task["value"],
                    task["reward_money"],
                    task["reward_point"],
                    task["reward_crystal"],
                    "".join(f"{gid}:{num}," for gid, num in task["reward_goods"]),
                ),
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
            INSERT INTO pets (player_id, pet_id, lv, star, pro, icon, skills)
            VALUES (?, ?, 1, ?, ?, ?, ?)
            """,
            (player_id, pet["pet_id"], pet["star"], pet["pro"], pet["icon"], "101:5101" if pet["pet_id"] == 1001 else "103:5101"),
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
            # EquipInfoUI shows the sell button only when `money` is 0
            # (EquipInfoUI.as:191); 68/69 are implemented, so the button is enabled.
            "money": 0,
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


def _inventory_row(
    connection: sqlite3.Connection, player_id: int, item_index: int
):
    return connection.execute(
        """
        SELECT id, item_id, team, quantity, item_type, icon
        FROM inventory WHERE id = ? AND player_id = ?
        """,
        (item_index, player_id),
    ).fetchone()


def _sale_price(item_id: int) -> int | None:
    return LOCAL_SELL_PRICES.get(item_id)


def _player_on_equip(database_path: Path) -> Response:
    """ON_EQUIP (37): wear the equipment row. The client leaves for the main map
    immediately and never reads the body, but the worn state must persist."""
    uid = _request_value("uid")
    try:
        item_index = int(_request_value("index", ""))
    except ValueError:
        return _pet_error(100)

    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        row = _inventory_row(connection, player["id"], item_index)
        if row is None or row["team"] != 3:
            return _pet_error(400)
        # One worn item per slot; equipment slot is the local `item_type` value.
        connection.execute(
            """
            UPDATE inventory SET equipped = 0
            WHERE player_id = ? AND team = 3 AND item_type = ? AND id <> ?
            """,
            (player["id"], row["item_type"], row["id"]),
        )
        connection.execute(
            "UPDATE inventory SET equipped = 1 WHERE id = ?", (row["id"],)
        )
    return _protocol_response(37, {"value": "ok"})


def _player_sale_info(database_path: Path) -> Response:
    """SALE_INFO (68): EquipInfoUI asks for the silver value before confirming."""
    uid = _request_value("uid")
    try:
        item_index = int(_request_value("index", ""))
        ttype = int(_request_value("ttype", "3"))
    except ValueError:
        return _pet_error(100)

    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        row = _inventory_row(connection, player["id"], item_index)
    if row is None or row["team"] != ttype:
        return _pet_error(400)
    price = _sale_price(row["item_id"])
    if price is None:
        return _pet_error(400)
    return _protocol_response(
        68, {"sold_price": price, "sold_goods_id": 0, "sold_goods_num": 0}
    )


def _player_sale_goods(database_path: Path) -> Response:
    """SALE_GOODS (69): consume `count` units and pay `price * count` silver."""
    uid = _request_value("uid")
    try:
        item_index = int(_request_value("index", ""))
        count = int(_request_value("count", "1"))
        ttype = int(_request_value("ttype", ""))
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
        row = _inventory_row(connection, player["id"], item_index)
        if row is None or row["team"] != ttype:
            return _pet_error(400)
        price = _sale_price(row["item_id"])
        if price is None:
            return _pet_error(400)
        if count > row["quantity"]:
            return _pet_error(206)
        connection.execute(
            "UPDATE players SET point = point + ? WHERE id = ?",
            (price * count, player["id"]),
        )
        if count == row["quantity"]:
            connection.execute("DELETE FROM inventory WHERE id = ?", (row["id"],))
        else:
            connection.execute(
                "UPDATE inventory SET quantity = quantity - ? WHERE id = ?",
                (count, row["id"]),
            )
    return _protocol_response(
        69,
        {
            "price_point": price * count,
            "price_goods_id": 0,
            "price_goods_num": 0,
        },
    )


# Map ids, names, worlds and icon ids come from the shipped client tables
# `client/air51-repack/src/data/zh-CN/config/exploreMap.txt` and `worldMap.txt`.
# Hunt/explore cost, AP and reward numbers below are LOCAL DEFAULTS.
LOCAL_HUNT_MAPS = {
    1: {"name": "樱花之岛1", "world": 1, "cost": 1, "monster": 1},
    2: {"name": "樱花之岛2", "world": 1, "cost": 1, "monster": 1},
    3: {"name": "樱花之岛3", "world": 1, "cost": 1, "monster": 2},
    101: {"name": "神龙之国1", "world": 2, "cost": 1, "monster": 2},
}
LOCAL_EXPLORE_MAPS = {
    1: {"world": 1, "cost_point": 0, "cost_money": 0, "disaster": 0, "is_catch": 0},
    2: {"world": 1, "cost_point": 0, "cost_money": 0, "disaster": 0, "is_catch": 0},
    101: {"world": 2, "cost_point": 0, "cost_money": 0, "disaster": 0, "is_catch": 0},
}


LOCAL_PICS = {1001: {"icon":1001,"reward":0},1002: {"icon":1002,"reward":0},20001: {"icon":20001,"reward":1}}


LOCAL_JOBS = {1: {"state":1}, 2: {"state":0}}


def _job_list(database_path: Path) -> Response:
    return _protocol_response(70,{"list":[{"job":k,"state":v["state"]} for k,v in LOCAL_JOBS.items()]})


def _job_detail(database_path: Path) -> Response:
    try: job=int(_request_value("gid",""))
    except ValueError:return _pet_error(100)
    if job not in LOCAL_JOBS:return _pet_error(400)
    return _protocol_response(71,{"job":job,"need_lv":1,"diff_lv":0,"nextRole":{"now_hp":0,"next_hp":0,"now_speed":0,"next_speed":0,"now_phy_att":0,"next_phy_att":0,"now_phy_def":0,"next_phy_def":0,"now_mag_att":0,"next_mag_att":0,"now_mag_def":0,"next_mag_def":0},"reward_goods":[]})


def _pic_list(database_path: Path) -> Response:
    try: ttype=int(_request_value("ttype","1")); page=int(_request_value("p","1")); size=int(_request_value("n","9"))
    except ValueError:return _pet_error(100)
    if not 1<=ttype<=4 or page<1:return _pet_error(100)
    ids=list(LOCAL_PICS); start=(page-1)*size
    pics=[[i,LOCAL_PICS[i]["icon"],LOCAL_PICS[i]["reward"]] for i in ids[start:start+size]]
    return _protocol_response(25,{"finish_rate":0,"pics":[{"index":x[0],"id":x[0],"icon":x[1],"is_reward":x[2]} for x in pics]})


def _pic_info(database_path: Path) -> Response:
    try: gid=int(_request_value("gid",""))
    except ValueError:return _pet_error(100)
    if gid not in LOCAL_PICS:return _pet_error(506)
    return _protocol_response(26,{"id":gid,"need_money":0,"is_reward":LOCAL_PICS[gid]["reward"],"pics":[{"id":gid,"is_reward":LOCAL_PICS[gid]["reward"]}]})


def _picstep_info(database_path: Path) -> Response:
    return _protocol_response(48,{"id":1,"own_num":0,"need_num":1,"reward_point":0,"reward_money":0,"reward_crystal":0,"reward_goods":[],"is_finish":0})


def _achievement_list(database_path: Path) -> Response:
    return _protocol_response(107,{"id":1,"need_money":0,"is_reward":0,"pics":[]})


def _guild_own(database_path: Path) -> Response:
    uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT nick,img FROM players WHERE uid=?",(uid,)).fetchone()
    if p is None:return _pet_error(103)
    return _protocol_response(86,{"guild_id":0,"leader_img":p["img"],"guild_name":"","position":0,"leader_name":"","mem_num":0})


def _guild_list(database_path: Path) -> Response:
    return _protocol_response(88,{"guilds":[]})


def _guild_members(database_path: Path) -> Response:
    return _protocol_response(91,{"list":[]})


def _guild_battle(database_path: Path) -> Response:
    return _protocol_response(94,{"is_battle_on":0,"battle_turn":0,"isReward":0,"start_time":0,"end_time":0,"total_honor":0,"battle_team":{"turn":{"1":[],"2":[],"3":[]}}})


def _friend_list(database_path: Path) -> Response:
    uid=_request_value("uid")
    try: page,size=int(_request_value("p","1")),int(_request_value("n","9"))
    except ValueError: return _pet_error(100)
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None:return _pet_error(103)
        rows=c.execute("SELECT uid,nick,lv,img FROM players WHERE id<>? ORDER BY id",(p["id"],)).fetchall()
    start=max(0,page-1)*size
    return _protocol_response(51,{"player_str_id":uid,"friend":[{"id":r["uid"],"state":0,"name":r["nick"],"img":r["img"]} for r in rows[start:start+size]]})


def _friend_detail(database_path: Path) -> Response:
    target=_request_value("gid"); uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,uid,nick,lv,img FROM players WHERE uid=?",(target,)).fetchone()
        if p is None:return _pet_error(103)
        pets=c.execute("SELECT id AS 'index',pet_id AS id,icon,name,lv FROM pets WHERE player_id=?",(p["id"],)).fetchall()
    return _protocol_response(52,{"show_type":0,"player":{"id":p["uid"],"name":p["nick"],"lv":p["lv"],"img":p["img"]},"pets":[dict(r) for r in pets]})


def _player_detail_social(database_path: Path) -> Response:
    return _social_detail_response(database_path, 3)


def _social_detail_response(database_path: Path, command_id: int) -> Response:
    target=_request_value("gid"); uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,uid,nick,lv,img FROM players WHERE uid=?",(target,)).fetchone()
        if p is None:return _pet_error(103)
        pets=c.execute("SELECT id AS 'index',pet_id AS id,icon,name,lv FROM pets WHERE player_id=?",(p["id"],)).fetchall()
    return _protocol_response(command_id,{"show_type":0,"player":{"id":p["uid"],"name":p["nick"],"lv":p["lv"],"img":p["img"]},"pets":[dict(r) for r in pets]})


def _hunter_list(database_path: Path) -> Response:
    uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,ht_ap,max_ht_ap FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
    return _protocol_response(4,{"player":{"hunt_ap":p["ht_ap"],"max_hunt_ap":p["max_ht_ap"]},"maps":[{"index":k,"code":k,"id":k,"name":v["name"],"world":v["world"],"rate":0,"pass":0,"star":0,"days":0,"is_allown_hunt":1} for k,v in LOCAL_HUNT_MAPS.items()]})


def _hunter_task(database_path: Path) -> Response:
    try: hid=int(_request_value("hid",""))
    except ValueError: return _pet_error(100)
    m=LOCAL_HUNT_MAPS.get(hid)
    if m is None: return _pet_error(400)
    uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,ht_ap,max_ht_ap FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
        pets=c.execute("SELECT id AS 'index',pet_id AS id,icon,name,lv FROM pets WHERE player_id=? AND battle_state=0",(p["id"],)).fetchall()
    return _protocol_response(5,{"id":hid,"hid":hid,"ht_ap":p["ht_ap"],"max_ht_ap":p["max_ht_ap"],"pets":[dict(r) for r in pets]})


def _hunter_fight(database_path: Path) -> Response:
    try: hid=int(_request_value("hid",""))
    except ValueError: return _pet_error(100)
    if hid not in LOCAL_HUNT_MAPS: return _pet_error(400)
    uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,ht_ap,max_ht_ap FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
        if p["ht_ap"] < 1: return _pet_error(100)
        c.execute("UPDATE players SET ht_ap=ht_ap-1 WHERE id=?",(p["id"],))
        ap=p["ht_ap"]-1
        rows=c.execute("SELECT id AS 'index',pet_id AS id,icon,name,lv FROM pets WHERE player_id=? AND battle_state=0 ORDER BY id LIMIT 1",(p["id"],)).fetchall()
    # LOCAL DEFAULT replay: one attacking pet from the save, one local monster row.
    if rows:
        r=rows[0]
        att={"team":1,"code":0,"is_pet":1,"index":r["index"],"id":r["id"],"name":r["name"] or "宠物","lv":r["lv"],"hp":100,"img":r["icon"]}
    else:
        att={"team":1,"code":0,"is_pet":0,"id":1001,"name":"猎人","lv":1,"hp":100,"img":1001}
    defense={"team":2,"code":0,"is_pet":0,"id":1001,"name":"烈焰怪","lv":1,"hp":50,"img":1001}
    record=[{"att":{"team":1,"code":0,"hp":100},"def":{"team":2,"code":0,"hp":0}}]
    return _protocol_response(6,{"is_win":1,"hunt_type":1,"map_id":hid,"monster_group":1,"att_list":[att],"def_list":[defense],"record":record,"ht_ap":ap,"value":"ok"})


def _hunter_catch(database_path: Path) -> Response:
    try: hid=int(_request_value("hid",""))
    except ValueError: return _pet_error(100)
    if hid not in LOCAL_HUNT_MAPS: return _pet_error(400)
    uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,pet_capacity FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
        count=c.execute("SELECT COUNT(*) FROM pets WHERE player_id=?",(p["id"],)).fetchone()[0]
        if count >= p["pet_capacity"]: return _pet_error(300)
    return _protocol_response(7,{"value":"ok","is_success":0,"hid":hid})


def _explore_start(database_path: Path) -> Response:
    try: gid=int(_request_value("gid",""))
    except ValueError: return _pet_error(100)
    if gid not in LOCAL_EXPLORE_MAPS: return _pet_error(400)
    uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,point,money FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
        m=LOCAL_EXPLORE_MAPS[gid]
        if p["point"] < m["cost_point"] or p["money"] < m["cost_money"]: return _pet_error(403)
        c.execute("UPDATE players SET point=point-?,money=money-? WHERE id=?",(m["cost_point"],m["cost_money"],p["id"]))
    return _protocol_response(103,{"value":"ok","event_type":0,"world":1,"world_id":gid,"is_finish":1,"explore_ap":0,"max_explore_ap":0,"now_discover_rate":0,"add_discover_rate":0,"need_discover_rate":0,"energy":0,"cost_energy":0,"add_energy":0,"supply":0,"cost_supply":0,"add_supply":0,"discover_days":0,"add_discover_days":0,"terrain":0})


def _explore_list(database_path: Path) -> Response:
    uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,point,money FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
    return _protocol_response(98,{"world":1,"explore_ap":0,"max_explore_ap":0,"list":[{"id":k,"world":v["world"],"name":"探索地图"} for k,v in LOCAL_EXPLORE_MAPS.items()]})


def _explore_detail(database_path: Path) -> Response:
    try: gid=int(_request_value("gid",""))
    except ValueError: return _pet_error(100)
    m=LOCAL_EXPLORE_MAPS.get(gid)
    if m is None: return _pet_error(400)
    uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT point,money FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
    return _protocol_response(99,{"id":gid,"world":m["world"],"cost_point":m["cost_point"],"own_point":p["point"],"cost_money":m["cost_money"],"own_money":p["money"],"disaster":m["disaster"],"is_catch":m["is_catch"]})


def _training_overview(database_path: Path) -> Response:
    return _protocol_response(504, {"list": [], "value": "ok"})


def _training_list(database_path: Path) -> Response:
    uid = _request_value("uid")
    try: page, size = int(_request_value("p", "1")), int(_request_value("n", "9"))
    except ValueError: return _pet_error(100)
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None: return _pet_error(103)
        rows = c.execute("SELECT id AS 'index',pet_id AS id,icon,name,lv FROM pets WHERE player_id=? AND battle_state=0 ORDER BY id", (player["id"],)).fetchall()
    start=max(0,page-1)*size
    return _protocol_response(505, {"list": [{"index":r["index"],"id":r["id"],"icon":r["icon"],"name":r["name"],"lv":r["lv"],"num":0,"energy":0} for r in rows[start:start+size]]})


def _training_detail(database_path: Path) -> Response:
    uid=_request_value("uid"); idx=_pet_index_from_request()
    if idx is None: return _pet_error(100)
    with _connect_database(database_path) as c:
        player,row=_find_player_pet(c,uid,idx)
        if player is None: return _pet_error(103)
        if row is None: return _pet_error(506)
        total=sum(row[k] for k in ("pro_hp","pro_speed","pro_phy_att","pro_mag_att","pro_phy_def","pro_mag_def"))
        payload={"index":idx,"id":row["pet_id"],"icon":row["icon"],"total_tp":total,"energy":0,"hp_tp":row["pro_hp"],"speed_tp":row["pro_speed"],"phy_att_tp":row["pro_phy_att"],"mag_att_tp":row["pro_mag_att"],"phy_def_tp":row["pro_phy_def"],"mag_def_tp":row["pro_mag_def"]}
    return _protocol_response(9,payload)


def _training_action(database_path: Path) -> Response:
    uid=_request_value("uid"); idx=_pet_index_from_request()
    try: ttype=int(_request_value("ttype",""))
    except ValueError: return _pet_error(100)
    if idx is None or ttype not in (1,2,3): return _pet_error(100)
    with _connect_database(database_path) as c:
        player,row=_find_player_pet(c,uid,idx)
        if player is None: return _pet_error(103)
        if row is None: return _pet_error(506)
        if row["is_locked"]: return _pet_error(100)
        target={1:"pro_hp",2:"pro_phy_att",3:"pro_mag_att"}[ttype]
        c.execute(f"UPDATE pets SET {target}={target}+1 WHERE id=?",(idx,))
        pet={"id":row["pet_id"],"icon":row["icon"],"name":row["name"]}
    return _protocol_response(10,{"pet":pet,"train_type":ttype,"reward_point":0,"reward_crystal":0,"add_hp_tp":1 if ttype==1 else 0,"add_phy_att_tp":1 if ttype==2 else 0,"add_mag_att_tp":1 if ttype==3 else 0,"add_speed_tp":0,"add_phy_def_tp":0,"add_mag_def_tp":0,"add_energy":0})


def _forge_refine(database_path: Path) -> Response:
    try: idx=int(_request_value("index",""))
    except ValueError: return _pet_error(100)
    uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,money,point,crystal FROM players WHERE uid=?",(uid,)).fetchone(); row=c.execute("SELECT * FROM inventory WHERE id=? AND player_id=? AND team=3",(idx,p["id"] if p else 0)).fetchone()
        if p is None: return _pet_error(103)
        if row is None: return _pet_error(400)
        next_level=row["level"]+1
        payload={"index":idx,"id":row["item_id"],"icon":row["icon"],"level":row["level"],"star":row["star"],"pro":row["pro"],"hp":row["hp"],"speed":row["speed"],"phy_att":row["phy_att"],"mag_att":row["mag_att"],"phy_def":row["phy_def"],"mag_def":row["mag_def"],"need_money":100,"own_money":p["money"],"need_point":0,"own_point":p["point"],"need_crystal":0,"own_crystal":p["crystal"],"need_goods":[],"next_refine":{"level":next_level,"hp":row["hp"],"speed":row["speed"],"phy_att":row["phy_att"]+5,"mag_att":row["mag_att"],"phy_def":row["phy_def"],"mag_def":row["mag_def"],"refine_add_skill_level":0}}
    return _protocol_response(35,payload)


def _forge_enchant(database_path: Path) -> Response:
    try: idx=int(_request_value("index",""))
    except ValueError: return _pet_error(100)
    uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,money,point,crystal FROM players WHERE uid=?",(uid,)).fetchone(); row=c.execute("SELECT * FROM inventory WHERE id=? AND player_id=? AND team=3",(idx,p["id"] if p else 0)).fetchone()
        if p is None: return _pet_error(103)
        if row is None: return _pet_error(400)
        if p["crystal"] < 10: return _pet_error(405)
        c.execute("UPDATE players SET crystal=crystal-10 WHERE id=?",(p["id"],)); c.execute("UPDATE inventory SET pro=pro+1 WHERE id=?",(idx,))
    return _protocol_response(36,{"index":idx,"id":row["item_id"],"icon":row["icon"],"level":row["level"],"star":row["star"],"pro":row["pro"]+1,"hp":row["hp"],"speed":row["speed"],"phy_att":row["phy_att"],"mag_att":row["mag_att"],"phy_def":row["phy_def"],"mag_def":row["mag_def"],"need_money":0,"own_money":p["money"],"need_point":0,"own_point":p["point"],"need_crystal":10,"own_crystal":p["crystal"]})


def _forge_list(database_path: Path) -> Response:
    try: ttype = int(_request_value("ttype", "1")); page = int(_request_value("p", "1")); size = int(_request_value("n", "9"))
    except ValueError: return _pet_error(100)
    if ttype != 1: return _protocol_response(32, {"list": []})
    rows = [{"index": rid, "id": rid, "icon": LOCAL_FORGE_EQUIPMENT.get(recipe["output"], {}).get("icon", recipe["output"]), "level": 1} for rid, recipe in LOCAL_FORGE_RECIPES.items()]
    start = max(0, page - 1) * size
    return _protocol_response(32, {"list": rows[start:start + max(0, size)]})


def _forge_detail(database_path: Path) -> Response:
    try: rid = int(_request_value("gid", ""))
    except ValueError: return _pet_error(100)
    recipe = LOCAL_FORGE_RECIPES.get(rid)
    if recipe is None: return _pet_error(400)
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id,money,point,crystal FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None: return _pet_error(103)
        output = LOCAL_FORGE_EQUIPMENT[recipe["output"]]
        needs = []
        for gid, num in recipe["goods"]:
            own = c.execute("SELECT COALESCE(SUM(quantity),0) FROM inventory WHERE player_id=? AND item_id=? AND team=2", (player["id"], gid)).fetchone()[0]
            needs.append({"id": gid, "need_num": num, "own_num": own})
    return _protocol_response(33, {"id": recipe["output"], "icon": output["icon"], "star": output["star"], "pro": output["pro"], "hp": output["hp"], "phy_att": output["phy_att"], "mag_att": output["mag_att"], "phy_def": output["phy_def"], "mag_def": output["mag_def"], "speed": output["speed"], "need_money": recipe["money"], "own_money": player["money"], "need_point": recipe["point"], "own_point": player["point"], "need_crystal": recipe["crystal"], "own_crystal": player["crystal"], "need_goods": needs})


def _forge_make(database_path: Path) -> Response:
    try: rid = int(_request_value("gid", ""))
    except ValueError: return _pet_error(100)
    recipe = LOCAL_FORGE_RECIPES.get(rid)
    if recipe is None: return _pet_error(400)
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id,money,point,crystal,bag_capacity FROM players WHERE uid=?", (_request_value("uid"),)).fetchone()
        if player is None: return _pet_error(103)
        if any(player[col] < recipe[col] for col in ("money","point","crystal")): return _pet_error(403)
        for gid, num in recipe["goods"]:
            row = c.execute("SELECT id,quantity FROM inventory WHERE player_id=? AND item_id=? AND team=2", (player["id"],gid)).fetchone()
            if row is None or row["quantity"] < num: return _pet_error(400)
        existing = c.execute("SELECT 1 FROM inventory WHERE player_id=? AND item_id=?", (player["id"],recipe["output"])).fetchone()
        if not existing and c.execute("SELECT COUNT(*) FROM inventory WHERE player_id=? AND team=3", (player["id"],)).fetchone()[0] >= player["bag_capacity"]: return _pet_error(300)
        for gid, num in recipe["goods"]:
            row = c.execute("SELECT id,quantity FROM inventory WHERE player_id=? AND item_id=? AND team=2", (player["id"], gid)).fetchone()
            if row["quantity"] == num:
                c.execute("DELETE FROM inventory WHERE id=?", (row["id"],))
            else:
                c.execute("UPDATE inventory SET quantity=quantity-? WHERE id=?", (num, row["id"]))
        c.execute("UPDATE players SET money=money-?,point=point-?,crystal=crystal-? WHERE id=?", (recipe["money"],recipe["point"],recipe["crystal"],player["id"]))
        o=LOCAL_FORGE_EQUIPMENT[recipe["output"]]; c.execute("INSERT INTO inventory (player_id,item_id,team,quantity,icon,item_type,use_type,level,star,pro,hp,speed,phy_att,mag_att,phy_def,mag_def) VALUES (?,?,3,1,?,0,1,?,?,?,?,?,?,?,?,?)", (player["id"],recipe["output"],o["icon"],o["level"],o["star"],o["pro"],o["hp"],o["speed"],o["phy_att"],o["mag_att"],o["phy_def"],o["mag_def"]))
        index=c.execute("SELECT id FROM inventory WHERE player_id=? AND item_id=?",(player["id"],recipe["output"])).fetchone()[0]
    return _protocol_response(34, {"index": index, "id": recipe["output"], "icon": o["icon"]})


def _reward_goods_ids(stored: str) -> list[tuple[int, int]]:
    goods = []
    for chunk in stored.split(","):
        if not chunk:
            continue
        gid, _, num = chunk.partition(":")
        if gid.isdigit() and num.isdigit():
            goods.append((int(gid), int(num)))
    return goods


def _task_prerequisite_met(
    connection: sqlite3.Connection, player_id: int, task: sqlite3.Row
) -> bool:
    if not task["quest_id"]:
        return True
    # LOCAL DEFAULT: prerequisites that are not in our honestly-checkable seed
    # are relaxed rather than fabricated into player_tasks.
    seeded_ids = {item["id"] for item in LOCAL_TASKS}
    if task["quest_id"] not in seeded_ids:
        return True
    return connection.execute(
        "SELECT 1 FROM player_tasks WHERE player_id = ? AND task_id = ? AND is_claimed = 1",
        (player_id, task["quest_id"]),
    ).fetchone() is not None


def _task_finished(
    connection: sqlite3.Connection, player_id: int, task: sqlite3.Row
) -> bool:
    """Evaluate a quest against state the local server actually owns.

    Only the six honestly-checkable condition types are seeded; anything else
    would require inventing progress, so it is never offered to the client.
    """
    value = (task["value"] or "").strip()
    if task["type"] == 0:
        return True
    if task["type"] == 7:  # own a pet of the given config id
        if not value.isdigit():
            return False
        return connection.execute(
            "SELECT 1 FROM pets WHERE player_id = ? AND pet_id = ?",
            (player_id, int(value)),
        ).fetchone() is not None
    if task["type"] == 8:  # equip an item from the id:id range
        try:
            low, _, high = value.partition(":")
            low_id, high_id = int(low), int(high or low)
        except ValueError:
            return False
        return connection.execute(
            """
            SELECT 1 FROM inventory
            WHERE player_id = ? AND team = 3 AND equipped = 1
              AND item_id BETWEEN ? AND ?
            """,
            (player_id, low_id, high_id),
        ).fetchone() is not None
    if task["type"] == 11:  # send a pet into battle
        return connection.execute(
            "SELECT 1 FROM pets WHERE player_id = ? AND battle_state != 0",
            (player_id,),
        ).fetchone() is not None
    if task["type"] in (20, 21):  # money / silver threshold
        column = "money" if task["type"] == 20 else "point"
        if not value.isdigit():
            return False
        return connection.execute(
            f"SELECT 1 FROM players WHERE id = ? AND {column} >= ?",
            (player_id, int(value)),
        ).fetchone() is not None
    return False


def _player_tasks(database_path: Path) -> Response:
    """TASK_LIST (511): the tracker rows read by TaskTrackUI.

    `is_finish` is recomputed from live state on every read and never stored,
    so the client can never be shown a stale or invented completion flag.
    """
    uid = _request_value("uid")
    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id, lv FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        tasks = connection.execute(
            "SELECT * FROM tasks WHERE need_level <= ? ORDER BY id",
            (player["lv"],),
        ).fetchall()
        claimed = {
            row["task_id"]
            for row in connection.execute(
                "SELECT task_id FROM player_tasks WHERE player_id = ? AND is_claimed = 1",
                (player["id"],),
            )
        }
        rows = [
            {
                "id": task["id"],
                "is_finish": 1 if _task_finished(connection, player["id"], task) else 0,
            }
            for task in tasks
            if task["id"] not in claimed
            and _task_prerequisite_met(connection, player["id"], task)
        ]
    return _protocol_response(511, {"list": rows[:LOCAL_TASK_TRACKER_LIMIT]})


def _task_condition(connection: sqlite3.Connection, player_id: int, task: sqlite3.Row) -> object:
    value = (task["value"] or "").strip()
    if task["type"] == 7:
        ids = [int(x) for x in value.split(":") if x.isdigit()]
        return {"list": [{"need_id": pet_id, "now_value": 1 if connection.execute("SELECT 1 FROM pets WHERE player_id = ? AND pet_id = ?", (player_id, pet_id)).fetchone() else 0, "need_value": 1} for pet_id in ids]}
    if task["type"] == 8:
        return {"now_value": 1 if _task_finished(connection, player_id, task) else 0, "need_value": 1}
    if task["type"] in (20, 21):
        column = "money" if task["type"] == 20 else "point"
        need = int(value or 0)
        row = connection.execute(f"SELECT {column} FROM players WHERE id = ?", (player_id,)).fetchone()
        return {"now_value": min(int(row[0] if row else 0), need), "need_value": need}
    return None


def _player_task_info(database_path: Path) -> Response:
    """TASK_INFO (46): one quest as TaskUI renders it.

    `ttype` is not trusted from the client; the task row is re-read by gid.
    """
    uid = _request_value("uid")
    raw = _request_value("gid", "").strip()
    if not raw.isdigit():
        return _pet_error(100)
    task_id = int(raw)

    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        task = connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if task is None:
            return _pet_error(211)
        if not _task_prerequisite_met(connection, player["id"], task):
            return _pet_error(211)
        finished = _task_finished(connection, player["id"], task)
        condition = _task_condition(connection, player["id"], task)
    return _protocol_response(
        46,
        {
            "id": task["id"],
            "type": task["type"],
            "icon": task["icon"],
            "condition": condition,
            "reward_money": task["reward_money"],
            "reward_point": task["reward_point"],
            "reward_crystal": task["reward_crystal"],
            "reward_goods": [
                {"id": gid, "num": num} for gid, num in _reward_goods_ids(task["reward_goods"])
            ],
            "is_finish": 1 if finished else 0,
        },
    )


def _player_task_reward(database_path: Path) -> Response:
    """TASK_REWARD (47): pay a finished quest exactly once.

    The client echoes `gid` and `ttype` from the 46 payload (TaskUI.as:186-189,
    463-465); `ttype` is ignored and the task is re-read by gid.
    """
    uid = _request_value("uid")
    raw = _request_value("gid", "").strip()
    if not raw.isdigit():
        return _pet_error(100)
    task_id = int(raw)

    with _connect_database(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        player = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        task = connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if task is None:
            return _pet_error(211)
        if not _task_prerequisite_met(connection, player["id"], task):
            return _pet_error(211)
        claimed = connection.execute(
            "SELECT is_claimed FROM player_tasks WHERE player_id = ? AND task_id = ?",
            (player["id"], task_id),
        ).fetchone()
        if claimed is not None and claimed["is_claimed"]:
            return _pet_error(211)
        if not _task_finished(connection, player["id"], task):
            # 107 is the client's bundled "finish the task first" text.
            return _pet_error(107)

        goods = _reward_goods_ids(task["reward_goods"])
        existing_item_ids = {
            row["item_id"] for row in connection.execute(
                "SELECT item_id FROM inventory WHERE player_id = ? AND team = 1",
                (player["id"],),
            )
        }
        new_rows = sum(1 for gid, _ in goods if gid not in existing_item_ids)
        capacity_row = connection.execute(
            "SELECT bag_capacity FROM players WHERE id = ?", (player["id"],)
        ).fetchone()
        used_rows = connection.execute(
            "SELECT COUNT(*) FROM inventory WHERE player_id = ? AND team = 1",
            (player["id"],),
        ).fetchone()[0]
        if used_rows + new_rows > int(capacity_row[0]):
            return _pet_error(300)
        if any(gid not in LOCAL_TASK_REWARD_PROPS for gid, _ in goods):
            return _pet_error(100)
        for gid, num in goods:
            prop = LOCAL_TASK_REWARD_PROPS[gid]
            connection.execute(
                """
                INSERT INTO inventory (
                    player_id, item_id, team, quantity, icon, item_type, use_type
                ) VALUES (?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT (player_id, item_id)
                DO UPDATE SET quantity = quantity + excluded.quantity
                """,
                (
                    player["id"],
                    gid,
                    num,
                    gid,
                    prop["type"] if prop else 0,
                    prop["use_type"] if prop else 0,
                ),
            )
        for column, amount in (
            ("money", task["reward_money"]),
            ("point", task["reward_point"]),
            ("crystal", task["reward_crystal"]),
        ):
            if amount:
                connection.execute(
                    f"UPDATE players SET {column} = {column} + ? WHERE id = ?",
                    (amount, player["id"]),
                )
        connection.execute(
            """
            INSERT INTO player_tasks (player_id, task_id, is_claimed, claimed_at)
            VALUES (?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT (player_id, task_id)
            DO UPDATE SET is_claimed = 1, claimed_at = CURRENT_TIMESTAMP
            """,
            (player["id"], task_id),
        )
    # TaskUI reads only `pic` from this body (TaskUI.as:425-433); an empty array
    # is falsy in AS3 so the client skips its reward animation instead of
    # rendering a half-initialised one.
    return _protocol_response(47, {"value": "ok", "pic": []})


def _function_flags(database_path: Path) -> Response:
    """REQUEST_FUNCTION_KEY (502).

    MainUI stores `GameUtil.fun_key = param2.value` (MainUI.as:80-83) and calls
    this right after every TASK_INFO (46) response, so a 501 here breaks the task
    screen on device. In this exported source `GameUtil.isFunKey()` returns true
    unconditionally (GameUtil.as:176-179) and `fun_key` has no reader, so the
    value is never consulted; "" is returned as a LOCAL DEFAULT.
    """
    return _protocol_response(502, {"value": ""})


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
        SELECT id AS "index", id, pet_id, icon, name, lv, star, pro, battle_state, is_locked,
               nature, skills, gw_hp, gw_speed, gw_phy_att, gw_mag_att, gw_phy_def, gw_mag_def, gw_flush_count,
               generation, buffs, pro_hp, pro_speed, pro_phy_att, pro_mag_att, pro_phy_def, pro_mag_def
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


def _player_pet_full_detail(database_path: Path) -> Response:
    uid = _request_value("uid")
    pet_index = _pet_index_from_request()
    if pet_index is None:
        return _pet_error(100)
    with _connect_database(database_path) as connection:
        player, row = _find_player_pet(connection, uid, pet_index)
        if player is None: return _pet_error(103)
        if row is None: return _pet_error(506)
        stats = LOCAL_PET_BASE_STATS.get(row["pet_id"], LOCAL_PET_BASE_STATS[1001])
        skills = _skill_rows(row["skills"])
        payload = {"index": row["index"], "id": row["pet_id"], "icon": row["icon"], "star": row["star"], "lv": row["lv"], "pro": row["pro"], "nature": row["nature"], "generation": row["generation"], "skills": skills, "buffs": [{"id": int(x)} for x in (row["buffs"] or "").split(":") if x.isdigit()], "hp": stats["hp"], "speed": stats["speed"], "phy_att": stats["phy_att"], "mag_att": stats["mag_att"], "phy_def": stats["phy_def"], "mag_def": stats["mag_def"], "hp_tp": 0, "speed_tp": 0, "phy_att_tp": 0, "mag_att_tp": 0, "phy_def_tp": 0, "mag_def_tp": 0, "hp_gw": row["gw_hp"], "speed_gw": row["gw_speed"], "phy_att_gw": row["gw_phy_att"], "mag_att_gw": row["gw_mag_att"], "phy_def_gw": row["gw_phy_def"], "mag_def_gw": row["gw_mag_def"], "total_gw": sum(row[k] for k in ("gw_hp","gw_speed","gw_phy_att","gw_mag_att","gw_phy_def","gw_mag_def")), "gw_rate": 1}
    return _protocol_response(13, payload)


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


LOCAL_PET_BASE_STATS = {
    1001: {"hp": 39, "speed": 65, "phy_att": 52, "mag_att": 60, "phy_def": 43, "mag_def": 50},
    2019: {"hp": 56, "speed": 76, "phy_att": 78, "mag_att": 45, "phy_def": 48, "mag_def": 43},
}


def _mutation_inventory(connection, player_id: int, item_id: int):
    return connection.execute(
        "SELECT id, quantity, item_type, team FROM inventory WHERE player_id = ? AND item_id = ?",
        (player_id, item_id),
    ).fetchone()


def _consume_mutation_item(connection, row):
    if row["quantity"] <= 1:
        connection.execute("DELETE FROM inventory WHERE id = ?", (row["id"],))
    else:
        connection.execute("UPDATE inventory SET quantity = quantity - 1 WHERE id = ?", (row["id"],))


def _mutation_pet(connection, uid: str, pet_index: int):
    player, pet = _find_player_pet(connection, uid, pet_index)
    return player, pet


def _pet_flush_grow(database_path: Path) -> Response:
    uid = _request_value("uid")
    pet_index = _pet_index_from_request()
    if pet_index is None:
        return _pet_error(100)
    with _connect_database(database_path) as connection:
        player, pet = _mutation_pet(connection, uid, pet_index)
        if player is None: return _pet_error(103)
        if pet is None: return _pet_error(506)
        if pet["is_locked"]: return _pet_error(100)
        item = _mutation_inventory(connection, player["id"], 10001)
        if item is None or item["quantity"] <= 0: return _pet_error(400)
        stats = LOCAL_PET_BASE_STATS.get(pet["pet_id"], LOCAL_PET_BASE_STATS[1001])
        values = [int(pet[k]) for k in ("gw_hp", "gw_speed", "gw_phy_att", "gw_mag_att", "gw_phy_def", "gw_mag_def")]
        total = sum(values)
        if total == 0: values[0] = 1; total = 1
        shift = (int(pet["gw_flush_count"]) + pet["id"]) % 6
        values = values[shift:] + values[:shift]
        columns = ("gw_hp", "gw_speed", "gw_phy_att", "gw_mag_att", "gw_phy_def", "gw_mag_def")
        connection.execute("UPDATE pets SET " + ", ".join(f"{c} = ?" for c in columns) + ", gw_flush_count = gw_flush_count + 1 WHERE id = ?", (*values, pet_index))
        _consume_mutation_item(connection, item)
        payload = {"value": "ok", "hp": stats["hp"], "hp_gw": values[0], "speed": stats["speed"], "speed_gw": values[1], "phy_att": stats["phy_att"], "phy_att_gw": values[2], "mag_att": stats["mag_att"], "mag_att_gw": values[3], "phy_def": stats["phy_def"], "phy_def_gw": values[4], "mag_def": stats["mag_def"], "mag_def_gw": values[5], "total_gw": total, "gw_rate": min(5, max(1, total // 20 + 1))}
    return _protocol_response(19, payload)


def _pet_flush_nature(database_path: Path) -> Response:
    uid = _request_value("uid"); pet_index = _pet_index_from_request()
    if pet_index is None: return _pet_error(100)
    with _connect_database(database_path) as connection:
        player, pet = _mutation_pet(connection, uid, pet_index)
        if player is None: return _pet_error(103)
        if pet is None: return _pet_error(506)
        if pet["is_locked"]: return _pet_error(100)
        item = _mutation_inventory(connection, player["id"], 10009)
        if item is None or item["quantity"] <= 0: return _pet_error(400)
        nature = (int(pet["nature"]) + 1) % 21
        connection.execute("UPDATE pets SET nature = ? WHERE id = ?", (nature, pet_index))
        _consume_mutation_item(connection, item)
        payload = {"id": pet["pet_id"], "name": pet["name"], "nature": nature, "value": "ok"}
    return _protocol_response(20, payload)


def _skill_rows(skill_text: str):
    result = []
    for token in (skill_text or "").split(":"):
        if not token.isdigit(): continue
        sid = int(token)
        dm_type = 2 if str(sid).startswith("51") else 1
        result.append({"id": sid, "dm_type": dm_type})
    return result


def _pet_forget_skill(database_path: Path) -> Response:
    uid = _request_value("uid"); pet_index = _pet_index_from_request()
    if pet_index is None: return _pet_error(100)
    with _connect_database(database_path) as connection:
        player, pet = _mutation_pet(connection, uid, pet_index)
        if player is None: return _pet_error(103)
        if pet is None: return _pet_error(506)
        if pet["is_locked"]: return _pet_error(524)
        skills = [x for x in (pet["skills"] or "").split(":") if x.isdigit()]
        if len(skills) <= 1: return _pet_error(515)
        item = _mutation_inventory(connection, player["id"], 10028)
        if item is None or item["quantity"] <= 0: return _pet_error(400)
        skills.pop(0)
        connection.execute("UPDATE pets SET skills = ? WHERE id = ?", (":".join(skills), pet_index))
        _consume_mutation_item(connection, item)
        payload = {"id": pet["pet_id"], "skills": _skill_rows(":".join(skills)), "value": "ok"}
    return _protocol_response(21, payload)


def _pet_add_generation(database_path: Path) -> Response:
    uid = _request_value("uid"); idx = _pet_index_from_request()
    if idx is None: return _pet_error(100)
    with _connect_database(database_path) as c:
        player, pet = _mutation_pet(c, uid, idx)
        if player is None: return _pet_error(103)
        if pet is None: return _pet_error(506)
        if pet["is_locked"]: return _pet_error(100)
        item = _mutation_inventory(c, player["id"], 10035)
        if item is None: return _pet_error(400)
        if pet["generation"] >= 9: return _pet_error(100)
        generation = pet["generation"] + 1
        c.execute("UPDATE pets SET generation=? WHERE id=?", (generation, idx)); _consume_mutation_item(c, item)
    return _protocol_response(84, {"id": pet["pet_id"], "generation": generation, "buffs": [], "value": "ok"})


def _pet_forget_buff(database_path: Path) -> Response:
    uid = _request_value("uid"); pet_idx = int(_request_value("index1", "0") or 0)
    with _connect_database(database_path) as c:
        player, pet = _mutation_pet(c, uid, pet_idx)
        if player is None: return _pet_error(103)
        if pet is None: return _pet_error(506)
        buffs = [x for x in (pet["buffs"] or "").split(":") if x.isdigit()]
        if len(buffs) < 2: return _pet_error(522)
        item = _mutation_inventory(c, player["id"], 10034)
        if item is None: return _pet_error(100)
        chosen = _request_value("index2", "")
        if chosen:
            if chosen not in buffs: return _pet_error(100)
            buffs.remove(chosen); c.execute("UPDATE pets SET buffs=? WHERE id=?", (":".join(buffs), pet_idx)); _consume_mutation_item(c, item)
            return _protocol_response(85, {"is_list": 0, "pet": {"id": pet["pet_id"], "skill_id": int(chosen)}, "value": "ok"})
        return _protocol_response(85, {"is_list": 1, "pet": {"id": pet["pet_id"], "buffs": [{"id": int(x)} for x in buffs]}})


def _pet_divide_pro(database_path: Path) -> Response:
    uid = _request_value("uid"); idx = _pet_index_from_request()
    if idx is None: return _pet_error(100)
    with _connect_database(database_path) as c:
        player, pet = _mutation_pet(c, uid, idx)
        if player is None: return _pet_error(103)
        if pet is None: return _pet_error(506)
        item = _mutation_inventory(c, player["id"], 10505)
        if item is None: return _pet_error(400)
        names = ("hp","speed","phy_att","mag_att","phy_def","mag_def")
        cols = tuple("pro_" + n for n in names)
        selected = _request_value("gid", "")
        vals = [int(pet[x]) for x in cols]
        if selected.isdigit() and 1 <= int(selected) <= 6:
            dest = int(selected)-1; source = max(range(6), key=lambda i: vals[i])
            if vals[source] <= 0: return _pet_error(523)
            amount = min(vals[source], 1000); vals[source] -= amount; vals[dest] += amount
            c.execute("UPDATE pets SET " + ",".join(x+"=?" for x in cols) + " WHERE id=?", (*vals, idx)); _consume_mutation_item(c, item)
            return _protocol_response(114, {"id": pet["pet_id"], "add_type": names[dest], "diff_type": names[source], "value": amount})
        payload = {"id": pet["pet_id"], "hp_tp": vals[0], "speed_tp": vals[1], "phy_att_tp": vals[2], "mag_att_tp": vals[3], "phy_def_tp": vals[4], "mag_def_tp": vals[5], "value": 0}
    return _protocol_response(114, payload)


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
        if command == "show" and _request_value("showId") == "37":
            return _player_on_equip(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "68":
            return _player_sale_info(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "69":
            return _player_sale_goods(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "103":
            return _explore_start(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "70":
            return _job_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "71":
            return _job_detail(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "25":
            return _pic_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "26":
            return _pic_info(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "48":
            return _picstep_info(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "107":
            return _achievement_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "86":
            return _guild_own(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "88":
            return _guild_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "91":
            return _guild_members(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "94":
            return _guild_battle(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "3":
            return _player_detail_social(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "51":
            return _friend_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "52":
            return _friend_detail(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "4":
            return _hunter_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "5":
            return _hunter_task(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "6":
            return _hunter_fight(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "7":
            return _hunter_catch(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "98":
            return _explore_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "99":
            return _explore_detail(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "504":
            return _training_overview(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "505":
            return _training_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "9":
            return _training_detail(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "10":
            return _training_action(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "35":
            return _forge_refine(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "36":
            return _forge_enchant(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "32":
            return _forge_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "33":
            return _forge_detail(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "34":
            return _forge_make(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "502":
            return _function_flags(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "46":
            return _player_task_info(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "47":
            return _player_task_reward(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "11":
            return _player_pets(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "12":
            return _player_pet_detail(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "13":
            return _player_pet_full_detail(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "14":
            return _pet_evolve(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "15":
            return _pet_release(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "18":
            return _pet_change_name(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "19":
            return _pet_flush_grow(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "20":
            return _pet_flush_nature(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "21":
            return _pet_forget_skill(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "84":
            return _pet_add_generation(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "85":
            return _pet_forget_buff(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "114":
            return _pet_divide_pro(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "40":
            return _pet_expand_capacity(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "55":
            return _pet_toggle_lock(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "511":
            return _player_tasks(current_app.config["DATABASE"])
        return jsonify(error="protocol_not_implemented"), 501

    return app
