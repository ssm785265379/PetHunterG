import ipaddress
import hashlib
import hmac
import json
import random
import secrets
import sqlite3
import time
from pathlib import Path

from flask import Flask, Response, current_app, jsonify, request, send_file

from . import config_tables


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

LOCAL_DEFAULT_BAG_CAPACITY = 1000
# Local cap for bag expansion consumables (背包扩展卡). Not a recovered rule.
LOCAL_MAX_BAG_CAPACITY = 2000
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
# Local levelling rule for pet exp: the original curve is not recoverable.
# LOCAL DEFAULT: a flat 1,000,000 exp per level. The bundled exp items carry real
# per-item values in this range (prop.txt's 宠物经验道具 grants 1,330,000), so the
# per-level cost stays in that scale and battle rewards below are scaled to match.
LOCAL_PET_EXP_PER_LEVEL = 1000000
LOCAL_MAX_PET_LEVEL = 99
# LOCAL DEFAULT: exp a single battle awards to each pet that took part, per
# monster level. 100,000 means a lv-1 hunt is ~10% of a level.
LOCAL_HUNT_EXP_PER_LEVEL = 100000
LOCAL_EXPLORE_EXP = 300000
# LOCAL DEFAULT: exploreMap.txt's passRewardPoint is 0 on most maps — their pass
# reward is an item or a picture-book entry — so a flat silver bonus is added on
# top to keep expeditions worth running.
LOCAL_EXPLORE_BONUS_POINT = 30
# LOCAL DEFAULT: silver awarded per monster level on a hunt win.
LOCAL_HUNT_POINT_REWARD = 50


def _parse_map_goods(raw: object) -> list[tuple[int, int, int, int]]:
    """Parse exploreMap's reward columns into (kind, id, num, icon) tuples.

    The shipped values are always four colon-separated numbers — `3:150011:150011:1`,
    `1:50001:50004:1`, `2:6002:6002:1` — which is `kind:id:icon:num`, NOT the
    `id:num,id:num` form task rewards use. Reading them with the pair parser
    silently produced item 3 x 150011. The icon field is genuinely independent:
    map 13 grants item 50001 drawn with icon 50004.
    """
    triples: list[tuple[int, int, int, int]] = []
    for chunk in str(raw or "").split(","):
        parts = [part.strip() for part in chunk.split(":")]
        if len(parts) == 4 and all(part.lstrip("-").isdigit() for part in parts):
            kind, gid, icon, num = (int(part) for part in parts)
            if gid > 0 and num > 0:
                triples.append((kind, gid, num, icon if icon > 0 else gid))
        elif len(parts) == 2 and all(part.isdigit() for part in parts):
            gid, num = int(parts[0]), int(parts[1])
            if gid > 0 and num > 0:
                triples.append((1, gid, num, gid))
    return triples


def _grant_goods(connection, player_id: int, goods) -> list[dict]:
    """Put reward items into the bag, stacking on the existing row.

    Each entry is (id, num) or (id, num, icon). exploreMap's reward columns carry
    an explicit icon in their third field (map 13 ships `1:50001:50004:1`, where
    the icon differs from the item id), so that is honoured when present.
    Unknown ids are skipped rather than inserted with a bogus icon, because the
    bag renders `p<icon>` without a guard.
    """
    props = config_tables._table("prop.txt")
    equips = config_tables._table("equip.txt")
    granted: list[dict] = []
    for entry in goods:
        gid, num = int(entry[0]), int(entry[1])
        icon_override = int(entry[2]) if len(entry) > 2 and entry[2] else None
        if gid <= 0 or num <= 0:
            continue
        if gid in equips:
            # kind-1 rewards may be equipment (map 13 ships item 50001, which is
            # in equip.txt, not prop.txt), so they need the equipment column set.
            record = equips[gid]
            def stat(key: str) -> int:
                raw = str(record.get(key, "") or "").strip()
                return int(raw) if raw.lstrip("-").isdigit() else 0
            icon = icon_override or stat("iconId") or gid
            for _ in range(num):
                # inventory is UNIQUE(player_id, item_id), so a repeat drop has to
                # stack onto the existing row instead of inserting a second copy
                # (a plain INSERT raised an IntegrityError and 500'd the page).
                connection.execute(
                    """INSERT INTO inventory (player_id, item_id, team, quantity, icon,
                                              item_type, use_type, level, star, pro,
                                              hp, speed, phy_att, mag_att, phy_def, mag_def)
                       VALUES (?,?,3,1,?,?,?,1,?,0,?,?,?,?,?,?)
                       ON CONFLICT (player_id, item_id)
                       DO UPDATE SET quantity = quantity + 1""",
                    (player_id, gid, icon, stat("type"), stat("useType"),
                     max(1, stat("star")), stat("hp"), stat("speed"),
                     stat("phyAtt"), stat("magAtt"), stat("phyDef"), stat("magDef")),
                )
            granted.append({"id": gid, "num": num})
            continue
        if gid not in props:
            continue
        record = props[gid]
        icon = icon_override or int(
            str(record.get("iconId", "") or gid).strip() or gid
        )
        connection.execute(
            """
            INSERT INTO inventory (player_id, item_id, team, quantity, icon, item_type, use_type)
            VALUES (?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT (player_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity
            """,
            (
                player_id,
                gid,
                num,
                icon,
                int(str(record.get("type", "0")).strip() or 0) if str(record.get("type", "0")).strip().isdigit() else 0,
                int(str(record.get("useType", "0")).strip() or 0) if str(record.get("useType", "0")).strip().isdigit() else 0,
            ),
        )
        granted.append({"id": gid, "num": num})
    return granted


def _grant_pet_exp(connection, pet_ids, amount: int) -> list[dict]:
    """Add battle exp to the pets that fought, returning their new levels.

    LOCAL DEFAULT: the original battle exp split is not recoverable, so every
    participating pet receives the full reward_exp.
    """
    if amount <= 0 or not pet_ids:
        return []
    granted: list[dict] = []
    for pet_id in pet_ids:
        row = connection.execute(
            "SELECT id, lv, exp FROM pets WHERE id = ?", (pet_id,)
        ).fetchone()
        if row is None:
            continue
        exp = (row["exp"] or 0) + amount
        lv = row["lv"] or 1
        while exp >= LOCAL_PET_EXP_PER_LEVEL and lv < LOCAL_MAX_PET_LEVEL:
            exp -= LOCAL_PET_EXP_PER_LEVEL
            lv += 1
        connection.execute("UPDATE pets SET lv = ?, exp = ? WHERE id = ?", (lv, exp, pet_id))
        granted.append({"index": pet_id, "lv": lv, "exp": exp, "add": amount})
    return granted
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
        if "cur_explore_map" not in player_columns:
            # ExploreMapInfoUI.as:204 sends EXPLORE_KEY(103) with no gid at all, so
            # the server has to remember the map the player opened with 99.
            connection.execute(
                "ALTER TABLE players ADD COLUMN cur_explore_map INTEGER"
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS explore_rented (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER NOT NULL,
                equip_id INTEGER NOT NULL,
                slot_type INTEGER NOT NULL DEFAULT 1,
                UNIQUE (player_id, equip_id)
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
            # Farm training (DevelopUI.as:133-134): 1=training 2=work 3=vacation,
            # mirrored straight off DevelopPetInfoUI's three ttype buttons.
            ("train_state", "ALTER TABLE pets ADD COLUMN train_state INTEGER NOT NULL DEFAULT 0"),
            ("train_type", "ALTER TABLE pets ADD COLUMN train_type INTEGER NOT NULL DEFAULT 0"),
            ("train_end", "ALTER TABLE pets ADD COLUMN train_end INTEGER NOT NULL DEFAULT 0"),
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


# equip.txt `type` -> the three slots RoleInfoUI prints (weapon/clothes/hat).
EQUIP_SLOT_FIELD = {1: "weapon", 2: "clothes", 3: "hat"}
ROLE_BASE_STATS = {
    # LOCAL DEFAULT: the original per-level base stats are not recoverable. These
    # are fixed starting values so equipment bonuses are visible in the panel.
    "hp": 100,
    "speed": 10,
    "phy_att": 10,
    "mag_att": 10,
    "phy_def": 10,
    "mag_def": 10,
}
# The bare character is THREE layers, not one. CreateUI.as:366-378 builds the
# default skin as "100001_100002_100003" (male) / "100001_100004_100005" (female):
# body + head + hair. Sending only 100001 drew a headless hunter, because no other
# layer supplies the head — skin.txt has no separate head id outside these triples.
LOCAL_BASE_SKIN_LAYERS = {
    1: (100001, 100002, 100003),
    2: (100001, 100004, 100005),
}


def _base_skin_layers(sex: int) -> tuple[int, ...]:
    return LOCAL_BASE_SKIN_LAYERS.get(int(sex or 1) or 1, LOCAL_BASE_SKIN_LAYERS[1])


def _worn_equipment(connection: sqlite3.Connection, player_id: int) -> dict[int, sqlite3.Row]:
    """Return {slot: inventory row} for the equipment the player is wearing."""
    rows = connection.execute(
        """
        SELECT id, item_id, item_type, icon, level, star, hp, speed,
               phy_att, mag_att, phy_def, mag_def
        FROM inventory WHERE player_id = ? AND team = 3 AND equipped = 1
        """,
        (player_id,),
    ).fetchall()
    worn: dict[int, sqlite3.Row] = {}
    for row in rows:
        # Prefer the config slot; fall back to the stored item_type.
        record = config_tables.equip_record(row["item_id"])
        slot = config_tables.equip_slot(record) if record else row["item_type"]
        if slot in EQUIP_SLOT_FIELD:
            worn[slot] = row
    return worn


def _role_skin_string(worn: dict[int, sqlite3.Row], sex: int = 1) -> str:
    """Build the ShowItem layer string.

    ShowItem.as:41-59 splits on "_", keeps only ids present in skin.txt and
    silently drops the rest, then :71 sorts by z DESCENDING and adds in that
    order — so the lowest z paints last, i.e. on top.

    The bare character needs its head and hair layers (CreateUI.as:366-378);
    omitting them is what produced a headless hunter in battle.
    """
    skin = config_tables.skin_table()
    layers: list[int] = [lid for lid in _base_skin_layers(sex) if lid in skin]
    for row in worn.values():
        record = config_tables.equip_record(row["item_id"])
        if not record:
            continue
        image_id = config_tables.equip_image_id(record)
        if image_id and image_id in skin and image_id not in layers:
            layers.append(image_id)
    # Match the client: highest z first (bottom), lowest z last (top).
    layers.sort(key=lambda lid: int(skin.get(lid, {}).get("z", "0") or 0), reverse=True)
    return "_".join(str(lid) for lid in layers)


def _role_stats(worn: dict[int, sqlite3.Row]) -> dict[str, int]:
    """Base stats plus the summed bonuses of every worn equipment."""
    totals = dict(ROLE_BASE_STATS)
    for row in worn.values():
        for key in totals:
            totals[key] += row[key] or 0
    return totals


def _equipped_slot_fields(worn: dict[int, sqlite3.Row]) -> dict[str, object]:
    """RoleInfoUI.as:170-172 reads weapon/clothes/hat plus a *_level each."""
    payload: dict[str, object] = {}
    for slot, field in EQUIP_SLOT_FIELD.items():
        row = worn.get(slot)
        if row is None:
            payload[field] = 0
            payload[f"{field}_level"] = 0
            continue
        record = config_tables.equip_record(row["item_id"])
        payload[field] = row["item_id"] if record else 0
        payload[f"{field}_level"] = row["level"] or 0
    return payload


def _player_info(database_path: Path, command_id: int = 510) -> Response:
    uid = _request_value("uid")
    with _connect_database(database_path) as connection:
        player = connection.execute(
            """
            SELECT id, nick AS name, lv, sex, img, money, point, crystal,
                   ht_ap, max_ht_ap, arena_ap, max_arena_ap
            FROM players WHERE uid = ?
            """,
            (uid,),
        ).fetchone()
        if player is None:
            return Response("-1:0", status=404, mimetype="text/plain; charset=utf-8")
        worn = _worn_equipment(connection, player["id"])
        pic_num = connection.execute(
            "SELECT COUNT(*) FROM pets WHERE player_id = ?", (player["id"],)
        ).fetchone()[0]
        payload = dict(player)
        # RoleInfoUI.as:137-186 and HomeUI.as:184-196 read every field below; the
        # six stats, the three equipment slots and `img` (the paper-doll layer
        # string) were all missing, which is why the panel printed `undefined`
        # and why worn gear never showed up on the character.
        payload.update(_role_stats(worn))
        payload["img"] = _role_skin_string(worn, player["sex"] if "sex" in player.keys() else 1)
        payload["pic_num"] = pic_num
        payload["skills"] = []
        payload["buffs"] = []
        payload.update(_equipped_slot_fields(worn))
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

    # EquipInfoUI.as:191-246 resolves the display name from pic.txt (which does
    # carry an entry for every equip.txt id, type=2) and instantiates
    # "p"+icon with no try/catch, so only real ids/icons may be returned.
    # skills/buffs come from equip.txt `skills` ("101:5101"); getSkill() reads
    # each entry's `id`.
    record = config_tables.equip_record(row["id"])
    skill_ids = config_tables.equip_skills(record) if record else []
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
            "skills": [{"id": sid} for sid in skill_ids],
            "buffs": [],
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
# Explore maps are no longer hardcoded: _explore_map_row() reads the shipped
# exploreMap.txt (worldId / terrain / star / name and the reward columns).


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
    # HomeUI.as:233-235 opens ROLE_INFO(3) for the player themselves and sends no
    # gid; FriendInfoUI.as:200 passes another player's uid. Fall back to `uid` so
    # the role page is reachable, and merge the paper doll / stats / equipment
    # slots that RoleInfoUI.as:150-172 prints without any null guards.
    target=_request_value("gid") or _request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,uid,nick,lv,sex FROM players WHERE uid=?",(target,)).fetchone()
        if p is None:return _pet_error(103)
        pets=c.execute("SELECT id AS 'index',pet_id AS id,icon,name,lv FROM pets WHERE player_id=?",(p["id"],)).fetchall()
        worn=_worn_equipment(c,p["id"])
        pic_num=c.execute("SELECT COUNT(*) FROM pets WHERE player_id=?",(p["id"],)).fetchone()[0]
        slots=_equipped_slot_fields(worn)
    # RoleInfoUI.as:144-172 reads name/lv/job/stats/weapon/... straight off
    # param2 (NOT param2.player), so the role page fields must be top level.
    # FriendInfoUI and KingFightInfoUI read param2.player for the same command,
    # so both shapes are shipped.
    player_fields={"id":p["uid"],"name":p["nick"],"lv":p["lv"],
                   "img":_role_skin_string(worn,p["sex"]),
                   "job":1,"guild_name":"0","guild_position":0,
                   "arena_rank":0,"pic_num":pic_num,
                   **_role_stats(worn), **slots,
                   "skills":[],"buffs":[]}
    payload={**player_fields,
             "show_type":0,"player":player_fields,
             "pets":[dict(r) for r in pets]}
    return _protocol_response(command_id,payload)


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
    return _protocol_response(5,{
        "id":hid,"hid":hid,"ht_ap":p["ht_ap"],"max_ht_ap":p["max_ht_ap"],
        # HunterTaskUI.as:100-101 disables the hunt/catch buttons when these
        # are not > 0, and :322 hides the plain button when rage_point hits 100.
        "isHunter":1 if p["ht_ap"] >= 1 else 0,
        "isCatch":1 if p["ht_ap"] >= 1 else 0,
        "rage_point":0,
        "pets":[_pet_list_entry(r) for r in pets],
    })


LOCAL_HUNT_WIN_RATE = 100
LOCAL_HUNT_MONSTER_COUNT = 1


def _monster_table() -> dict:
    return config_tables._table("monster.txt")


def _pick_monster(monster_id: int) -> dict[str, object] | None:
    """Real monster row from monster.txt.

    HunterResultUI.as:398 resolves the defender name from the *monster* table,
    and Pet.as:121 instantiates "p" + skin with no null guard, so `img` must
    be the monster's own iconId (a real MovieClip linkage), never a pet id.
    """
    record = _monster_table().get(monster_id)
    if record is None:
        return None
    icon = record.get("iconId", "").strip()
    if not icon.isdigit():
        return None
    def stat(column: str, fallback: int) -> int:
        raw = str(record.get(column, "")).strip()
        return int(raw) if raw.isdigit() else fallback
    return {
        "id": monster_id,
        "icon": int(icon),
        "name": record.get("name", ""),
        "lv": stat("level", 1),
        "hp": stat("hp", 50),
        "phy_att": stat("phyAtt", 10),
    }


def _monsters_for_map(hid: int) -> list[dict[str, object]]:
    """Monster group for a hunt map.

    The original per-map spawn table is not recoverable, so this walks
    monster.txt in id order — REAL data, but the grouping is a LOCAL DEFAULT.
    """
    table = _monster_table()
    ids = sorted(int(m) for m in table)
    picked = [_pick_monster(m) for m in ids[:LOCAL_HUNT_MONSTER_COUNT]]
    return [m for m in picked if m is not None]


def _battle_side(
    *,
    hunter_skin: str,
    hunter_name: str,
    hunter_lv: int,
    pet_rows,
    defenders,
) -> tuple[list[dict], list[dict]]:
    """Shared attacker/defender builder for HUNT(6), ARENA(24) and COPY(74).

    The three result screens were compared field by field
    (HunterResultUI.as:347-420, RingResultUI.as:283-357, AbyssResultUI.as:297-357):
    att_list/def_list/record use identical names, nesting, int() coercion points
    and the t=1/t=2 attacker/defender markers, and all three share one
    FightProcess state machine. Only the defender *name* fallback table differs
    (74 reads monster.txt, 24 reads pet.txt), which does not matter here because
    every name we send is already non-empty.

    Two client constraints fix the shape:
      * The hunter must lead att_list. HunterResultUI.as:354 and RingResultUI.as:290
        push att_list[0].img into ShowItem.items, which splits on "_" and resolves
        each id through skin.txt; a pet id there misses and the layer is silently
        dropped, which is what left the player headless.
      * def_list[i].img goes through Pet.as:121 getDefinition("p" + skin), so a
        defender carries a bare icon id and never an underscore-joined string.
    """
    lead = {
        "team": 1, "code": 0, "is_pet": 0, "id": 0, "name": hunter_name,
        "lv": hunter_lv, "pre_lv": hunter_lv, "hp": 100, "img": hunter_skin,
    }

    def attacker(row, code: int) -> dict:
        # LOCAL DEFAULT: hp doubles as the max hp the client draws with
        # (HunterResultUI.as:367-368), so it is derived from the pet's upgrades.
        power = (row["pro_hp"] or 0) + (row["pro_phy_att"] or 0) + (row["pro_mag_att"] or 0)
        return {
            "team": 1, "code": code, "is_pet": 1, "index": row["index"],
            "id": row["id"], "name": _pet_name(row["id"], row["name"]),
            "lv": row["lv"], "pre_lv": row["lv"], "hp": 100 + power, "img": row["icon"],
        }

    att_list = [lead] + [attacker(r, i + 1) for i, r in enumerate(pet_rows)][:2]
    def_list = [
        {"team": 2, "code": i, "is_pet": 0, "id": d["id"], "name": d["name"],
         "lv": d["lv"], "hp": d["hp"], "img": d["icon"]}
        for i, d in enumerate(defenders)
    ]
    return att_list, def_list


def _battle_record(att_list, def_list) -> list[dict]:
    """Replay steps, one per defender, all struck down.

    FightProcess.as:1066-1068 reads cur_hp/is_dead/is_revive with no guard and
    HunterResultUI.as:578 never starts the replay timer when record is empty, so
    every step carries all three on both sides.
    """
    steps = [
        {"att": {"team": 1, "code": 0, "cur_hp": att_list[0]["hp"],
                 "is_dead": False, "is_revive": False},
         "def": {"team": 2, "code": i, "cur_hp": 0,
                 "is_dead": True, "is_revive": False}}
        for i in range(len(def_list))
    ]
    if not steps:
        steps = [{"att": {"team": 1, "code": 0, "cur_hp": att_list[0]["hp"],
                          "is_dead": False, "is_revive": False},
                  "def": {"team": 2, "code": 0, "cur_hp": 0,
                          "is_dead": True, "is_revive": False}}]
    return steps


def _credit_battle_rewards(c: sqlite3.Connection, player_id: int, *, point: int, crystal: int) -> None:
    """Persist the reward figures a battle response just advertised.

    FightResultItem.as:285 and :296 render reward_point/reward_crystal from the
    response alone, so returning numbers without writing them made the settlement
    panel show a payout the player never received.
    """
    c.execute(
        "UPDATE players SET point=point+?, crystal=crystal+? WHERE id=?",
        (max(0, point), max(0, crystal), player_id),
    )


def _hunter_fight(database_path: Path) -> Response:
    try: hid=int(_request_value("hid",""))
    except ValueError: return _pet_error(100)
    if hid not in LOCAL_HUNT_MAPS: return _pet_error(400)
    uid=_request_value("uid")
    monsters=_monsters_for_map(hid)
    if not monsters: return _pet_error(400)
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,nick,lv,sex,ht_ap,max_ht_ap FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
        if p["ht_ap"] < 1: return _pet_error(100)
        c.execute("UPDATE players SET ht_ap=ht_ap-1 WHERE id=?",(p["id"],))
        ap=p["ht_ap"]-1
        worn=_worn_equipment(c,p["id"])
        rows=c.execute("SELECT id AS 'index',pet_id AS id,icon,name,lv,pro_hp,pro_speed,pro_phy_att,pro_mag_att,pro_phy_def,pro_mag_def FROM pets WHERE player_id=? AND battle_state=0 AND is_locked=0 ORDER BY id LIMIT 2",(p["id"],)).fetchall()
        # LOCAL DEFAULT rewards; the original hunt payout table is not recoverable.
        exp_reward=LOCAL_HUNT_EXP_PER_LEVEL*(sum(m["lv"] for m in monsters) or 1)
        point_reward=LOCAL_HUNT_POINT_REWARD*(sum(m["lv"] for m in monsters) or 1)
        _credit_battle_rewards(c,p["id"],point=point_reward,crystal=0)
        # The pets that actually fought gain the battle exp, so levelling (and the
        # evolution level gates) can advance through normal play.
        pet_exp=_grant_pet_exp(c,[r["index"] for r in rows],exp_reward)

    # LOCAL DEFAULT combat maths: the player's pets always win this one replay.
    att_list, def_list = _battle_side(
        hunter_skin=_role_skin_string(worn,p["sex"]),
        hunter_name=p["nick"] or "猎人",
        hunter_lv=p["lv"] or 1,
        pet_rows=rows,
        defenders=monsters,
    )
    record=_battle_record(att_list, def_list)
    pic=_pic_entries(monsters)
    return _protocol_response(6,{
        "is_win":1,"hunt_type":1,"map_id":hid,"monster_group":len(def_list)+3,
        "att_list":att_list,"def_list":def_list,"record":record,
        "ht_ap":ap,"max_ht_ap":p["max_ht_ap"],"ap_goods_index":0,
        "rage_point":0,"finish_rate":100,"pic":pic,
        "reward_exp":exp_reward,"reward_point":point_reward,"reward_crystal":0,
        "pet_exp":pet_exp,
        "reward_rate":1,"reward_goods":[],
        "value":"ok",
    })


def _pic_entries(monsters) -> list[dict]:
    """Picture-book entries for the monsters a hunt just defeated.

    GetPicItem.as:170-197 instantiates `p<icon>` and then resolves the display
    name through pic.txt -> pet.txt -> prop.txt -> exploreEquip.txt, dereferencing
    the record without a null guard. So both fields have to resolve for real:

    * `icon` must name an existing `p<icon>` symbol,
    * `id` must exist in one of those four tables.

    In the shipped data monster.txt's `iconId` is exactly that id (monster 1
    "原味波利" has iconId 5001, pet 5001 is the same creature and `p5001` lives in
    pet6000.swf), so it drives both fields.

    LOCAL DEFAULT: the per-pic rewards come from pic.txt when the entry exists;
    otherwise a level-scaled point payout is used because the original drop table
    is not recoverable.
    """
    pics = config_tables._table("pic.txt")
    pets = config_tables._table("pet.txt")
    entries: list[dict] = []
    seen: set[int] = set()
    for monster in monsters:
        try:
            pid = int(str(monster["icon"]).strip())
        except (KeyError, TypeError, ValueError):
            continue
        if pid in seen:
            continue
        seen.add(pid)
        record = pics.get(pid)
        if record is not None:
            point = int(str(record.get("rewardPoint", "0")).strip() or 0)
            crystal = int(str(record.get("rewardCrystal", "0")).strip() or 0)
            goods = [
                {"id": gid, "num": num}
                for gid, num in _reward_goods_ids(str(record.get("rewardGoods", "") or ""))
            ]
        else:
            level = int(monster["lv"] or 1) if "lv" in monster.keys() else 1
            point, crystal, goods = 10 * level, 0, []
        if pid not in pics and pid not in pets:
            continue  # name lookup would return null and throw in GetPicItem
        entries.append({
            "id": pid, "icon": pid,
            "reward_point": point, "reward_crystal": crystal, "reward_goods": goods,
        })
    return entries


def _catchable_pet(hid: int, ttype: int) -> tuple[int, dict] | None:
    """Which pet a catch attempt on this map can yield.

    HunterTaskUI and ExploreMapInfoUI both send CATCH_KEY; the latter passes
    ttype=2 and an explore map id in `hid`. The hunt maps name their monster in
    LOCAL_HUNT_MAPS, and monster.txt's `iconId` is the pet id that shares the
    same artwork (monster 1 原味波利 -> iconId 5001 -> pet.txt 5001, whose own
    iconId is also 5001, so `p5001` resolves for the catch screen).

    Returns (pet_id, monster_row) or None when nothing catchable lines up.
    """
    pets = config_tables._table("pet.txt")
    if ttype == 2:
        if _explore_map_row(hid) is None:
            return None
        # LOCAL DEFAULT: exploreMap.txt's catchPet column is 0 on the shipped
        # maps, so the first catchable monster is used instead.
        candidates = _monsters_for_map(1)
    else:
        entry = LOCAL_HUNT_MAPS.get(hid)
        if entry is None:
            return None
        monster = _pick_monster(int(entry["monster"]))
        candidates = [monster] if monster else []
    for monster in candidates:
        pid = int(str(monster.get("icon", "")).strip() or 0)
        if pid in pets:
            return pid, monster
    return None


def _hunter_catch(database_path: Path) -> Response:
    """7 (CATCH_KEY) — catch a pet.

    HunterCatchUI.as:128-150 reads only index/id/icon/pic and never looks at
    `is_success`, so the response must always describe a real, renderable pet:
    `id` is resolved through getConfigValue("pet", id, "name") and `icon` becomes
    `p<icon>` in Pet.as:121, both without null guards.

    LOCAL DEFAULT: the original per-map catch-rate table is not recoverable, so
    the attempt succeeds unless the roster is already at pet_capacity.
    """
    try: hid=int(_request_value("hid",""))
    except ValueError: return _pet_error(100)
    try: ttype=int(_request_value("ttype","1") or 1)
    except ValueError: ttype=1
    uid=_request_value("uid")
    target=_catchable_pet(hid,ttype)
    if target is None: return _pet_error(400)
    pet_id,monster=target
    pets=config_tables._table("pet.txt")
    record=pets[pet_id]
    try: level=max(1,int(str(monster.get("lv",1)).strip() or 1))
    except ValueError: level=1
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,pet_capacity FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
        count=c.execute("SELECT COUNT(*) FROM pets WHERE player_id=?",(p["id"],)).fetchone()[0]
        if count >= p["pet_capacity"]: return _pet_error(300)
        icon=str(record.get("iconId","") or pet_id).strip()
        star=str(record.get("star","1") or 1).strip()
        skills=str(record.get("skills","") or "").strip()
        nature_ids=sorted(config_tables._table("nature.txt").keys()) or [1]
        cursor=c.execute(
            """INSERT INTO pets (player_id, pet_id, lv, star, pro, icon, skills, generation, nature)
               VALUES (?,?,?,?,1,?,?,1,?)""",
            (p["id"],pet_id,level,int(star) if star.isdigit() else 1,
             int(icon) if icon.isdigit() else pet_id,
             skills or "101:5101",
             random.choice(nature_ids)),
        )
        index=cursor.lastrowid
    return _protocol_response(7,{
        "value":"ok","is_success":1,"hid":hid,
        "index":index,"id":pet_id,"icon":int(icon) if icon.isdigit() else pet_id,
        "name":_pet_name(pet_id), "lv":level,
        "pic":_pic_entries([monster]),
    })


def _explore_map_table() -> dict:
    """REAL rows from the shipped exploreMap.txt.

    Replaces the earlier hardcoded LOCAL_EXPLORE_MAPS placeholder: the client
    table carries name, worldId, terrain, star and the reward columns, and
    ExplorePveUI.as:385 resolves map_id through getConfigValue("exploreMap",
    map_id, "iconId"), so the ids have to be the real ones.
    """
    return config_tables._table("exploreMap.txt")


def _explore_map_row(gid: int) -> dict | None:
    table = _explore_map_table()
    record = table.get(gid)
    if record is None:
        return None
    world, terrain = 1, 1
    for key, target in (("worldId", "world"), ("terrain", "terrain")):
        raw = str(record.get(key, "")).strip()
        if raw.isdigit():
            if target == "world":
                world = int(raw)
            else:
                terrain = int(raw)
    def _int(key: str, default: int = 0) -> int:
        raw = str(record.get(key, "")).strip()
        return int(raw) if raw.lstrip("-").isdigit() else default

    return {
        "world": world,
        "terrain": terrain,
        # star is a "1500:1000:700:500" band string in the client table; the
        # explore list only passes it through, so keep it as shipped.
        "star": record.get("star", "1500:1000:700:500"),
        "name": record.get("name", ""),
        "need_discover_rate": _int("needDiscoverRate"),
        "pass_reward_point": _int("passRewardPoint"),
        "pass_reward_crystal": _int("passRewardCrystal"),
        "pass_reward_goods": str(record.get("passRewardGoods", "") or ""),
        "max_reward_point": _int("maxRewardPoint"),
        "max_reward_crystal": _int("maxRewardCrystal"),
        "max_reward_goods": str(record.get("maxRewardGoods", "") or ""),
        "is_catch": 1 if str(record.get("catchPet", "0")).strip() not in ("", "0") else 0,
        # LOCAL DEFAULT: no original expedition fee is recoverable, so the
        # shipped passRewardPoint/maxRewardPoint are shown but not charged.
        "cost_point": 0,
        "cost_money": 0,
        "max_days": 1,
        "disaster": 0,
    }


def _explore_map_world(gid: int) -> int:
    raw = str(_explore_map_table()[gid].get("worldId", "")).strip()
    return int(raw) if raw.isdigit() else 1


def _explore_event_type(gid: int) -> int:
    """Which expedition event the map rolls, read from exploreMap.txt.

    The shipped `events` column holds codes built as `map_id * 10 + event_type`,
    with `eventProbability` a parallel weight list:

        map 1  -> "11:12:13:14:15"       (types 1-5)
        map 4  -> "41:42:43:44:45"       (types 1-5)
        map 11 -> "111:112:...:117"      (types 1-7)

    GameUtil.getExploreEvent:482 switches on the event type (0,2,3,5,6,7,8,9) and
    ExploreUI.as:100 only opens the battle screen for type 1, so the type is the
    LAST digit — dividing by ten returned the map id and pushed every map onto the
    non-battle event page.

    LOCAL DEFAULT: always the first entry (a battle), because the original
    weighted roll and its persistent per-map state are not recoverable.
    """
    record = _explore_map_table().get(gid)
    if record is None:
        return 1
    first = str(record.get("events", "")).split(":")[0].strip()
    return int(first) % 10 if first.isdigit() else 1


# ExploreUI.as:182-190 does getDefinition("m" + horse) / ("m" + horse + "_2")
# with no null guard, so `horse` has to be a mount id that actually exists in
# mounts.swf. That SWF exports m100001..m100007 (and their _2 walk cycles),
# which are the exploreEquip.txt mount ids — NOT a 1..7 slot number.
LOCAL_EXPLORE_DEFAULT_HORSE = 100001


def _explore_horse(database_path: Path, player_id: int) -> int:
    """The mount drawn on the expedition page.

    Prefers a mount the player actually rented (slot_type=1 in exploreEquip.txt
    is the mount category); otherwise falls back to LOCAL DEFAULT 100001 (驴),
    which is the first mount in the shipped table and always has artwork.
    """
    try:
        rented = sorted(_rented_ids(database_path, player_id, 1))
    except Exception:  # noqa: BLE001 - a missing rental table must not break 103
        rented = []
    table = config_tables._table("exploreEquip.txt")
    for candidate in rented:
        if f"m{candidate}" in _MOUNT_SYMBOLS:
            return candidate
    if LOCAL_EXPLORE_DEFAULT_HORSE in table:
        return LOCAL_EXPLORE_DEFAULT_HORSE
    return LOCAL_EXPLORE_DEFAULT_HORSE


_MOUNT_SYMBOLS = {f"m10000{n}" for n in range(1, 8)}


def _reward_block(point: int, crystal: int, goods) -> dict:
    """One ExploreResultItem reward box.

    ExploreResultItem.as:447-540 reads data.finish_reward / data.max_star_reward,
    each shaped {reward_point, reward_crystal, reward_goods[]}, and prefers point
    then crystal then the first goods entry. Sending nothing left both reward
    slots blank on the WIN panel.
    """
    return {
        "reward_point": int(point or 0),
        "reward_crystal": int(crystal or 0),
        "reward_goods": [{"id": gid, "num": num} for gid, num in goods],
    }


def _explore_start(database_path: Path) -> Response:
    """103 (EXPLORE_KEY) — the expedition battle.

    ExploreMapInfoUI.as:204 and ExplorePveUI.as:698 send EXPLORE_KEY with no gid,
    so fall back to the map the player opened through showId=99.

    ExplorePveUI.as:377 assigns param2 = param2.battle_result and the very next
    line reads _loc2_.is_win with no guard, so a response without battle_result is
    a hard TypeError, not an empty screen. Inside it the page needs the same
    is_win/hunt_type/map_id/monster_group/att_list/def_list/record contract as the
    hunt screen, so the shared battle builder applies.
    """
    gid_value=_request_value("gid")
    uid=_request_value("uid")
    try:
        gid=int(gid_value) if gid_value else None
    except ValueError: return _pet_error(100)
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,point,money,cur_explore_map FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
        if gid is None:
            gid=p["cur_explore_map"]
        m=_explore_map_row(gid)
        if m is None: return _pet_error(400)
        if p["point"] < m["cost_point"] or p["money"] < m["cost_money"]: return _pet_error(403)
        c.execute("UPDATE players SET point=point-?,money=money-?,cur_explore_map=? WHERE id=?",(m["cost_point"],m["cost_money"],gid,p["id"]))
        # LOCAL DEFAULT: an expedition always resolves against the first monsters
        # in monster.txt, since the per-map spawn table is not recoverable.
        # REAL rewards from exploreMap.txt's passReward* columns (the earlier
        # implementation paid a flat LOCAL_EXPLORE_REWARD and no items at all).
        reward_point = m["pass_reward_point"] + LOCAL_EXPLORE_BONUS_POINT
        reward_crystal = m["pass_reward_crystal"]
        parsed_goods = _parse_map_goods(m["pass_reward_goods"])
        reward_goods = _grant_goods(
            c, p["id"],
            [(gid, num, icon) for kind, gid, num, icon in parsed_goods if kind == 1],
        )
        # kind 2 is a pet reward; kind 3 is a picture-book entry with no item row.
        gifted_pets = [(gid, num) for kind, gid, num, _icon in parsed_goods if kind == 2]
        if gifted_pets:
            capacity = c.execute(
                "SELECT pet_capacity FROM players WHERE id=?", (p["id"],)
            ).fetchone()[0]
            held = c.execute(
                "SELECT COUNT(*) FROM pets WHERE player_id=?", (p["id"],)
            ).fetchone()[0]
            pets_table = config_tables._table("pet.txt")
            for gid, num in gifted_pets:
                if gid not in pets_table:
                    continue
                for _ in range(num):
                    if held >= capacity:
                        break
                    c.execute(
                        """INSERT INTO pets (player_id, pet_id, lv, star, pro, icon, skills, generation)
                           VALUES (?,?,1,?,1,?,?,1)""",
                        (p["id"], gid, int(str(pets_table[gid].get("star", "1") or 1).strip() or 1),
                         gid, str(pets_table[gid].get("skills", "") or "").strip() or "101:5101"),
                    )
                    held += 1
            reward_goods = reward_goods + [{"id": gid, "num": num} for gid, num in gifted_pets]
        _credit_battle_rewards(c, p["id"], point=reward_point, crystal=reward_crystal)
        # Expedition battles train the squad too, so exploring is a viable way to
        # level pets for evolution (LOCAL DEFAULT exp amount).
        explore_pets=[r[0] for r in c.execute(
            "SELECT id FROM pets WHERE player_id=? AND battle_state=0 AND is_locked=0 ORDER BY id LIMIT 2",
            (p["id"],))]
        _grant_pet_exp(c,explore_pets,LOCAL_EXPLORE_EXP)
    horse=_explore_horse(database_path, p["id"])
    att_list, def_list, record=_fight_payload(
        database_path,_defenders_from_monsters((1,)))
    if att_list is None: return _pet_error(103)
    return _protocol_response(103,{
        # ExploreUI.as:100 routes to the battle screen only when event_type == 1;
        # anything else (0 here previously) went to ExploreEventResultUI, which
        # never renders a fight, so the expedition silently produced a black page.
        "value":"ok","event_type":_explore_event_type(gid),
        "world":m["world"],"world_id":m["world"],
        "is_tired":0,
        "is_finish":1,"explore_ap":0,"max_explore_ap":0,
        "now_discover_rate":0,"add_discover_rate":0,
        "need_discover_rate":m["need_discover_rate"],
        "energy":0,"cost_energy":0,"add_energy":0,
        "supply":0,"cost_supply":0,"add_supply":0,
        "discover_days":1,"add_discover_days":0,
        # ExploreUI.as:167-168 does getDefinition("map_terrain_" + terrain) with no
        # guard, and map.swf only ships map_terrain_1 / map_terrain_2. A zero here
        # throws and leaves the page on a black background with just the HUD icons.
        "terrain":m["terrain"],
        # ExploreUI.as:182-190 looks up getDefinition("m" + horse); omitting the
        # field produced "mundefined" and threw right after the terrain lookup.
        "horse":horse,
        # ExploreResultItem.as:447-540 renders these two boxes on the WIN panel.
        "finish_reward":_reward_block(
            reward_point, reward_crystal,
            [(entry["id"], entry["num"]) for entry in reward_goods],
        ),
        "max_star_reward":_reward_block(
            m["max_reward_point"], m["max_reward_crystal"],
            [(gid, num) for kind, gid, num, _icon in _parse_map_goods(m["max_reward_goods"])],
        ),
        # ExplorePveUI.as:381-510 dereferences every field below without a guard.
        "battle_result":{
            "is_win":1,"hunt_type":1,"map_id":gid,
            "monster_group":len(def_list)+3,
            "att_list":att_list,"def_list":def_list,"record":record,
            "reward_point":reward_point,"reward_crystal":reward_crystal,
            "reward_goods":reward_goods,"pic":[],
        },
    })


def _explore_list(database_path: Path) -> Response:
    uid=_request_value("uid")
    try: world=int(_request_value("ttype","1"))
    except ValueError: return _pet_error(100)
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
    # ExploreMapListUI.as:200-260 reads world/explore_ap/max_explore_ap and list rows
    # with code,id,terrain,star,max_days; the row name/icon are derived client-side.
    rows=[]
    for gid in sorted(_explore_map_table()):
        if _explore_map_world(gid) != world:
            continue
        row=_explore_map_row(gid)
        rows.append({"index":gid,"code":gid,"id":gid,"terrain":row["terrain"],
                     "name":row["name"],
                     "star":row["star"],"max_days":row["max_days"]})
    if not rows: return _pet_error(400)
    return _protocol_response(98,{"world":world,"explore_ap":0,"max_explore_ap":0,"list":rows})


def _explore_detail(database_path: Path) -> Response:
    try: gid=int(_request_value("gid",""))
    except ValueError: return _pet_error(100)
    m=_explore_map_row(gid)
    if m is None: return _pet_error(400)
    uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,point,money FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
        # Remember the map so the follow-up 103, which carries no gid, can use it.
        c.execute("UPDATE players SET cur_explore_map=? WHERE id=?",(gid,p["id"]))
    return _protocol_response(99,{"id":gid,"world":m["world"],"cost_point":m["cost_point"],"own_point":p["point"],"cost_money":m["cost_money"],"own_money":p["money"],"disaster":m["disaster"],"is_catch":m["is_catch"]})


def _training_overview(database_path: Path) -> Response:
    """504 (REQUEST_TRAIN_KEY): the nine farm training slots.

    DevelopUI.as:117-135 walks `param2.list[i]` with no null guard and falls
    back to `DevelopItem.data = null` for anything missing, which makes
    DevelopItem.as:178 load the `clip_wand` placeholder. That is exactly the
    "star wand instead of a pet" symptom: every slot renders empty because this
    command used to answer with an empty list. A pet only occupies a slot while
    its train_end is in the future, so a finished run drops back to the
    placeholder automatically — the client re-requests 504 when the countdown
    hits zero (DevelopItem.as:226) and the slot simply disappears.

    The training duration is a LOCAL DEFAULT; the original duration table is
    not recoverable.
    """
    uid = _request_value("uid")
    now = int(time.time())
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        # Drop finished runs first so the list never reports a stale countdown.
        c.execute("UPDATE pets SET train_state=0, train_type=0, train_end=0 WHERE train_end>0 AND train_end<=?", (now,))
        training = c.execute(
            """SELECT id AS "index", pet_id AS id, icon, name, lv, train_state, train_end
               FROM pets WHERE player_id=? AND train_end>?
               ORDER BY train_end LIMIT 9""",
            (player["id"], now),
        ).fetchall()
        # DevelopUI.as:120-139 renders one DevelopItem per list entry and falls back
        # to the clip_wand placeholder for every slot with no data, so an empty
        # response showed nine star wands. Fill the remaining slots with the
        # player's own pets (train_state 0 => icon + name, no progress bar) so the
        # page always shows the pet roster.
        idle = c.execute(
            """SELECT id AS "index", pet_id AS id, icon, name, lv, train_state, train_end
               FROM pets WHERE player_id=? AND (train_end IS NULL OR train_end<=?)
               ORDER BY lv DESC, id LIMIT 9""",
            (player["id"], now),
        ).fetchall()
    seen: set[int] = set()
    rows: list = []
    for row in list(training) + list(idle):
        if row["index"] in seen:
            continue
        seen.add(row["index"])
        rows.append(row)
        if len(rows) == 9:
            break
    return _protocol_response(
        504,
        {
            "list": [
                {
                    "index": r["index"],
                    "id": r["id"],
                    "icon": r["icon"],
                    "name": _pet_name(r["id"], r["name"]),
                    "num": 0,
                    "train_state": r["train_state"],
                    "train_time": max(0, ((r["train_end"] or 0) - now) * 1000),
                }
                for r in rows
            ],
            "value": "ok",
        },
    )


def _pet_name(pet_id: int, fallback: object = None) -> str:
    """Real name from pet.txt; the client falls back the same way."""
    if fallback:
        return str(fallback)
    record = config_tables._table("pet.txt").get(pet_id)
    return record["name"] if record else ""


def _pet_list_entry(row: sqlite3.Row) -> dict[str, object]:
    return {"index": row["index"], "id": row["id"], "icon": row["icon"],
            "name": _pet_name(row["id"], row["name"]), "lv": row["lv"],
            "num": 0, "energy": 0}


def _training_list(database_path: Path) -> Response:
    uid = _request_value("uid")
    try: page, size = int(_request_value("p", "1")), int(_request_value("n", "9"))
    except ValueError: return _pet_error(100)
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None: return _pet_error(103)
        rows = c.execute("SELECT id AS 'index',pet_id AS id,icon,name,lv FROM pets WHERE player_id=? AND battle_state=0 ORDER BY id", (player["id"],)).fetchall()
    start=max(0,page-1)*size
    return _protocol_response(505, {"list": [_pet_list_entry(r) for r in rows[start:start+size]]})


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


LOCAL_TRAIN_SECONDS = 60
# LOCAL DEFAULT gains per training type; the original duration/gain tables are
# not recoverable. Keys match DevelopPetInfoUI's three buttons (ttype 1/2/3).
LOCAL_TRAIN_GAIN = {
    1: {"pro_hp": 1},
    2: {"pro_phy_att": 1, "pro_mag_att": 1},
    3: {"pro_phy_def": 1, "pro_mag_def": 1},
}


def _training_action(database_path: Path) -> Response:
    """10 (TRAIN_KEY): start a farm training run for one pet.

    DevelopPetInfoUI.as:172-194 sends {index, ttype:1|2|3}; DevelopResultUI
    .as:164-336 then reads pet{name,icon,id}, reward_point/reward_crystal and the
    add_*_tp set. Starting a run puts the pet into a 504 slot so it renders as a
    pet instead of the clip_wand placeholder.
    """
    uid=_request_value("uid"); idx=_pet_index_from_request()
    try: ttype=int(_request_value("ttype",""))
    except ValueError: return _pet_error(100)
    if idx is None or ttype not in (1,2,3): return _pet_error(100)
    now=int(time.time())
    with _connect_database(database_path) as c:
        player,row=_find_player_pet(c,uid,idx)
        if player is None: return _pet_error(103)
        if row is None: return _pet_error(506)
        if row["is_locked"]: return _pet_error(100)
        if row["train_end"] and row["train_end"] > now: return _pet_error(100)
        c.execute(
            "UPDATE pets SET train_state=?, train_type=?, train_end=? WHERE id=?",
            (ttype, ttype, now + LOCAL_TRAIN_SECONDS, idx),
        )
        pet={"id":row["pet_id"],"icon":row["icon"],"name":_pet_name(row["pet_id"], row["name"])}
    gain=LOCAL_TRAIN_GAIN[ttype]
    # "pro_hp" -> "add_hp_tp". The client field names carry a "_tp" suffix
    # (DevelopResultUI.as:164-336 reads add_hp_tp and friends), so the mapping has
    # to produce that exact name — "pro_hp".split("_")[1] would yield "hp" and
    # every add_*_tp would come back as 0.
    adds={f"add_{k.split('_', 1)[1]}_tp": v for k, v in gain.items()}
    return _protocol_response(10,{
        "pet":pet,"train_type":ttype,"reward_point":0,"reward_crystal":0,
        "add_hp_tp":adds.get("add_hp_tp",0),"add_phy_att_tp":adds.get("add_phy_att_tp",0),
        "add_mag_att_tp":adds.get("add_mag_att_tp",0),"add_speed_tp":0,
        "add_phy_def_tp":adds.get("add_phy_def_tp",0),"add_mag_def_tp":adds.get("add_mag_def_tp",0),
        "add_energy":0,
    })


LOCAL_ARENA_RIVAL_NAME = "试炼对手"
LOCAL_ARENA_RIVAL_LEVEL = 5


LOCAL_EXPLORE_HIRE_SLOTS = 6
# LOCAL DEFAULT: price quoted when every rental slot type is already in use.
LOCAL_EXPLORE_SLOT_PRICE = 12000


def _explore_hire_list(database_path: Path) -> Response:
    """104 (EXPLORE_CANCEL_RENT_KEY) — despite the name this is the hire list.

    HireListUI.as:242-266 reads type/equip_count/max_equip_count off the payload
    and then walks `param2.list` with no null guard; each entry only needs `id`
    and `type` because the name and icon come from the exploreEquip table
    (HireListUI.as:258-259). ttype=1 is mounts, anything else is the roster.
    """
    uid = _request_value("uid")
    try:
        ttype = int(_request_value("ttype", "1"))
        page, size = int(_request_value("p", "1")), int(_request_value("n", "9"))
    except ValueError:
        return _pet_error(100)
    if page < 1 or not 1 <= size <= 9:
        return _pet_error(100)
    table = config_tables._table("exploreEquip.txt")
    # LOCAL DEFAULT: one entry per type from the shipped table, in id order.
    by_type: dict[int, list[int]] = {}
    for equip_id, record in table.items():
        raw = str(record.get("type", "")).strip()
        if raw.isdigit():
            by_type.setdefault(int(raw), []).append(equip_id)
    entries = [{"id": i, "type": ttype} for i in sorted(by_type.get(ttype, []))[:size]]
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        rented = c.execute(
            "SELECT COUNT(*) FROM explore_rented WHERE player_id=?", (player["id"],)
        ).fetchone()[0]
    return _protocol_response(
        104,
        {
            "type": ttype,
            "equip_count": rented,
            "max_equip_count": LOCAL_EXPLORE_HIRE_SLOTS,
            "list": entries,
            "value": "ok",
        },
    )


def _choose_pet_list(database_path: Path) -> Response:
    """42 (CHOOSE_HUNT_PET_LIST_KEY): the picker behind the two hunt slots.

    FightPetListUI.as:173 indexes `param2.list` with no null guard, so the
    array is always present even when the roster is empty.
    """
    uid = _request_value("uid")
    try:
        page, size = int(_request_value("p", "1")), int(_request_value("n", "9"))
    except ValueError:
        return _pet_error(100)
    if page < 1 or not 1 <= size <= 9:
        return _pet_error(100)
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        rows = c.execute(
            """SELECT id AS "index", pet_id AS id, icon, name, lv FROM pets
               WHERE player_id=? AND is_locked=0 ORDER BY id LIMIT ? OFFSET ?""",
            (player["id"], size, (page - 1) * size),
        ).fetchall()
    return _protocol_response(42, {"list": [_pet_list_entry(r) for r in rows]})


def _choose_battle_pet(database_path: Path) -> Response:
    """44 (CHOOSE_BATTLE_PET_KEY): park the picked pet in a hunt slot.

    MainUI has no case for 44, so the payload is handed to the current item and
    HunterTaskUI.as:316-320 immediately re-requests 5. Only a parseable body
    matters; the state itself is re-read from command 5.
    """
    uid = _request_value("uid")
    index = _pet_index_from_request()
    slot = _request_value("ttype", "1")
    if index is None:
        return _pet_error(100)
    with _connect_database(database_path) as c:
        player, row = _find_player_pet(c, uid, index)
        if player is None:
            return _pet_error(103)
        if row is None:
            return _pet_error(506)
        if slot == "1":
            c.execute("UPDATE pets SET battle_state=1 WHERE id=?", (index,))
        else:
            c.execute("UPDATE pets SET battle_state=0 WHERE id=?", (index,))
        pet = _pet_list_entry(row)
    return _protocol_response(44, {"value": "ok", "pet": pet})


def _choose_rest_pet(database_path: Path) -> Response:
    """45 (CHOOSE_REST_PET_KEY): toggle a pet on or off the bench.

    Like 44 the body is discarded and HunterTaskUI re-issues 5; it only has to
    be valid JSON.
    """
    uid = _request_value("uid")
    index = _pet_index_from_request()
    if index is None:
        return _pet_error(100)
    with _connect_database(database_path) as c:
        player, row = _find_player_pet(c, uid, index)
        if player is None:
            return _pet_error(103)
        if row is None:
            return _pet_error(506)
        pet = _pet_list_entry(row)
    return _protocol_response(45, {"value": "ok", "pet": pet})


LOCAL_COPY_MAPS = (1001, 1002, 1003, 1004)
# LOCAL DEFAULT payouts. The original arena/dungeon reward tables are not
# recoverable, so these are flat and are credited to players.point on a win.
LOCAL_ARENA_REWARD = 20
LOCAL_COPY_REWARD = 50
LOCAL_EXPLORE_REWARD = 30
# LOCAL DEFAULT: exp each pet gains from one arena bout / one dungeon clear.
LOCAL_ARENA_EXP = 200000
LOCAL_COPY_EXP = 400000


def _defenders_from_monsters(ids) -> list[dict[str, object]]:
    """Real monster rows for the enemy side of a fight."""
    return [m for m in (_pick_monster(i) for i in ids) if m is not None]


def _fight_payload(database_path: Path, defenders):
    """Assemble the shared 6/24/74 body. Returns (att_list, def_list, record)."""
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        p = c.execute("SELECT id,nick,lv,sex FROM players WHERE uid=?", (uid,)).fetchone()
        if p is None:
            return None
        worn = _worn_equipment(c, p["id"])
        rows = c.execute(
            """SELECT id AS "index", pet_id AS id, icon, name, lv,
                      pro_hp, pro_phy_att, pro_mag_att
               FROM pets WHERE player_id=? AND battle_state=0 AND is_locked=0
               ORDER BY id LIMIT 2""",
            (p["id"],),
        ).fetchall()
    att_list, def_list = _battle_side(
        hunter_skin=_role_skin_string(worn,p["sex"]),
        hunter_name=p["nick"] or "猎人",
        hunter_lv=p["lv"] or 1,
        pet_rows=rows,
        defenders=defenders,
    )
    return att_list, def_list, _battle_record(att_list, def_list)


def _arena_battle(database_path: Path) -> Response:
    """24 (ARENA_KEY) — arena settlement.

    RingResultUI shares the hunt replay contract. FightResultItem.as:349 and :405
    read arena_ap/max_arena_ap/rage_point with no guard and concatenate them into
    text, so all three must be present and numeric.
    """
    parts = _fight_payload(database_path, _defenders_from_monsters((1,)))
    if parts is None:
        return _pet_error(103)
    att_list, def_list, record = parts
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        p = c.execute("SELECT id,arena_ap,max_arena_ap FROM players WHERE uid=?", (uid,)).fetchone()
        if p is None:
            return _pet_error(103)
        ap = max(0, (p["arena_ap"] or 0) - 1)
        c.execute("UPDATE players SET arena_ap=? WHERE id=?", (ap, p["id"]))
        max_ap = p["max_arena_ap"] or LOCAL_ARENA_RIVAL_LEVEL
        _credit_battle_rewards(c, p["id"], point=LOCAL_ARENA_REWARD, crystal=0)
        # Arena bouts train the squad too, matching the hunt/expedition payouts.
        arena_pets=[r[0] for r in c.execute(
            "SELECT id FROM pets WHERE player_id=? AND battle_state=0 AND is_locked=0 ORDER BY id LIMIT 2",
            (p["id"],))]
        _grant_pet_exp(c, arena_pets, LOCAL_ARENA_EXP)
    # LOCAL DEFAULT outcome, rewards and rank; the originals are not recoverable.
    return _protocol_response(24, {
        "is_win": 1, "arena_ap": ap, "max_arena_ap": max_ap, "arena_rank": 0,
        "rage_point": 0, "att_list": att_list, "def_list": def_list,
        "record": record, "pic": [],
        "reward_point": LOCAL_ARENA_REWARD, "reward_crystal": 0, "reward_goods": [],
        "value": "ok",
    })


def _copy_list(database_path: Path) -> Response:
    """73 (COPY_LIST_KEY) — the abyss/dungeon map grid.

    AbyssMapUI.as:197-199 calls int(param2.maps.length) with no null guard, and
    MapItem.as:315 locks a tile when is_battle_able is falsy, so an empty or
    short list would leave nothing tappable.
    """
    uid = _request_value("uid")
    try:
        page, size = int(_request_value("p", "1")), int(_request_value("n", "9"))
    except ValueError:
        return _pet_error(100)
    if page < 1 or not 1 <= size <= 9:
        return _pet_error(100)
    with _connect_database(database_path) as c:
        if c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone() is None:
            return _pet_error(103)
    # LOCAL DEFAULT: four stages, all unlocked, from LOCAL_COPY_MAPS.
    maps = [
        {"code": i, "id": map_id, "is_battle_able": 1,
         "finish_rate": 0, "finished_num": 0}
        for i, map_id in enumerate(LOCAL_COPY_MAPS[:size], start=1)
    ]
    return _protocol_response(73, {"cd": 0, "maps": maps, "value": "ok"})


def _copy_battle(database_path: Path) -> Response:
    """74 (COPY_BATTLE_KEY) — dungeon settlement.

    AbyssResultUI was compared against HunterResultUI and RingResultUI field by
    field: att_list/def_list/record are structurally identical, so the shared
    builder applies. AbyssResultUI.readDatas has no if(param1 == ...) guard, so a
    malformed body here is fatal rather than merely ignored.
    """
    uid = _request_value("uid")
    try:
        hid = int(_request_value("hid", ""))
    except ValueError:
        return _pet_error(100)
    if hid not in LOCAL_COPY_MAPS:
        return _pet_error(400)
    parts = _fight_payload(database_path, _defenders_from_monsters((1, 11)))
    if parts is None:
        return _pet_error(103)
    att_list, def_list, record = parts
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        _credit_battle_rewards(c, player["id"], point=LOCAL_COPY_REWARD, crystal=0)
        copy_pets=[r[0] for r in c.execute(
            "SELECT id FROM pets WHERE player_id=? AND battle_state=0 AND is_locked=0 ORDER BY id LIMIT 2",
            (player["id"],))]
        _grant_pet_exp(c, copy_pets, LOCAL_COPY_EXP)
    # LOCAL DEFAULT rewards; reward_goods[].id resolves through pic.txt
    # (FightResultItem.as:476), so it stays empty rather than guessing an id.
    return _protocol_response(74, {
        "is_win": 1, "att_list": att_list, "def_list": def_list,
        "record": record, "pic": [],
        "reward_point": LOCAL_COPY_REWARD, "reward_crystal": 0, "reward_goods": [],
        "value": "ok",
    })


def _explore_equip_price(record: dict[str, str]) -> tuple[int, int]:
    """(price_type, price) from exploreEquip's three cost columns.

    PropItem.as:286-302 switches on price_type: 1 money, 2 point, 3 crystal and
    anything else the goods variant. HireShopUI.as:215-228 uses the same order.
    """
    money = int(record.get("needMoney") or 0)
    point = int(record.get("needPoint") or 0)
    crystal = int(record.get("needCrystal") or 0)
    if money:
        return 1, money
    if point:
        return 2, point
    if crystal:
        return 3, crystal
    return 4, 0


def _rented_ids(database_path: Path, player_id: int, slot_type: int) -> set[int]:
    with _connect_database(database_path) as c:
        return {
            r["equip_id"]
            for r in c.execute(
                "SELECT equip_id FROM explore_rented WHERE player_id=? AND slot_type=?",
                (player_id, slot_type),
            )
        }


def _explore_equip_list(database_path: Path) -> Response:
    """100 (EXPLORE_EQUIP_LIST_KEY) — the rental shop.

    HireShopUI.as:201-202 reads int(param2.list.length) with no null guard, and
    the name/icon come from exploreEquip itself (:211-212), so each entry only
    needs the id plus its price. `type` must echo the requested ttype rather than
    the table's own type column: HireShopUI.as:179 and HireListUI.as:266 send it
    straight back as the next request's ttype.
    """
    uid = _request_value("uid")
    try:
        ttype = int(_request_value("ttype", "1"))
        page, size = int(_request_value("p", "1")), int(_request_value("n", "9"))
    except ValueError:
        return _pet_error(100)
    if page < 1 or not 1 <= size <= 9:
        return _pet_error(100)
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        rented = _rented_ids(database_path, player["id"], ttype)
    table = config_tables._table("exploreEquip.txt")
    by_type: dict[int, list[int]] = {}
    for equip_id, record in table.items():
        raw = str(record.get("type", "")).strip()
        if raw.isdigit():
            by_type.setdefault(int(raw), []).append(int(equip_id))
    # exploreEquip.type is 1=mount / 2=gear; request ttype 1 and 2 select between
    # them, and 4 is the goods-currency variant shown by HireShopInfoUI.
    source = ttype if ttype in by_type else 1
    entries = []
    for equip_id in sorted(by_type.get(source, []))[:size]:
        price_type, price = _explore_equip_price(table[equip_id])
        entries.append({
            "id": equip_id, "price_type": price_type, "price": price,
            "need_goods_num": 0, "need_goods_id": 0, "type": ttype,
            "is_rented": 1 if equip_id in rented else 0,
        })
    return _protocol_response(100, {"type": ttype, "list": entries, "value": "ok"})


def _explore_equip_info(database_path: Path) -> Response:
    """101 (EXPLORE_EQUIP_INFO_KEY) — rental detail page.

    HireShopInfoUI.as:202 reads goods_ext.need_goods_id with no null guard, so
    goods_ext is always an object. name/icon/remark are resolved by the client
    from exploreEquip, hence they are not sent.
    """
    uid = _request_value("uid")
    try:
        ttype = int(_request_value("ttype", "1"))
        gid = int(_request_value("gid", ""))
    except ValueError:
        return _pet_error(100)
    table = config_tables._table("exploreEquip.txt")
    record = table.get(gid)
    if record is None:
        return _pet_error(400)
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        rented = _rented_ids(database_path, player["id"], ttype)
    return _protocol_response(101, {
        "type": ttype, "id": gid,
        "is_rented": 1 if gid in rented else 0,
        "need_money": int(record.get("needMoney") or 0),
        "need_point": int(record.get("needPoint") or 0),
        "need_crystal": int(record.get("needCrystal") or 0),
        "goods_ext": {"need_goods_id": 0, "own_need_goods_num": 0},
        "value": "ok",
    })


def _explore_rent(database_path: Path) -> Response:
    """102 (EXPLORE_RENT_KEY) — pure ack.

    All three callers (HireShopInfoUI.as:166, HireMountsUI.as:193 and
    HireListUI.as:234) check param2.value == "ok" and silently return otherwise,
    so value must be exactly that string. The row is written first because all
    three re-request 104 immediately afterwards.
    """
    uid = _request_value("uid")
    try:
        ttype = int(_request_value("ttype", "1"))
        gid = int(_request_value("gid", ""))
    except ValueError:
        return _pet_error(100)
    if gid not in config_tables._table("exploreEquip.txt"):
        return _pet_error(400)
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        count = c.execute(
            "SELECT COUNT(*) FROM explore_rented WHERE player_id=? AND slot_type=?",
            (player["id"], ttype),
        ).fetchone()[0]
        if count >= LOCAL_EXPLORE_HIRE_SLOTS:
            return _protocol_response(
                102, {"value": "full", "need_money": 0, "own_money": 0}
            )
        c.execute(
            "INSERT OR IGNORE INTO explore_rented (player_id, equip_id, slot_type)"
            " VALUES (?,?,?)",
            (player["id"], gid, ttype),
        )
    return _protocol_response(102, {"value": "ok"})


def _explore_stop(database_path: Path) -> Response:
    """105 (EXPLORE_INFO_KEY) — "abandon this expedition".

    ExplorePveUI.as:365-372 and ExploreEventResultUI.as:115-122 are identical and
    read only `value`. Anything other than "ok" falls through to the EXPLORE_KEY
    branch, where param2 = param2.battle_result is undefined and the next line
    reads _loc2_.is_win — a hard TypeError (ExplorePveUI.as:377).
    """
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        if c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone() is None:
            return _pet_error(103)
    return _protocol_response(105, {"value": "ok"})


def _explore_add_slot(database_path: Path) -> Response:
    """106 (EXPLORE_ADD_EQUIP_COUNT_KEY) — buy another rental slot.

    The only command in this group that reports field-level failure: on a value
    other than "ok", HireListUI.as:216 and :219 read need_money and own_money with
    no guard, and a missing one becomes NaN in the displayed price.
    """
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        player = c.execute(
            "SELECT id, money FROM players WHERE uid=?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        count = c.execute(
            "SELECT COUNT(DISTINCT slot_type) FROM explore_rented WHERE player_id=?",
            (player["id"],),
        ).fetchone()[0]
        if count < LOCAL_EXPLORE_HIRE_SLOTS:
            # LOCAL DEFAULT: a free slot until every type is filled once.
            return _protocol_response(106, {"value": "ok"})
        own = player["money"] or 0
    return _protocol_response(106, {
        "value": "not_enough",
        "need_money": LOCAL_EXPLORE_SLOT_PRICE,
        "own_money": own,
    })


def _arena_fighter(database_path: Path) -> Response:
    """506 (REQUEST_ARENA_FIGHTER_KEY).

    RingUI.as:286-294 reads id/name/lv/arena_ap/max_arena_ap off the payload and
    then calls `param2.pets.shift()` with no null guard, so an empty or missing
    `pets` array throws. The single rival is a LOCAL DEFAULT stand-in: the real
    ladder of other players is not recoverable, and the player is the only
    account in this offline server.
    """
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        player = c.execute(
            "SELECT id, lv, arena_ap, max_arena_ap FROM players WHERE uid=?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        # LOCAL DEFAULT: the rival borrows the player's own roster so the two
        # Pet widgets resolve real `p<icon>` artwork instead of empty slots.
        pets = c.execute(
            """SELECT id AS "index", pet_id AS id, icon, lv FROM pets
               WHERE player_id=? AND battle_state=0 ORDER BY id LIMIT 2""",
            (player["id"],),
        ).fetchall()
        rival_pets = [
            {"index": r["index"], "id": r["id"], "icon": r["icon"],
             "name": _pet_name(r["id"]), "lv": LOCAL_ARENA_RIVAL_LEVEL}
            for r in pets
        ]
    return _protocol_response(
        506,
        {
            "id": LOCAL_ARENA_RIVAL_NAME,
            "name": LOCAL_ARENA_RIVAL_NAME,
            "lv": LOCAL_ARENA_RIVAL_LEVEL,
            "arena_ap": player["arena_ap"],
            "max_arena_ap": player["max_arena_ap"],
            "skin": _role_skin_string({}),
            "pets": rival_pets,
        },
    )


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
               generation, buffs, pro_hp, pro_speed, pro_phy_att, pro_mag_att, pro_phy_def, pro_mag_def,
               train_state, train_type, train_end
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
        # Populating the name from pet.txt matters here: FarmUI's PetItem and
        # Pet.as:135 both read data.name with no fallback, so dropping the key
        # rendered "undefined" on the device.
        pet["name"] = _pet_name(row["id"], row["name"])
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


def _pet_synthesis_pick(database_path: Path, command_id: int) -> Response:
    """62/63 (MAKE_MAIN_PET_KEY / MAKE_VICE_PET_KEY).

    PetSynthesisListUI.as:198-224 renders `list[]` rows with index/name/lv/icon;
    the name falls back to pet.txt when absent, so `name` may be left empty.
    An empty first page shows error 10 ("没有可用的宠物"), which is the correct
    behaviour when the player has nothing to offer.
    """
    uid = _request_value("uid")
    try:
        page = int(_request_value("p", "1"))
        page_size = int(_request_value("n", "9"))
    except ValueError:
        return _pet_error(100)
    if page < 1 or not 1 <= page_size <= 9:
        return _pet_error(100)
    with _connect_database(database_path) as connection:
        player = connection.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        # LOCKED pets cannot be consumed or used as material.
        rows = connection.execute(
            """
            SELECT id AS "index", pet_id AS id, icon, name, lv FROM pets
            WHERE player_id=? AND battle_state=0 AND is_locked=0
            ORDER BY id LIMIT ? OFFSET ?
            """,
            (player["id"], page_size, (page - 1) * page_size),
        ).fetchall()
    return _protocol_response(
        command_id,
        {"list": [_pet_list_entry(r) for r in rows]},
    )


def _pet_synthesis(database_path: Path) -> Response:
    """65 (MAKE_PET_KEY): fuse the main pet with the vice pet.

    PetSynthesisUI.as:254-264 sends {main, vice, ttype}. PetSynthesisResultUI
    .as:124-197 needs index (for follow-ups), icon (instantiates "p"+icon with
    no guard), name|id, lv, type, skills[]|buffs[] and the exd_* reinforcement
    fields.

    The fusion outcome itself is a LOCAL DEFAULT: the original server's synthesis
    table is not recoverable, so the vice pet is consumed and the main pet keeps
    its identity while gaining one generation of reinforcement.
    """
    uid = _request_value("uid")
    main_raw = _request_value("main")
    vice_raw = _request_value("vice")
    if not main_raw or not vice_raw:
        return _pet_error(100)
    try:
        main_index, vice_index = int(main_raw), int(vice_raw)
    except ValueError:
        return _pet_error(100)
    if main_index == vice_index:
        return _pet_error(100)

    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id, pet_capacity FROM players WHERE uid=?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        main_row = connection.execute(
            "SELECT * FROM pets WHERE id=? AND player_id=?", (main_index, player["id"])
        ).fetchone()
        vice_row = connection.execute(
            "SELECT * FROM pets WHERE id=? AND player_id=?", (vice_index, player["id"])
        ).fetchone()
        if main_row is None or vice_row is None:
            return _pet_error(506)
        if main_row["is_locked"] or vice_row["is_locked"]:
            return _pet_error(524)
        if vice_row["battle_state"] != 0 or main_row["battle_state"] != 0:
            return _pet_error(524)

        # LOCAL DEFAULT: one generation, +1 to each of the six reinforcements.
        # pets stores them as pro_* (pro_hp … pro_mag_def), matching the
        # *_tp fields DevelopPetInfoUI reads on command 9.
        step = {"pro_hp": 5, "pro_speed": 5, "pro_phy_att": 5,
                "pro_mag_att": 5, "pro_phy_def": 5, "pro_mag_def": 5}
        for column, delta in step.items():
            connection.execute(
                f"UPDATE pets SET {column} = {column} + ? WHERE id = ?", (delta, main_index)
            )
        generation = (main_row["generation"] or 1) + 1
        connection.execute("UPDATE pets SET generation=? WHERE id=?", (generation, main_index))
        connection.execute("DELETE FROM pets WHERE id=?", (vice_index,))
        updated = connection.execute(
            """SELECT id AS "index", pet_id AS id, icon, name, lv, star, pro, skills,
                      pro_hp, pro_speed, pro_phy_att, pro_mag_att, pro_phy_def, pro_mag_def
               FROM pets WHERE id=?""",
            (main_index,),
        ).fetchone()

    skills = [s for s in str(updated["skills"] or "").replace(";", ":").split(":") if s.strip()]
    payload = {
        "index": updated["index"],
        "id": updated["id"],
        "icon": updated["icon"],
        "name": _pet_name(updated["id"], updated["name"]),
        "lv": updated["lv"],
        "exd_generation": generation,
        "type": 1,
        "skills": [{"id": int(s)} for s in skills if s.isdigit()],
        "buffs": [],
        "exd_hp_tp": updated["pro_hp"],
        "exd_speed_tp": updated["pro_speed"],
        "exd_phy_att_tp": updated["pro_phy_att"],
        "exd_mag_att_tp": updated["pro_mag_att"],
        "exd_phy_def_tp": updated["pro_phy_def"],
        "exd_mag_def_tp": updated["pro_mag_def"],
    }
    return _protocol_response(65, payload)


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
        if command == "show" and _request_value("showId") == "506":
            return _arena_fighter(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "42":
            return _choose_pet_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "104":
            return _explore_hire_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "100":
            return _explore_equip_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "101":
            return _explore_equip_info(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "102":
            return _explore_rent(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "105":
            return _explore_stop(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "106":
            return _explore_add_slot(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "24":
            return _arena_battle(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "73":
            return _copy_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "74":
            return _copy_battle(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "44":
            return _choose_battle_pet(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "45":
            return _choose_rest_pet(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "504":
            return _training_overview(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "505":
            return _training_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "9":
            return _training_detail(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "10":
            return _training_action(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "62":
            return _pet_synthesis_pick(current_app.config["DATABASE"], 62)
        if command == "show" and _request_value("showId") == "63":
            return _pet_synthesis_pick(current_app.config["DATABASE"], 63)
        if command == "show" and _request_value("showId") == "65":
            return _pet_synthesis(current_app.config["DATABASE"])
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
        # Fallback for commands the client sends but this server has not
        # implemented yet (48 of them at the time of writing).
        #
        # Returning 501 used to produce the in-game "网络错误" alert, because
        # APetHunter.as:166-168 raises that dialog from ioHttpRequestError — i.e.
        # on any transport-level failure, not on a protocol error. APetHunter.as
        # :143-162 only parses the body when the status is a normal success, so a
        # 200 with a valid envelope lets every page take its normal branch and
        # simply render empty instead of blocking the player with an error.
        unimplemented = _request_value("showId")
        try:
            fallback_id = int(unimplemented or 0)
        except ValueError:
            fallback_id = 0
        app.logger.warning(
            "unimplemented command showId=%s answered with an empty envelope",
            unimplemented,
        )
        return _protocol_response(fallback_id, {"value": "ok"})

    return app
