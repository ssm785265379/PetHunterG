import ipaddress
import hashlib
import hmac
import json
import os
import math
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
    # 金币商店 (price_type 1 = money)
    {"item_id": 10007, "team": 1, "shop_type": 1, "price_type": 1, "price": 80, "icon": 10007, "sort": 1},
    {"item_id": 10001, "team": 1, "shop_type": 1, "price_type": 1, "price": 90, "icon": 10001, "sort": 2},
    {"item_id": 10014, "team": 1, "shop_type": 1, "price_type": 1, "price": 200, "icon": 10014, "sort": 3},
    {"item_id": 10002, "team": 1, "shop_type": 1, "price_type": 1, "price": 360, "icon": 10002, "sort": 4},
    {"item_id": 10009, "team": 1, "shop_type": 1, "price_type": 1, "price": 460, "icon": 10009, "sort": 5},
    {"item_id": 10505, "team": 1, "shop_type": 1, "price_type": 1, "price": 200, "icon": 10505, "sort": 6},
    {"item_id": 10028, "team": 1, "shop_type": 1, "price_type": 1, "price": 1800, "icon": 10028, "sort": 7},
    # 银币商店 (price_type 2 = point)
    {"item_id": 10011, "team": 1, "shop_type": 2, "price_type": 2, "price": 500, "icon": 10011, "sort": 1},
    {"item_id": 10022, "team": 1, "shop_type": 2, "price_type": 2, "price": 500, "icon": 10022, "sort": 2},
    {"item_id": 10015, "team": 1, "shop_type": 2, "price_type": 2, "price": 5000, "icon": 10015, "sort": 3},
    {"item_id": 10023, "team": 1, "shop_type": 2, "price_type": 2, "price": 160000, "icon": 10023, "sort": 4},
)
# LOCAL DEFAULT 神秘商店: three random props a day, prices rolled inside a band
# around the prop's own reference price. The rotation is keyed on the local date so
# restarts within one day keep the same offer.
LOCAL_MYSTERY_SHOP_SLOTS = 3
LOCAL_MYSTERY_PRICE_MIN = 0.6
LOCAL_MYSTERY_PRICE_MAX = 1.4
# Local levelling rule for pet exp: the original curve is not recoverable.
# LOCAL DEFAULT: a flat 1,000,000 exp per level. The bundled exp items carry real
# per-item values in this range (prop.txt's 宠物经验道具 grants 1,330,000), so the
# per-level cost stays in that scale and battle rewards below are scaled to match.
# LOCAL DEFAULT: the shipped config has no levelling table at all, so the curve is
# ours. The cap is 1000 because monster.txt's own `level` column runs 1..1000 and
# help.txt id 10 talks about 500/300-level pets (one evolution step takes 200),
# neither of which fits a 99 cap.
LOCAL_MAX_PET_LEVEL = 1000


def exp_to_next(lv: int) -> int:
    """LOCAL DEFAULT exp needed to leave `lv`. Four linear segments, tuned so a
    same-level pet needs roughly 3-9 kills early and 8-17 at the cap."""
    if lv <= 50:
        return 5_000 + 1_000 * (lv - 1)
    if lv <= 200:
        return 60_000 + 2_000 * (lv - 50)
    if lv <= 500:
        return 700_000 + 10_000 * (lv - 200)
    return 4_000_000 + 60_000 * (lv - 500)
# LOCAL DEFAULT: exp a single battle awards to each pet that took part, per
# monster level. 100,000 means a lv-1 hunt is ~10% of a level.
# Fallback only: monster.txt ships a per-monster `exp` column, which is the real
# source. This constant just covers rows whose cell is 0, so it is deliberately
# small — at 100,000 a 0-exp monster would out-pay the ones with real data.
LOCAL_HUNT_EXP_PER_LEVEL = 100
# LOCAL DEFAULT: one expedition is a quarter of a level for the squad's own level.
LOCAL_EXPLORE_EXP_SHARE = 4
# LOCAL DEFAULT: exploreMap.txt's passRewardPoint is 0 on most maps — their pass
# reward is an item or a picture-book entry — so a flat silver bonus is added on
# top to keep expeditions worth running.
LOCAL_EXPLORE_BONUS_POINT = 30
# LOCAL DEFAULT: expedition stamina cap. The original AP table is not recoverable;
# the HUD prints explore_ap/max_explore_ap directly, so they have to be real.
LOCAL_DEFAULT_EXPLORE_AP = 20
# LOCAL DEFAULT: which monster level an expedition map fields. exploreMap.txt's
# `star` is the only difficulty knob it ships, so the band is derived from it.
LOCAL_EXPLORE_LEVEL_BASE = 10
LOCAL_EXPLORE_LEVEL_PER_STAR = 10
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
            # Never hand a character the other sex's copy: equip.txt ships one row
            # per sex and the bag hides (and 37 refuses) the mismatched one, so a
            # cross-sex drop would be an item the player can see in the reward tip
            # but never use. Map it to the (name, type) twin instead, and keep the
            # icon/stat columns consistent with the twin.
            owner = connection.execute(
                "SELECT sex FROM players WHERE id = ?", (player_id,)
            ).fetchone()
            owner_sex = int(owner["sex"] or 0) if owner else 1
            item_sex = config_tables.equip_sex(record)
            if item_sex is not None and int(item_sex) != owner_sex:
                twin_id = config_tables.equip_same_slot_other_sex(gid)
                if twin_id is None:
                    continue
                gid = twin_id
                record = equips.get(twin_id, {})
                record_icon = icon_override or stat("iconId") or gid
                icon = record_icon
            else:
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
        while lv < LOCAL_MAX_PET_LEVEL:
            need = exp_to_next(lv)
            if exp < need:
                break
            exp -= need
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
        # Expedition stamina. The explore HUD concatenates explore_ap/max_explore_ap
        # straight into text, so without these columns it printed "0/0" on every
        # page. LOCAL DEFAULT: 20 points, refilled to the cap on each read.
        if "explore_ap" not in player_columns:
            connection.execute(
                f"ALTER TABLE players ADD COLUMN explore_ap INTEGER NOT NULL DEFAULT {LOCAL_DEFAULT_EXPLORE_AP}"
            )
        if "rage_point" not in player_columns:
            # FightResultItem.as:211-215 draws this as a 0..100 meter and :169
            # unlocks 无双一击 at 100, so it has to accumulate between hunts
            # rather than be a per-fight flag.
            connection.execute(
                "ALTER TABLE players ADD COLUMN rage_point INTEGER NOT NULL DEFAULT 0"
            )
        if "guild_id" not in player_columns:
            # 86/88/91 are real now, so membership has to live somewhere.
            connection.execute("ALTER TABLE players ADD COLUMN guild_id INTEGER")
        if "guild_position" not in player_columns:
            # GameUtil.getGuildPost: 1 = leader, 2 = officer, 3 = member.
            connection.execute(
                "ALTER TABLE players ADD COLUMN guild_position INTEGER NOT NULL DEFAULT 0"
            )
        if "max_explore_ap" not in player_columns:
            connection.execute(
                f"ALTER TABLE players ADD COLUMN max_explore_ap INTEGER NOT NULL DEFAULT {LOCAL_DEFAULT_EXPLORE_AP}"
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
        # Bag rows seeded before prop.txt drove the effect rules carry
        # item_type/use_type = 0, which made every consumable unclickable and
        # rejected by the use-goods guard. Re-align them with the shipped table on
        # every boot (idempotent; only touches rows that disagree).
        prop_table = config_tables.prop_table()
        for row in connection.execute(
            "SELECT id, item_id, item_type, use_type FROM inventory WHERE team IN (1, 2)"
        ).fetchall():
            record = prop_table.get(row["item_id"])
            if record is None:
                continue
            kind_raw = str(record.get("type", "") or "").strip()
            use_raw = str(record.get("useType", "") or "").strip()
            if not kind_raw.lstrip("-").isdigit():
                continue
            kind = int(kind_raw)
            use_type = int(use_raw) if use_raw.lstrip("-").isdigit() else 0
            # Keep going when kind == 0: such props still carry a `useType` that
            # decides whether the bag cell is clickable at all.
            if row["item_type"] != kind or row["use_type"] != use_type:
                connection.execute(
                    "UPDATE inventory SET item_type = ?, use_type = ? WHERE id = ?",
                    (kind, use_type, row["id"]),
                )
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
        # 神秘商店 (shop_type 4) rotates daily; this remembers which day the rows
        # were rolled for, so a restart inside the same day keeps the same offer.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS shop_rotation (
                shop_type INTEGER PRIMARY KEY,
                day TEXT NOT NULL
            )
            """
        )
        # 深渊 (commands 73/74) clears. One row per stage means command 73 can show
        # real progress ("通关人数/完成度") and gate the next stage instead of
        # advertising four permanently-open tiles.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS copy_cleared (
                player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                stage_id INTEGER NOT NULL,
                cleared_at TEXT,
                PRIMARY KEY (player_id, stage_id)
            )
            """
        )
        # The shop table is a local default, not player data, so it is rewritten
        # from LOCAL_SHOP_GOODS on every start. That keeps removed goods from
        # lingering in older saves (purchases go to `inventory`, not here).
        # The mystery rows are wiped too, so the rotation marker has to be cleared
        # as well — otherwise the day looks "already rolled" and 神秘商店 comes up
        # empty until midnight.
        connection.execute("DELETE FROM shop_goods")
        connection.execute("DELETE FROM shop_rotation")
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
            # 出战槽位（1/2，0=未安排）。和 battle_state 分开：后者被"能否放生/合成"
            # 等逻辑当作"在队里"使用，直接改它会牵动十几处查询。
            ("squad_slot", "ALTER TABLE pets ADD COLUMN squad_slot INTEGER NOT NULL DEFAULT 0"),
            # 训练收益先记账、到点再发放（用户要求"时间结束再点才加属性"）。
            ("train_gain", "ALTER TABLE pets ADD COLUMN train_gain INTEGER NOT NULL DEFAULT 0"),
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
        # Picture-book (图鉴) collection: which creatures the player has
        # registered, and which picStep milestone rewards were already taken.
        # picStep.txt holds the milestones (value = entries required).
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS hunt_progress (
                player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                map_id INTEGER NOT NULL,
                kills INTEGER NOT NULL DEFAULT 0,
                cleared INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (player_id, map_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS guilds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                leader_player_id INTEGER,
                max_mem_num INTEGER NOT NULL DEFAULT 10,
                created_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pic_unlocked (
                player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                pic_id INTEGER NOT NULL,
                unlocked_at TEXT,
                PRIMARY KEY (player_id, pic_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pic_step_claimed (
                player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                step_id INTEGER NOT NULL,
                claimed_at TEXT,
                PRIMARY KEY (player_id, step_id)
            )
            """
        )
        # Weekly arena star prize (commands 82/83). The key is the ISO week so the
        # reward re-arms every week, matching the "每周3、6刷新" note on the rank page.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arena_star_claimed (
                player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                week_key TEXT NOT NULL,
                claimed_at TEXT,
                PRIMARY KEY (player_id, week_key)
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
        # Pets created before `buffSkills` was read (old saves, seed scripts) carry
        # an empty `buffs`: 10034 (遗忘卡牌) then answers 522 forever and command
        # 13's 特性 section stays blank. Seed the first traits for the generation.
        for pet in connection.execute(
            "SELECT id, pet_id, generation, buffs FROM pets"
        ).fetchall():
            if pet["buffs"]:
                continue
            seeded = _buffs_for_pet(pet["pet_id"], int(pet["generation"] or 1))
            if seeded:
                connection.execute(
                    "UPDATE pets SET buffs=? WHERE id=?", (seeded, pet["id"])
                )
        # 坐骑: every character gets one free mount so the expedition page has
        # something to show and rent. Without a rental row, command 104 answers an
        # empty list and the mount screen is a dead end (its shop branch is only
        # reachable with a non-empty list). Renting another mount later switches the
        # active one — `_explore_horse` prefers the newest rental.
        if LOCAL_STARTER_MOUNT_ID in config_tables._table("exploreEquip.txt"):
            for player in connection.execute("SELECT id FROM players").fetchall():
                has_mount = connection.execute(
                    "SELECT 1 FROM explore_rented WHERE player_id=? AND slot_type=1",
                    (player["id"],),
                ).fetchone()
                if has_mount is None:
                    connection.execute(
                        "INSERT OR IGNORE INTO explore_rented"
                        " (player_id, equip_id, slot_type) VALUES (?, ?, 1)",
                        (player["id"], LOCAL_STARTER_MOUNT_ID),
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
            INSERT INTO pets (player_id, pet_id, lv, star, pro, icon, skills, buffs)
            VALUES (?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (player_id, pet["pet_id"], pet["star"], pet["pro"], pet["icon"],
             "101:5101" if pet["pet_id"] == 1001 else "103:5101",
             _buffs_for_pet(pet["pet_id"], 1)),
        )
        added += 1
    return added


def _insert_starter_equipment(
    connection: sqlite3.Connection, player_id: int, sex: int = 1
) -> int:
    """Insert the local starter equipment; returns how many rows were added.

    equip.txt keeps one row per sex, so a female character must get the female
    twin (same name/type, different imageId). Handing everyone the male 20001
    left female saves with an unwearable, now-hidden row.
    """
    added = 0
    for configured in LOCAL_STARTER_EQUIPMENT:
        item = dict(configured)
        record = config_tables.equip_record(int(item["item_id"]))
        item_sex = config_tables.equip_sex(record) if record else None
        if item_sex is not None and int(item_sex) != int(sex):
            counterpart = config_tables.equip_same_slot_other_sex(int(item["item_id"]))
            if counterpart is None:
                continue
            twin = config_tables.equip_record(counterpart) or {}
            stats = config_tables.equip_stats(twin)
            item.update(
                item_id=counterpart,
                icon=config_tables.equip_icon(twin),
                item_type=config_tables.equip_slot(twin) or item["item_type"],
                star=config_tables.equip_star(twin),
                **stats,
            )
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
        players = connection.execute("SELECT id, sex FROM players ORDER BY id").fetchall()
        for player in players:
            if _insert_starter_equipment(connection, player["id"], int(player["sex"] or 0)):
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
            _insert_starter_equipment(connection, cursor.lastrowid, sex)
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
            _insert_starter_equipment(connection, cursor.lastrowid, sex)
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
#
# The keys are the *registration* values, not an arbitrary enum: /regplayer only
# accepts sex 0 or 1 and stores the female triple when sex != 1 (app.py:863).
# Keying this dict 1/2 made `_base_skin_layers(0)` fall through to the male
# default, so every female hunter was drawn with the male head and hair.
LOCAL_BASE_SKIN_LAYERS = {
    1: (100001, 100002, 100003),
    0: (100001, 100004, 100005),
}


def _base_skin_layers(sex: int) -> tuple[int, ...]:
    try:
        key = int(sex)
    except (TypeError, ValueError):
        key = 1
    return LOCAL_BASE_SKIN_LAYERS.get(key, LOCAL_BASE_SKIN_LAYERS[1])


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
    silently drops the rest, then :71 sorts the survivors and :72-79 addChild's
    every one of them: there is no replace/merge logic anywhere in the class, so
    whatever we list gets stacked. (Note `sortOn("z",16)`: 16 is Array.NUMERIC,
    i.e. ascending — the ordering only decides who paints last, not what exists.)

    Two things must therefore be true of the string:
      * the bare character needs its head and hair layers (CreateUI.as:366-378);
        omitting them produced a headless hunter in battle.
      * every equipment layer must be the *player's own sex*. equip.txt keeps one
        row per sex with a different imageId (20002 male -> 100020, 20005 female
        -> 100040), and `_worn_equipment` never filtered on that, so a male hunter
        wearing a female armour row rendered the male base triple *plus* the
        female armour sprite — the "男女图层重合" seen on screen.
    """
    skin = config_tables.skin_table()
    base = [lid for lid in _base_skin_layers(sex) if lid in skin]
    gear: list[int] = []
    for row in worn.values():
        record = config_tables.equip_record(row["item_id"])
        if not record:
            continue
        item_sex = config_tables.equip_sex(record)
        if item_sex is not None and item_sex != int(sex):
            # Cross-sex gear: draw the matching piece instead of dropping the
            # layer, so saves seeded with both sexes still look armoured.
            counterpart = config_tables.equip_same_slot_other_sex(row["item_id"])
            record = config_tables.equip_record(counterpart) if counterpart else None
            if not record:
                continue
        image_id = config_tables.equip_image_id(record)
        if image_id and image_id in skin and image_id not in gear:
            gear.append(image_id)

    # The base triple is a COMPLETE DEFAULT OUTFIT, not "body + head + hair":
    #   100002 (z4) body, 100003 (z5) head, 100001 (z6) arms holding a default
    #   weapon.
    # Measured sprite sizes back this up (100001 is 270x135 like the 258x142 weapon
    # sprite, while the armour is 183x300). So equipment REPLACES the base layer at
    # its own depth — which is also why switching a weapon must change the
    # arms+weapon sprite instead of stacking a second weapon on the character.
    #
    # PETHUNTER_SKIN_MODE=overlay restores the old stacking behaviour as an escape
    # hatch; "replace" is the only supported mode otherwise.
    mode = os.environ.get("PETHUNTER_SKIN_MODE", "replace").strip().lower()
    if gear and mode != "overlay":
        taken = {int(skin.get(lid, {}).get("z", "0") or 0) for lid in gear}
        layers = [
            lid for lid in base
            if int(skin.get(lid, {}).get("z", "0") or 0) not in taken
        ]
        layers.extend(gear)
    else:
        layers = base + [lid for lid in gear if lid not in base]
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


def _player_payload(connection: sqlite3.Connection, player: sqlite3.Row) -> dict[str, object]:
    """Everything HomeUI/RoleInfoUI read, built from an already-fetched player row.

    Shared by 2/510/511 and by ON_EQUIP(37). MainUI.as:317-318 has no case for 37
    and falls through to `default: Navigator.getInstance().item.readDatas(...)`,
    which hands the body to whichever screen is current. Equipping flows straight
    back to HomeUI (EquipInfoUI.as:337-341), and HomeUI.readDatas never looks at
    the command id — it just reads param2.img/lv/job/... So returning
    {"value":"ok"} from 37 set GameUtil.skin = undefined, ShowItem.as:36-40 called
    removeAll() (the doll vanished) and every label printed `undefined`.
    """
    worn = _worn_equipment(connection, player["id"])
    pic_num = connection.execute(
        "SELECT COUNT(*) FROM pets WHERE player_id = ?", (player["id"],)
    ).fetchone()[0]
    payload = dict(player)
    # RoleInfoUI.as:137-186 and HomeUI.as:184-196 read every field below; the six
    # stats, the three equipment slots and `img` (the paper-doll layer string) were
    # all missing, which is why the panel printed `undefined` and why worn gear
    # never showed up on the character.
    payload.update(_role_stats(worn))
    payload["img"] = _role_skin_string(worn, player["sex"] if "sex" in player.keys() else 1)
    payload["pic_num"] = pic_num
    payload["skills"] = []
    payload["buffs"] = []
    payload.update(_equipped_slot_fields(worn))
    # Local starting state; guild and arena systems are not restored yet.
    # HomeUI resolves job through the bundled upRole configuration.
    payload.update(job=1, guild_name="", guild_position=0, arena_rank=_local_arena_rank())
    return payload


_PLAYER_ROW_SQL = """
    SELECT id, nick AS name, lv, sex, img, money, point, crystal,
           ht_ap, max_ht_ap, arena_ap, max_arena_ap
    FROM players WHERE uid = ?
"""


def _player_info(database_path: Path, command_id: int = 510) -> Response:
    uid = _request_value("uid")
    with _connect_database(database_path) as connection:
        player = connection.execute(_PLAYER_ROW_SQL, (uid,)).fetchone()
        if player is None:
            return Response("-1:0", status=404, mimetype="text/plain; charset=utf-8")
        payload = _player_payload(connection, player)
    return _protocol_response(command_id, payload)


def _equip_matches_sex(item_id: int, sex: int) -> bool:
    """equip.txt ships every piece twice, one row per sex (sex 0 female, 1 male).

    A row belonging to the other sex must never show up in this character's bag:
    wearing it stacked a female sprite onto a male paper doll, and the equipment
    tab simply has no business listing it.
    """
    record = config_tables.equip_record(item_id)
    item_sex = config_tables.equip_sex(record) if record else None
    return item_sex is None or int(item_sex) == int(sex)


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
            "SELECT id, bag_capacity, sex FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return Response("-1:0", status=404, mimetype="text/plain; charset=utf-8")
        sex = int(player["sex"] or 0)
        if item_type == 3:
            # Sex filtering has to happen before paging, otherwise page 1 shows
            # 9 rows, page 2 repeats some of them and the count is wrong.
            every_row = connection.execute(
                """
                SELECT id AS "index", item_id AS id, team, quantity AS num, icon,
                       item_type AS type, use_type, level
                FROM inventory WHERE player_id = ? AND team = 3 ORDER BY id
                """,
                (player["id"],),
            ).fetchall()
            visible = [r for r in every_row if _equip_matches_sex(r["id"], sex)]
            count = len(visible)
            start = (page - 1) * page_size
            rows = visible[start:start + page_size]
        else:
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
        # BagListUI hands `icon` straight to PropItem, and PropItem.as:233 does
        # getDefinition("p" + data.icon) itself. Pre-prefixing here made it look
        # up "pp10007", getDefinition returned null, `new null()` threw, and the
        # empty catch at PropItem.as:243 swallowed it — every bag slot rendered
        # without art until you opened the detail page (39 sends a bare number).
        # So this field must stay a NUMBER. Only IconItem consumers
        # (IconItem.as:79 getDefinition("" + icon)) want the full class name.
        item["icon"] = item["icon"] or 0
        if item["team"] in (1, 2):
            # PropItem.as:328-333 disables the slot when data.on == 0. The response
            # carried no `on` at all, so non-consumables (prop.txt type 0, e.g.
            # 王国勋章) still looked tappable and just answered -1:100 — the
            # "不可使用的也展示出来了" report.
            #
            # Only type 0 is disabled: several really-usable props carry value 0
            # (扩建证书/遗忘之锤/推磨钱袋) or even a decimal (狩猎秘籍 value=1.5),
            # so keying off _prop_effect_rules wrongly greyed them out.
            kind = str((config_tables.prop_record(item["id"]) or {}).get("type", "")).strip()
            item["on"] = 0 if kind in ("", "0") else 1
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


def _refresh_mystery_shop(connection: sqlite3.Connection) -> None:
    """LOCAL DEFAULT 神秘商店: three random usable props per local day.

    Seeded from the date, so every restart inside one day keeps the same offer,
    and the picks are written into `shop_goods` so commands 28/29 need no special
    case. Prices roll inside a band around the prop's own reference price
    (prop.txt `money` first, then `point`).
    """
    today = time.strftime("%Y-%m-%d")
    current = connection.execute(
        "SELECT day FROM shop_rotation WHERE shop_type = 4"
    ).fetchone()
    if current is not None and current["day"] == today:
        return

    def price_of(record: dict[str, str], key: str) -> int:
        raw = str(record.get(key, "") or "").strip()
        return int(raw) if raw.lstrip("-").isdigit() else 0

    pool: list[tuple[int, dict[str, str]]] = []
    for item_id, record in config_tables.prop_table().items():
        kind = price_of(record, "type")
        # Only props whose effect USE_GOODS can actually apply, and only ones with
        # a non-zero effect amount (value 0 props are the dedicated-command pets).
        if kind == 0 or price_of(record, "value") <= 0:
            continue
        if str(record.get("team", "")).strip() not in ("1", "2"):
            continue
        pool.append((item_id, record))
    if not pool:
        return

    rng = random.Random(f"mystery-{today}")
    picks = rng.sample(pool, min(LOCAL_MYSTERY_SHOP_SLOTS, len(pool)))
    connection.execute("DELETE FROM shop_goods WHERE shop_type = 4")
    for sort, (item_id, record) in enumerate(picks, start=1):
        money, point = price_of(record, "money"), price_of(record, "point")
        base = money or point or 200
        price = max(1, round(base * rng.uniform(LOCAL_MYSTERY_PRICE_MIN,
                                                LOCAL_MYSTERY_PRICE_MAX)))
        price_type = 1 if money else 2
        connection.execute(
            "INSERT OR REPLACE INTO shop_goods"
            " (item_id, team, shop_type, price_type, price, icon, sort)"
            " VALUES (?, 1, 4, ?, ?, ?, ?)",
            (item_id, price_type, price, price_of(record, "iconId") or item_id, sort),
        )
    connection.execute(
        "INSERT INTO shop_rotation (shop_type, day) VALUES (4, ?)"
        " ON CONFLICT(shop_type) DO UPDATE SET day = excluded.day",
        (today,),
    )


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
        if shop_type == 4:
            _refresh_mystery_shop(connection)
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
        # Read the effect kind from prop.txt instead of the 13-entry local
        # catalog: a purchased row written with item_type=0 is unclickable in the
        # bag, and the lazy self-heal only runs when the item is used — which can
        # never happen if the grid refuses the tap.
        _prop_record = config_tables.prop_record(row["item_id"]) or {}

        def _prop_int(key: str) -> int:
            raw = str(_prop_record.get(key, "") or "").strip()
            return int(raw) if raw.lstrip("-").isdigit() else 0

        prop = {"type": _prop_int("type"), "use_type": _prop_int("useType")}
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


def _prop_effect_rules(item_id: int) -> dict[str, int] | None:
    """Read a prop's effect straight from prop.txt (the shipped authority).

    prop.txt columns: id, name, iconId, **type** (effect kind), **value** (effect
    amount), value1, **useType** (bag interaction), ...

    The old code compared prop.txt's type against the *inventory row's*
    `item_type`, but `seed_items.py` wrote a literal 0 into every seeded row, so
    every seeded consumable failed the guard and answered -1:100 while staying in
    the bag. The local catalog it consulted also only covered 13 ids and had
    10011 at 1,000,000 while prop.txt says 10,000 (a 100x error). Reading the
    table fixes both, and lets every effect-bearing prop work instead of 13.
    """
    record = config_tables.prop_record(item_id)
    if record is None:
        return None

    def number(key: str) -> int:
        raw = str(record.get(key, "") or "").strip()
        return int(raw) if raw.lstrip("-").isdigit() else 0

    kind = number("type")
    amount = number("value")
    if kind == 0 or amount == 0:
        return None
    return {"type": kind, "value": amount, "use_type": number("useType")}


def _pet_by_star(min_star: int) -> int | None:
    """A random pet.txt species whose star is at least `min_star`."""
    table = config_tables._table("pet.txt")
    pool = []
    for pet_id, record in table.items():
        raw = str(record.get("star", "") or "").strip()
        if raw.isdigit() and int(raw) >= int(min_star):
            pool.append(int(pet_id))
    return random.choice(pool) if pool else None


def _insert_gift_pet(connection, player, pet_id: int) -> bool:
    """Put one pet of `pet_id` into the roster; False when the roster is full."""
    capacity = player["pet_capacity"] if "pet_capacity" in player.keys() else None
    if capacity is None:
        capacity = connection.execute(
            "SELECT pet_capacity FROM players WHERE id=?", (player["id"],)
        ).fetchone()[0]
    held = connection.execute(
        "SELECT COUNT(*) FROM pets WHERE player_id=?", (player["id"],)
    ).fetchone()[0]
    if held >= capacity:
        return False
    record = config_tables._table("pet.txt").get(pet_id) or {}
    icon_raw = str(record.get("iconId", "") or "").strip()
    star_raw = str(record.get("star", "") or "").strip()
    skills = str(record.get("skills", "") or "").strip() or "101:5101"
    connection.execute(
        """INSERT INTO pets (player_id, pet_id, lv, star, pro, icon, skills,
                             generation, buffs)
           VALUES (?, ?, 1, ?, 1, ?, ?, 1, ?)""",
        (player["id"], pet_id,
         int(star_raw) if star_raw.isdigit() else 1,
         int(icon_raw) if icon_raw.isdigit() else pet_id,
         skills, _buffs_for_pet(pet_id, 1)),
    )
    return True


# LOCAL DEFAULT box payouts. prop.txt's `value` selects the tier; eggs/wish coins
# hand out a pet, treasure chests hand out silver.
LOCAL_BOX_EGG_STAR = {
    101: 4, 102: 5, 103: 6, 104: 7, 105: 8, 106: 10, 107: 12,
    1001: 4, 1002: 5,
}
LOCAL_BOX_SILVER = {1: 1000, 2: 5000, 3: 20000, 4: 100000, 5: 500000,
                    6: 1000000, 201: 5000, 202: 5000}


def _open_prop_box(connection, player, amount: int) -> dict | None:
    """Open a type-15 prop (宝箱/许愿硬币/宠物蛋) and pay it out.

    Returns the GameUtil.getBox payload (`box_type` plus its value fields), or None
    when the reward cannot be delivered (roster full), so the caller can leave the
    item in the bag instead of silently eating it.
    """
    star_need = LOCAL_BOX_EGG_STAR.get(int(amount))
    if star_need is None and 500 <= int(amount) <= 599:
        # 波利婴儿车 / 摇篮 / 钢蛋: a random 4-star-and-up creature.
        star_need = 4
    if star_need is not None:
        pet_id = _pet_by_star(int(star_need))
        if pet_id is None or not _insert_gift_pet(connection, player, pet_id):
            return None
        return {"box_type": 2, "id": pet_id, "num": 1, "point": 0, "crystal": 0}
    silver = LOCAL_BOX_SILVER.get(int(amount), 500)
    connection.execute(
        "UPDATE players SET point = point + ? WHERE id = ?", (silver, player["id"])
    )
    return {"box_type": 3, "id": 0, "num": 0, "point": silver, "crystal": 0}


def _player_use_goods(database_path: Path) -> Response:
    """USE_GOODS (50) from the bag: `index` is the inventory row id, `index1` the
    selected pet id (0 when no target).

    The effect kind comes from prop.txt's `type` column (7 hunt AP, 5 pet exp,
    14 bag capacity, 15 box/egg/wish, 16-17 currency bags) and the amount from
    `value`; `useType` decides the usage context (2 = on a pet, 1 = on the
    hunter/home) and both directions are enforced below, because the client only
    enforces it by greying out grid cells.
    """
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
        if row is None or row["quantity"] <= 0:
            return _pet_error(400)
        prop = _prop_effect_rules(row["item_id"])
        if prop is None or row["team"] not in (1, 2):
            # Items this local server has no rule for stay in the bag untouched.
            return _pet_error(100)
        effect = prop["type"]
        amount = prop["value"]
        if row["item_type"] != effect or row["item_type"] == 0:
            # Self-heal rows seeded with item_type=0 so the bag's clickability
            # and our guard agree from now on.
            connection.execute(
                "UPDATE inventory SET item_type = ?, use_type = ? WHERE id = ?",
                (effect, prop["use_type"], row["id"]),
            )

        # prop.txt `useType` is the usage context: 2 = used on a pet, 1 = used on
        # the hunter/home. The client only enforces this through which grid cell
        # it lets you tap, so the server has to reject the mismatched direction —
        # otherwise pet food can be eaten from the home screen (target 0) and a
        # silver bag can be "fed" to a pet.
        use_type = prop["use_type"]
        if target <= 0 and use_type == 2:
            # 506 is the bundled "没有这只宠物" error; using a pet item from the
            # home screen has no target pet, so it reads correctly to the player.
            return _pet_error(506)
        if target > 0 and use_type == 1:
            return _pet_error(100)

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
            while lv < LOCAL_MAX_PET_LEVEL:
                need = exp_to_next(lv)
                if exp < need:
                    break
                exp -= need
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
        elif effect == 15:  # 宝箱 / 许愿硬币 / 宠物蛋
            box = _open_prop_box(connection, player, amount)
            if box is None:
                return _pet_error(300)   # bag or roster full
            # BagListUI.as:502-540 feeds `param2.value` straight into
            # GameUtil.getBox, which reads box_type/id/num/point/crystal — so the
            # value field is an OBJECT here, not the usual delta number.
            payload = {"value": box}
        else:
            return _pet_error(100)

        if row["quantity"] > 1:
            connection.execute(
                "UPDATE inventory SET quantity = quantity - 1 WHERE id = ? AND quantity > 0",
                (row["id"],),
            )
        else:
            connection.execute(
                "DELETE FROM inventory WHERE id = ? AND quantity <= 1", (row["id"],)
            )
        ht_ap = connection.execute(
            "SELECT ht_ap FROM players WHERE id = ?", (player["id"],)
        ).fetchone()["ht_ap"]
    # BagListUI.as:389-580 switches on param2.type to pick the result popup
    # (5/7/14/16/17 -> exp/AP/bag/point/crystal). Omitting it meant the item was
    # consumed and the effect applied, but the player got no feedback at all.
    payload["type"] = effect
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
    """ON_EQUIP (37): wear the equipment row and refresh the home screen.

    The client never re-requests showId=2 after equipping: EquipInfoUI.as:337-341
    sends 37 and synchronously flows back to GAME_HOME, and Navigator only calls
    request() on a CMD_BACK pop (Navigator.as:336-347, :988-1005). Because
    MainUI.as:317-318 forwards an unhandled 37 to the current screen's readDatas,
    the response body *is* the refresh mechanism — so it has to carry the same
    shape as command 2, not {"value":"ok"}.
    """
    uid = _request_value("uid")
    try:
        item_index = int(_request_value("index", ""))
    except ValueError:
        return _pet_error(100)

    with _connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT id, sex FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        row = _inventory_row(connection, player["id"], item_index)
        if row is None or row["team"] != 3:
            return _pet_error(400)
        record = config_tables.equip_record(row["item_id"])
        item_sex = config_tables.equip_sex(record) if record else None
        if item_sex is not None and player["sex"] != item_sex:
            # Wearing the other sex's row would stack its sprite onto a mismatched
            # base triple (equip.txt keeps one row per sex with its own imageId).
            counterpart = config_tables.equip_same_slot_other_sex(row["item_id"])
            if counterpart is None:
                return _pet_error(100)
            counterpart_record = config_tables.equip_record(counterpart)
            connection.execute(
                "UPDATE inventory SET item_id = ?, icon = ? WHERE id = ?",
                (counterpart, config_tables.equip_icon(counterpart_record), row["id"]),
            )
            row = _inventory_row(connection, player["id"], item_index)
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
        player_row = connection.execute(_PLAYER_ROW_SQL, (uid,)).fetchone()
        payload = _player_payload(connection, player_row)
    payload["value"] = "ok"
    return _protocol_response(37, payload)


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
# LOCAL DEFAULT: the original per-map spawn table is not recoverable, so each map
# names a REAL monster.txt row as its base. Ids 1..6 are used because
# map_icon.swf ships icon_map_1..27 and the client draws icon_map_<map id>.
LOCAL_HUNT_MAPS = {
    1: {"name": "樱花之岛1", "world": 1, "cost": 1, "monster": 1},    # L1
    2: {"name": "樱花之岛2", "world": 1, "cost": 1, "monster": 3},    # L10
    3: {"name": "樱花之岛3", "world": 1, "cost": 1, "monster": 4},    # L40
    4: {"name": "神龙之国1", "world": 2, "cost": 1, "monster": 7},    # L60
    5: {"name": "神龙之国2", "world": 2, "cost": 1, "monster": 10},   # L80
    6: {"name": "神龙之国3", "world": 2, "cost": 1, "monster": 12},   # L100
}
# Maps unlock in this order: the first is always open, the rest need the previous
# one cleared.
LOCAL_HUNT_ORDER = (1, 2, 3, 4, 5, 6)
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
    # IllustrationInfoUI.as:162 does getDefinition("p" + param2.icon) itself, so
    # this must be a bare number; without it the detail page silently rendered no
    # artwork (the failure is swallowed by a catch block).
    record = config_tables._table("pic.txt").get(gid) or {}
    raw_icon = str(record.get("iconId", "") or "").strip()
    icon = int(raw_icon) if raw_icon.lstrip("-").isdigit() and int(raw_icon) > 0 else gid
    return _protocol_response(26,{"id":gid,"icon":icon,"need_money":0,"is_reward":LOCAL_PICS[gid]["reward"],"pics":[{"id":gid,"icon":icon,"is_reward":LOCAL_PICS[gid]["reward"]}]})


def _achievement_list(database_path: Path) -> Response:
    return _protocol_response(107,{"id":1,"need_money":0,"is_reward":0,"pics":[]})


# LOCAL DEFAULT: the original server was shared by many players; this one has a
# single hunter. These NPC guilds keep the 公会 board from being an empty page and
# give the member list something to render. They are not joinable (ids 9xxx are
# outside the guilds table and _join is never offered by the client anyway).
LOCAL_GUILD_FILLER = (
    (9001, "樱花猎人团", "风间彻", 7),
    (9002, "神龙卫队", "龙崎", 5),
    (9003, "夜市商会", "阿福", 4),
    (9004, "星光旅团", "露娜", 6),
    (9005, "无名剑客会", "剑心", 3),
)
LOCAL_GUILD_MAX_MEMBERS = 10
LOCAL_GUILD_DEFAULT_SUFFIX = "的公会"


def _guild_row(connection: sqlite3.Connection, guild_id: int):
    return connection.execute(
        "SELECT id, name, leader_player_id, max_mem_num FROM guilds WHERE id = ?",
        (guild_id,),
    ).fetchone()


def _member_count(connection: sqlite3.Connection, guild_id: int) -> int:
    return connection.execute(
        "SELECT COUNT(*) FROM players WHERE guild_id = ?", (guild_id,)
    ).fetchone()[0]


def _guild_own(database_path: Path) -> Response:
    """86 (MY_GUILD_KEY) — the player's own guild card.

    MainUI.as:212-221 only opens the page when `position` is truthy; otherwise it
    pops the bundled "还没有加入公会" alert, so a guildless player must report
    position 0 rather than an empty guild.
    """
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        p = c.execute(
            "SELECT id, nick, img, guild_id, guild_position FROM players WHERE uid=?",
            (uid,),
        ).fetchone()
        if p is None:
            return _pet_error(103)
        if not p["guild_id"]:
            return _protocol_response(86, {"guild_id": 0, "position": 0,
                                           "guild_name": "", "leader_name": "",
                                           "leader_img": p["img"], "mem_num": 0,
                                           "value": "ok"})
        guild = _guild_row(c, p["guild_id"])
        if guild is None:
            return _protocol_response(86, {"guild_id": 0, "position": 0,
                                           "guild_name": "", "leader_name": "",
                                           "leader_img": p["img"], "mem_num": 0,
                                           "value": "ok"})
        leader = c.execute(
            "SELECT nick, img FROM players WHERE id = ?",
            (guild["leader_player_id"],),
        ).fetchone()
        members = _member_count(c, guild["id"])
    return _protocol_response(86, {
        "guild_id": guild["id"],
        "guild_name": guild["name"],
        "position": p["guild_position"] or 3,
        "leader_name": (leader["nick"] if leader else "") or "",
        "leader_img": (leader["img"] if leader else "") or p["img"],
        "mem_num": members,
        "value": "ok",
    })


def _guild_list(database_path: Path) -> Response:
    """88 (GUILD_LIST_KEY) — SocietiesTopUI.as:201-218 walks `guilds[]`."""
    with _connect_database(database_path) as c:
        rows = c.execute(
            "SELECT id, name, leader_player_id, max_mem_num FROM guilds ORDER BY id"
        ).fetchall()
        guilds = []
        for row in rows:
            leader = c.execute(
                "SELECT nick FROM players WHERE id = ?", (row["leader_player_id"],)
            ).fetchone()
            guilds.append({
                "id": row["id"],
                "name": row["name"],
                "mem_num": _member_count(c, row["id"]),
                "max_mem_num": row["max_mem_num"] or LOCAL_GUILD_MAX_MEMBERS,
                "leader_name": (leader["nick"] if leader else "") or "",
            })
    for guild_id, name, leader_name, mem_num in LOCAL_GUILD_FILLER:
        guilds.append({
            "id": guild_id,
            "name": name,
            "mem_num": mem_num,
            "max_mem_num": LOCAL_GUILD_MAX_MEMBERS,
            "leader_name": leader_name,
        })
    return _protocol_response(88, {"guilds": guilds, "type": 0, "value": "ok"})


def _guild_members(database_path: Path) -> Response:
    """91 (GUILD_MEMBER_LIST_KEY) — SocietiesListUI.as:180-195 reads `list[]`."""
    uid = _request_value("uid")
    try:
        guild_id = int(_request_value("gid", "0") or 0)
    except ValueError:
        guild_id = 0
    with _connect_database(database_path) as c:
        p = c.execute(
            "SELECT id, nick, img, guild_id FROM players WHERE uid=?", (uid,)
        ).fetchone()
        if p is None:
            return _pet_error(103)
        if not guild_id:
            guild_id = p["guild_id"] or 0
        if guild_id in {entry[0] for entry in LOCAL_GUILD_FILLER}:
            # LOCAL DEFAULT filler roster for the NPC guilds above.
            name, leader, count = next(
                (e[1], e[2], e[3]) for e in LOCAL_GUILD_FILLER if e[0] == guild_id
            )
            members = [{"id": 0, "name": leader, "position": 1, "img": p["img"]}]
            for index in range(1, count):
                members.append({"id": -index, "name": "团员%02d" % index,
                                "position": 3, "img": ""})
            return _protocol_response(91, {"list": members[:10], "value": "ok"})
        rows = c.execute(
            "SELECT id, nick, img, guild_position FROM players WHERE guild_id=? ORDER BY guild_position, id",
            (guild_id,),
        ).fetchall()
    members = [
        {"id": row["id"], "name": row["nick"], "position": row["guild_position"] or 3,
         "img": row["img"] or ""}
        for row in rows
    ]
    return _protocol_response(91, {"list": members, "value": "ok"})


def _create_guild(database_path: Path) -> Response:
    """92 (CREATE_GUILD_KEY) — SocietiesTopUI.as:157 sends no parameters at all.

    The client therefore expects the server to pick the name; the resulting alert
    (ui/257) is immediately followed by a return to the board, and the player can
    rename it through 89 if they want.
    """
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        p = c.execute(
            "SELECT id, nick, guild_id FROM players WHERE uid=?", (uid,)
        ).fetchone()
        if p is None:
            return _pet_error(103)
        if p["guild_id"]:
            return _pet_error(100)  # already in one
        name = f"{p['nick'] or '猎人'}{LOCAL_GUILD_DEFAULT_SUFFIX}"
        cursor = c.execute(
            "INSERT INTO guilds (name, leader_player_id, max_mem_num, created_at)"
            " VALUES (?, ?, ?, ?)",
            (name, p["id"], LOCAL_GUILD_MAX_MEMBERS, time.strftime("%Y-%m-%d %H:%M:%S")),
        )
        c.execute(
            "UPDATE players SET guild_id = ?, guild_position = 1 WHERE id = ?",
            (cursor.lastrowid, p["id"]),
        )
    return _protocol_response(92, {"value": "ok", "guild_id": cursor.lastrowid})


def _guild_change_name(database_path: Path) -> Response:
    """89 (GUILD_CHANGE_NAME_KEY) — SocietiesMyUI.as:244 sends {index, pName}."""
    uid = _request_value("uid")
    name = (_request_value("pName") or "").strip()
    if not 1 <= len(name) <= 8:
        return _pet_error(514)  # bundled "名字不合法"
    with _connect_database(database_path) as c:
        p = c.execute(
            "SELECT id, guild_id, guild_position FROM players WHERE uid=?", (uid,)
        ).fetchone()
        if p is None:
            return _pet_error(103)
        if not p["guild_id"] or (p["guild_position"] or 0) != 1:
            return _pet_error(100)  # leader only
        c.execute("UPDATE guilds SET name = ? WHERE id = ?", (name, p["guild_id"]))
    return _protocol_response(89, {"value": "ok"})


def _quit_guild(database_path: Path) -> Response:
    """90 (QUIT_GUILD_KEY) — a sole leader disbands, everyone else just leaves."""
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        p = c.execute(
            "SELECT id, guild_id, guild_position FROM players WHERE uid=?", (uid,)
        ).fetchone()
        if p is None:
            return _pet_error(103)
        if not p["guild_id"]:
            return _pet_error(100)
        if (p["guild_position"] or 0) == 1:
            c.execute("UPDATE players SET guild_id = NULL, guild_position = 0 WHERE guild_id = ?",
                      (p["guild_id"],))
            c.execute("DELETE FROM guilds WHERE id = ?", (p["guild_id"],))
        else:
            c.execute("UPDATE players SET guild_id = NULL, guild_position = 0 WHERE id = ?",
                      (p["id"],))
    return _protocol_response(90, {"value": "ok"})


def _guild_battle(database_path: Path) -> Response:
    return _protocol_response(94,{"is_battle_on":0,"battle_turn":0,"isReward":0,"start_time":0,"end_time":0,"total_honor":0,"battle_team":{"turn":{"1":[],"2":[],"3":[]}}})


# LOCAL DEFAULT: the original game had a shared friend list. This server holds a
# single hunter, so the list would always be empty; these NPC hunters keep the
# friend screen usable and give 52/53 something to open. Their uids are prefixed
# so 52 can tell them apart from real rows.
LOCAL_FRIEND_FILLER = (
    ("npc-1", "风间彻", 12),
    ("npc-2", "龙崎", 24),
    ("npc-3", "阿福", 8),
    ("npc-4", "露娜", 35),
    ("npc-5", "剑心", 50),
)
LOCAL_FRIEND_FILLER_PETS = (1001, 2019, 1003)


def _friend_filler_entry(uid: str):
    for entry in LOCAL_FRIEND_FILLER:
        if entry[0] == uid:
            return entry
    return None


def _friend_filler_pets(level: int) -> list[dict]:
    pets = []
    table = config_tables.pet_table()
    for pet_id in LOCAL_FRIEND_FILLER_PETS:
        record = table.get(pet_id)
        if record is None:
            continue
        icon = str(record.get("iconId", "") or pet_id).strip()
        pets.append({
            "index": pet_id, "id": pet_id,
            "icon": int(icon) if icon.isdigit() else pet_id,
            "name": record.get("name", ""), "lv": max(1, int(level)),
        })
    return pets


def _friend_list(database_path: Path) -> Response:
    uid=_request_value("uid")
    try: page,size=int(_request_value("p","1")),int(_request_value("n","9"))
    except ValueError: return _pet_error(100)
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None:return _pet_error(103)
        rows=c.execute("SELECT uid,nick,lv,img FROM players WHERE id<>? ORDER BY id",(p["id"],)).fetchall()
    friends = [
        {"id": r["uid"], "state": 0, "name": r["nick"], "img": r["img"]}
        for r in rows
    ]
    friends.extend(
        {"id": friend_uid, "state": 0, "name": name,
         "img": "_".join(str(layer) for layer in _base_skin_layers(1))}
        for friend_uid, name, _level in LOCAL_FRIEND_FILLER
    )
    start = max(0, page - 1) * size
    return _protocol_response(51, {
        "player_str_id": uid,
        "friend": friends[start:start + size],
        "value": "ok",
    })


def _friend_request(database_path: Path) -> Response:
    """512/513 — add / remove a friend.

    The list is local filler, so there is no friendship table to mutate; the two
    commands just have to answer `ok` instead of falling through to the generic
    empty envelope (FriendUI re-reads the list immediately afterwards).
    """
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
    return _protocol_response(int(_request_value("showId", "512")), {"value": "ok"})


def _friend_detail(database_path: Path) -> Response:
    target=_request_value("gid"); uid=_request_value("uid")
    filler = _friend_filler_entry(target)
    if filler is not None:
        friend_uid, name, level = filler
        return _protocol_response(52, {
            "show_type": 0,
            "player": {
                "id": friend_uid, "name": name, "lv": level,
                "img": "_".join(str(layer) for layer in _base_skin_layers(1)),
            },
            "pets": _friend_filler_pets(level),
            "value": "ok",
        })
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
                   "arena_rank":_local_arena_rank(),"pic_num":pic_num,
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
        # HunterMapUI.as:206 draws `rate` as a percentage bar; it used to be a
        # hardcoded 0, so a map could be farmed forever and still read 0%.
        progress = {
            row["map_id"]: (row["kills"], row["cleared"])
            for row in c.execute(
                "SELECT map_id, kills, cleared FROM hunt_progress WHERE player_id=?",
                (p["id"],),
            )
        }
    # Sequential unlock: the first map is free, later ones need the previous clear.
    unlocked: set[int] = set()
    for position, map_id in enumerate(LOCAL_HUNT_ORDER):
        if position == 0:
            unlocked.add(map_id)
            continue
        previous = LOCAL_HUNT_ORDER[position - 1]
        if progress.get(previous, (0, 0))[1]:
            unlocked.add(map_id)
        else:
            break
    maps = []
    for map_id, info in LOCAL_HUNT_MAPS.items():
        kills, cleared = progress.get(map_id, (0, 0))
        maps.append({
            "index": map_id, "code": map_id, "id": map_id,
            "name": info["name"], "world": info["world"],
            "rate": min(100, kills * 100 // LOCAL_HUNT_CLEAR_KILLS),
            "pass": 1 if cleared else 0,
            "star": 0, "days": 0,
            "is_allown_hunt": 1 if map_id in unlocked else 0,
        })
    return _protocol_response(4, {
        "player": {"hunt_ap": p["ht_ap"], "max_hunt_ap": p["max_ht_ap"]},
        "maps": maps,
    })


def _hunter_task(database_path: Path) -> Response:
    try: hid=int(_request_value("hid",""))
    except ValueError: return _pet_error(100)
    m=LOCAL_HUNT_MAPS.get(hid)
    if m is None: return _pet_error(400)
    uid=_request_value("uid")
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,ht_ap,max_ht_ap FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
        # HunterTaskUI.as:337-375 shifts exactly TWO entries into the two battle
    # slots, so this answers the arranged squad first and fills the rest with the
    # first available pets (otherwise both slots render empty placeholders).
    # ONLY the arranged squad. Filling empty slots with ordinary pets made the
    # client believe both slots were occupied: tapping one then sent 45 ("take it
    # off"), the server cleared a slot that was already 0, and nothing changed —
    # "狩猎不能切换宠物". An empty slot must render as a placeholder so tapping it
    # opens the picker (HunterTaskUI.as:299-303).
    pets=c.execute(
        "SELECT id AS 'index',pet_id AS id,icon,name,lv FROM pets"
        " WHERE player_id=? AND squad_slot>0 AND is_locked=0"
        " ORDER BY squad_slot LIMIT 2",(p["id"],)).fetchall()
    return _protocol_response(5,{
        "id":hid,"hid":hid,"ht_ap":p["ht_ap"],"max_ht_ap":p["max_ht_ap"],
        # HunterTaskUI.as:100-101 disables the hunt/catch buttons when these
        # are not > 0, and :322 hides the plain button when rage_point hits 100.
        "isHunter":1 if p["ht_ap"] >= 1 else 0,
        "isCatch":1 if p["ht_ap"] >= 1 else 0,
        "rage_point":0,
        "pets":[_pet_list_entry(r) for r in pets],
    })


# LOCAL DEFAULT: how many monsters a hunt map spawns per battle. The client's
# BoxItem2 row holds three, so two is safe and gives each map its own group.
LOCAL_HUNT_MONSTER_COUNT = 2
# LOCAL DEFAULT: how far a map's monsters may stray from its base monster's level.
LOCAL_HUNT_LEVEL_BAND = 15
# LOCAL DEFAULT: a map reads as "cleared" after this many victories, and the map
# list shows `kills / LOCAL_HUNT_CLEAR_KILLS` as its progress percentage.
LOCAL_HUNT_CLEAR_KILLS = 10
# LOCAL DEFAULT elite encounter: chance, stat multiplier and payout multiplier.
# "无双一击" (the client's rage button) is gated on clearing one of these.
# LOCAL DEFAULT: one win fills a quarter of the meter, so 无双 lands every ~4th
# clear (every ~2nd if it was an elite encounter).
LOCAL_RAGE_GAIN_PER_WIN = 25
LOCAL_ELITE_CHANCE = 0.15
LOCAL_ELITE_SCALE = 1.6
LOCAL_ELITE_REWARD_MULT = 2


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
        # monster.txt carries a real `exp` column; hunt payouts read it instead of
        # inventing a per-level constant.
        "exp": stat("exp", 0),
    }


def _monsters_for_map(hid: int) -> list[dict[str, object]]:
    """Monster group for a hunt map.

    LOCAL_HUNT_MAPS names a base monster per map (REAL monster.txt rows); the
    group is built from monsters near that base's LEVEL, so different maps field
    different creatures — and therefore unlock different picture-book entries.
    Reading the table from the top for every map (the earlier behaviour) made all
    four maps fight the same 原味波利 and the 图鉴 could never grow past one row.

    Picking adjacent *ids* was still wrong: monster.txt is not sorted by level, so
    map 2 ended up as "lv10 + lv40" — one hunt paid 24,000 exp while a lv10 pet
    only needs 14,000, i.e. more than a level per fight, and the fight itself was
    lopsided. The band keeps a map's group level-consistent.
    """
    table = _monster_table()
    ids = sorted(int(m) for m in table)
    entry = LOCAL_HUNT_MAPS.get(hid)
    base = int(entry["monster"]) if entry else (ids[0] if ids else 0)
    base_raw = str((table.get(base) or {}).get("level", "")).strip()
    base_level = int(base_raw) if base_raw.isdigit() else 1
    # Closest levels first: walking `ids` in order would keep re-picking the
    # lowest-id cluster (map 2 was still fielding lv1/lv5 creatures for a lv10
    # base), because monster.txt's ids are unrelated to level.
    # Sort key: the base monster first, then the closest level at or above it.
    # Never below: a lv40 map should not field lv1 filler just because the band is
    # symmetric, and the map's base creature must always be in its own group.
    candidates: list[tuple[int, int, int]] = []
    for monster_id in ids:
        level_raw = str(table[monster_id].get("level", "")).strip()
        level = int(level_raw) if level_raw.isdigit() else 0
        delta = level - base_level
        if delta < 0 or delta > LOCAL_HUNT_LEVEL_BAND:
            continue
        candidates.append((0 if monster_id == base else 1, delta, monster_id))
    candidates.sort()
    picked: list[dict[str, object]] = []
    for _is_base, _distance, monster_id in candidates:
        monster = _pick_monster(monster_id)
        if monster is not None:
            picked.append(monster)
        if len(picked) >= LOCAL_HUNT_MONSTER_COUNT:
            break
    if picked and random.random() < LOCAL_ELITE_CHANCE:
        # LOCAL DEFAULT elite encounter: one flagged leader plus the ordinary pair.
        # Only an elite clear unlocks 无双一击 (rage_point == 100 in the result) and
        # it pays double exp/silver, so the "无双" button stops appearing on every
        # single hunt.
        leader = dict(picked[0])
        leader["elite"] = True
        return [leader] + picked
    return picked


def _combat_stats(pet_row) -> tuple[int, int, int]:
    """(hp, att, def) for one pet: pet.txt 六维 × 等级系数 + 强化值。

    强化只加一半到 hp/def、全量加到 att，避免高强化宠物同时变成又肉又痛。
    系数 0.006 与"同级普通怪 4~6 击"的口径一起调过（见 _monster_stats）。
    """
    stats = _pet_base_stats(pet_row["id"])
    keys = pet_row.keys()

    def pro(name: str) -> int:
        return int(pet_row[name] or 0) if name in keys else 0

    lv = max(1, int(pet_row["lv"] or 1))
    lf = 1 + 0.006 * (lv - 1)
    return (
        round(stats["hp"] * lf) + pro("pro_hp") // 2,
        round(stats["phy_att"] * lf) + pro("pro_phy_att"),
        round(stats["phy_def"] * lf) + pro("pro_phy_def") // 2,
    )


def _hunter_combat_stats(player_row, worn) -> tuple[int, int, int]:
    """猎人的战斗数值：ROLE_BASE_STATS 随等级成长 + 装备加成。

    基础值必须成长，否则 1000 级猎人仍然是 lv1 的 att10，"参战"没有意义。
    """
    stats = _role_stats(worn)
    lv = max(1, int(player_row["lv"] or 1))
    lf = 1 + 0.006 * (lv - 1)
    hp = round(ROLE_BASE_STATS["hp"] * lf) + (stats["hp"] - ROLE_BASE_STATS["hp"])
    att = round(ROLE_BASE_STATS["phy_att"] * lf) + (stats["phy_att"] - ROLE_BASE_STATS["phy_att"])
    defence = round(ROLE_BASE_STATS["phy_def"] * lf) + (stats["phy_def"] - ROLE_BASE_STATS["phy_def"])
    return hp, att, defence


def _monster_stats(level: int) -> tuple[int, int, int]:
    """LOCAL DEFAULT monster strength for one level.

    monster.txt's own hp/att/def do not scale with level at all (L10's median att
    is higher than L100's), so the curve lives here. The slopes were tuned against
    real pets: L1 monsters fall in 3-4 hits, same-level content is a win, and a
    5-level squad fighting the L40 map loses a pet.
    """
    lv = max(1, int(level or 1))
    hp = round(60 + 1.8 * (lv - 1))
    return hp, round(16 + 0.60 * (lv - 1)), round(15 + 0.15 * hp)


def _damage(att: int, defence: int, element: float = 1.0) -> int:
    return max(1, round(0.6 * att * att / (att + defence) * element))


def _battle_side(
    *,
    hunter_skin: str,
    hunter_name: str,
    hunter_lv: int,
    hunter_stats: tuple[int, int, int],
    pet_rows,
    defenders,
) -> tuple[list[dict], list[dict], dict]:
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

    Returns the two payload lists plus `combat`, the per-code stats the replay
    needs to compute each swing (the hunter participates too).
    """
    combat: dict[str, dict] = {"att": {}, "def": {}}
    hunter_hp, hunter_att, hunter_def = hunter_stats
    combat["att"][0] = {"hp": hunter_hp, "att": hunter_att, "def": hunter_def,
                        "speed": int(ROLE_BASE_STATS.get("speed", 10))}
    lead = {
        "team": 1, "code": 0, "is_pet": 0, "id": 0, "name": hunter_name,
        "lv": hunter_lv, "pre_lv": hunter_lv, "hp": hunter_hp, "img": hunter_skin,
    }

    def attacker(row, code: int) -> dict:
        hp, att, defence = _combat_stats(row)
        combat["att"][code] = {"hp": hp, "att": att, "def": defence,
                               "speed": int(_pet_base_stats(row["id"])["speed"])}
        return {
            "team": 1, "code": code, "is_pet": 1, "index": row["index"],
            "id": row["id"], "name": _pet_name(row["id"], row["name"]),
            "lv": row["lv"], "pre_lv": row["lv"], "hp": hp, "img": row["icon"],
        }

    att_list = [lead] + [attacker(r, i + 1) for i, r in enumerate(pet_rows)][:2]
    def_list = []
    for i, d in enumerate(defenders):
        mon_hp, mon_att, mon_def = _monster_stats(int(d["lv"] or 1))
        if d.get("elite"):
            mon_hp = round(mon_hp * LOCAL_ELITE_SCALE)
            mon_att = round(mon_att * LOCAL_ELITE_SCALE)
            mon_def = round(mon_def * LOCAL_ELITE_SCALE)
        combat["def"][i] = {"hp": mon_hp, "att": mon_att, "def": mon_def, "speed": 0}
        def_list.append({"team": 2, "code": i, "is_pet": 0, "id": d["id"],
                         "name": d["name"], "lv": d["lv"], "hp": mon_hp, "img": d["icon"]})
    return att_list, def_list, combat


# LOCAL DEFAULT: a same-level ordinary monster should take about four swings.
# The original damage formula is not recoverable (monster.txt's own hp/att/def do
# not scale with level at all), so the replay is budgeted rather than simulated.
LOCAL_SWINGS_PER_MONSTER = 4
LOCAL_BATTLE_STEP_LIMIT = 30
# Guard for the simulated replay: three actors plus their counters per round.
LOCAL_BATTLE_ROUND_LIMIT = 12
# skill.txt 101 = 烈焰之刃 (a real, physical skill); only used for the animation.
LOCAL_REPLAY_SKILL_ID = 101


def _battle_record(att_list, def_list, combat=None) -> list[dict]:
    """Replay steps. `combat` given -> real round-by-round simulation.

    The client does no combat maths of its own — HunterResultUI.as:421-462 hands
    each step to FightProcess, which reads the swing value from `att.skill.dm`
    (FightProcess.as:716-718, :754, :763-764) and copies `cur_hp` straight into
    the health bar. With no `skill` and an instant 0 the monster simply vanished
    at full health: the "everything dies in one hit" report.

    FightProcess.as:1066-1068 reads cur_hp/is_dead/is_revive with no guard and
    HunterResultUI.as:578 never starts the replay timer when record is empty, so
    every step must carry all three on both sides.

    Without `combat` the old fixed-budget replay is kept as a fallback.
    """
    if combat:
        return _battle_record_simulated(att_list, def_list, combat)
    attacker_hp = int(att_list[0]["hp"])
    steps: list[dict] = []
    for index, defender in enumerate(def_list):
        total = max(1, int(defender.get("hp") or 1))
        swing = max(1, round(total / LOCAL_SWINGS_PER_MONSTER))
        remaining = total
        while remaining > 0 and len(steps) < LOCAL_BATTLE_STEP_LIMIT:
            remaining = max(0, remaining - swing)
            steps.append({
                "att": {"team": 1, "code": 0, "cur_hp": attacker_hp,
                        "is_dead": False, "is_revive": False,
                        "skill": {"id": LOCAL_REPLAY_SKILL_ID, "pro": 1, "dm": swing}},
                "def": {"team": 2, "code": index, "cur_hp": remaining,
                        "is_dead": remaining <= 0, "is_revive": False},
            })
        if len(steps) >= LOCAL_BATTLE_STEP_LIMIT:
            break
    if not steps:
        steps = [{"att": {"team": 1, "code": 0, "cur_hp": attacker_hp,
                          "is_dead": False, "is_revive": False},
                  "def": {"team": 2, "code": 0, "cur_hp": 0,
                          "is_dead": True, "is_revive": False}}]
    return steps


def _battle_record_simulated(att_list, def_list, combat) -> list[dict]:
    """Both sides act: hunter and pets by speed, monsters counter the striker.

    A monster that dies on a swing does not counter, so the final step of a win is
    always a `team 2` death and `_record_is_win` can decide from the last step.
    """
    order = sorted(combat["att"], key=lambda code: -int(combat["att"][code].get("speed", 0)))
    hp = {code: int(combat["att"][code]["hp"]) for code in combat["att"]}
    mon = {index: int(combat["def"][index]["hp"]) for index in combat["def"]}
    steps: list[dict] = []
    rounds = 0
    while any(v > 0 for v in mon.values()) and any(v > 0 for v in hp.values()):
        rounds += 1
        if rounds > LOCAL_BATTLE_ROUND_LIMIT or len(steps) >= LOCAL_BATTLE_STEP_LIMIT:
            break
        acted = False
        for code in order:
            if hp[code] <= 0:
                continue
            target = next((index for index in sorted(mon) if mon[index] > 0), None)
            if target is None:
                break
            acted = True
            swing = _damage(combat["att"][code]["att"], combat["def"][target]["def"])
            mon[target] = max(0, mon[target] - swing)
            steps.append({
                "att": {"team": 1, "code": code, "cur_hp": hp[code],
                        "is_dead": False, "is_revive": False,
                        "skill": {"id": LOCAL_REPLAY_SKILL_ID, "pro": 1, "dm": swing}},
                "def": {"team": 2, "code": target, "cur_hp": mon[target],
                        "is_dead": mon[target] <= 0, "is_revive": False},
            })
            if len(steps) >= LOCAL_BATTLE_STEP_LIMIT or mon[target] <= 0:
                continue
            hit = _damage(combat["def"][target]["att"], combat["att"][code]["def"])
            hp[code] = max(0, hp[code] - hit)
            steps.append({
                "att": {"team": 2, "code": target, "cur_hp": mon[target],
                        "is_dead": False, "is_revive": False,
                        "skill": {"id": LOCAL_REPLAY_SKILL_ID, "pro": 1, "dm": hit}},
                "def": {"team": 1, "code": code, "cur_hp": hp[code],
                        "is_dead": hp[code] <= 0, "is_revive": False},
            })
            if len(steps) >= LOCAL_BATTLE_STEP_LIMIT or hp[code] <= 0:
                break
        if not acted:
            break
    if not steps:
        return [{"att": {"team": 1, "code": 0, "cur_hp": int(att_list[0]["hp"]),
                         "is_dead": False, "is_revive": False},
                 "def": {"team": 2, "code": 0, "cur_hp": 0,
                         "is_dead": True, "is_revive": False}}]
    return steps


def _record_is_win(record: list[dict]) -> bool:
    """胜 = 最后一步是"守方(team 2)被打死"；否则是攻方阵亡或未打完。"""
    if not record:
        return False
    last = record[-1]
    return last["def"]["team"] == 2 and bool(last["def"]["is_dead"])


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


def _hunt_map_unlocked(database_path: Path, uid: str, map_id: int) -> bool:
    """Sequential gate: the first map is open, each later one needs the previous clear."""
    if map_id not in LOCAL_HUNT_ORDER:
        return True
    position = LOCAL_HUNT_ORDER.index(map_id)
    if position == 0:
        return True
    previous = LOCAL_HUNT_ORDER[position - 1]
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return False
        row = c.execute(
            "SELECT cleared FROM hunt_progress WHERE player_id=? AND map_id=?",
            (player["id"], previous),
        ).fetchone()
    return bool(row and row["cleared"])


def _hunter_fight(database_path: Path) -> Response:
    try: hid=int(_request_value("hid",""))
    except ValueError: return _pet_error(100)
    if hid not in LOCAL_HUNT_MAPS: return _pet_error(400)
    if not _hunt_map_unlocked(database_path, _request_value("uid"), hid): return _pet_error(400)
    uid=_request_value("uid")
    monsters=_monsters_for_map(hid)
    if not monsters: return _pet_error(400)
    with _connect_database(database_path) as c:
        p=c.execute("SELECT id,nick,lv,sex,ht_ap,max_ht_ap,rage_point FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
        if p["ht_ap"] < 1: return _pet_error(100)
        c.execute("UPDATE players SET ht_ap=ht_ap-1 WHERE id=?",(p["id"],))
        ap=p["ht_ap"]-1
        worn=_worn_equipment(c,p["id"])
        rows=c.execute("SELECT id AS 'index',pet_id AS id,icon,name,lv,pro_hp,pro_speed,pro_phy_att,pro_mag_att,pro_phy_def,pro_mag_def FROM pets WHERE player_id=? AND battle_state=0 AND is_locked=0 ORDER BY id LIMIT 2",(p["id"],)).fetchall()
        # Resolve the replay BEFORE paying anything: the outcome decides the payout.
        att_list, def_list, combat = _battle_side(
            hunter_skin=_role_skin_string(worn,p["sex"]),
            hunter_name=p["nick"] or "猎人",
            hunter_lv=p["lv"] or 1,
            hunter_stats=_hunter_combat_stats(p, worn),
            pet_rows=rows,
            defenders=monsters,
        )
        record=_battle_record(att_list, def_list, combat)
        is_win=_record_is_win(record)
        # LOCAL DEFAULT rewards; the original hunt payout table is not recoverable.
        # REAL values: use the monster table's own exp column when present.
        # A lost hunt still costs the AP but pays a tenth of the exp, no silver and
        # no picture-book entry (you did not defeat them).
        base_exp=sum(
            int(m.get("exp") or 0) or LOCAL_HUNT_EXP_PER_LEVEL * int(m["lv"])
            for m in monsters
        )
        elite_fight=any(m.get("elite") for m in monsters)
        if elite_fight:
            base_exp *= LOCAL_ELITE_REWARD_MULT
        exp_reward=base_exp if is_win else base_exp // 10
        point_reward=(LOCAL_HUNT_POINT_REWARD*(sum(m["lv"] for m in monsters) or 1)
                      * (LOCAL_ELITE_REWARD_MULT if elite_fight else 1)
                      if is_win else 0)
        _credit_battle_rewards(c,p["id"],point=point_reward,crystal=0)
        # The pets that actually fought gain the battle exp, so levelling (and the
        # evolution level gates) can advance through normal play.
        pet_exp=_grant_pet_exp(c,[r["index"] for r in rows],exp_reward)
        if is_win:
            # Only the entries unlocked by THIS hunt may pop the 图鉴 banner; the
            # response used to list every monster in the fight, so an already
            # registered creature re-popped "获得图鉴" on every single hunt.
            newly_unlocked = set(_unlock_pic(
                c, p["id"], [entry["id"] for entry in _pic_entries(monsters)]
            ))
        # Per-map progress, so the map list's bar actually moves.
        c.execute(
            "INSERT INTO hunt_progress (player_id, map_id, kills, cleared) VALUES (?,?,?,0)"
            " ON CONFLICT(player_id, map_id) DO UPDATE SET kills = kills + 1",
            (p["id"], hid, 1 if is_win else 0),
        )
        if is_win:
            c.execute(
                "UPDATE hunt_progress SET cleared = 1"
                " WHERE player_id = ? AND map_id = ? AND kills >= ?",
                (p["id"], hid, LOCAL_HUNT_CLEAR_KILLS),
            )
        # FightResultItem.as:211-215 feeds `rage_point` into PercentUItem and :169
        # gates the 无双一击 button on ==100, so one value drives both the bar and
        # the button. It therefore accumulates across hunts: each win adds a
        # chunk, 100 triggers 无双 and spends the meter. Hardcoding it to 100 made
        # 无双 fire on every single hunt; hardcoding it to 0 (elite-only) put the
        # progress bar back at zero, which was the earlier complaint.
        rage_gain = LOCAL_RAGE_GAIN_PER_WIN * (2 if elite_fight else 1) if is_win else 0
        stored_rage = int(p["rage_point"] or 0) if "rage_point" in p.keys() else 0
        rage_after = min(100, stored_rage + rage_gain) if is_win else stored_rage
        if rage_after >= 100:
            # Spend the meter: this fight is the 无双 one, the next starts empty.
            c.execute("UPDATE players SET rage_point = 0 WHERE id = ?", (p["id"],))
        elif rage_gain:
            c.execute("UPDATE players SET rage_point = ? WHERE id = ?", (rage_after, p["id"]))

    pic=[
        entry for entry in _pic_entries(monsters)
        if is_win and entry["id"] in newly_unlocked
    ]
    return _protocol_response(6,{
        "is_win":1 if is_win else 0,"hunt_type":1,"map_id":hid,"monster_group":len(def_list)+3,
        "att_list":att_list,"def_list":def_list,"record":record,
        "ht_ap":ap,"max_ht_ap":p["max_ht_ap"],"ap_goods_index":0,
        "rage_point":rage_after,
        "finish_rate":100 if is_win else 0,"pic":pic,
        "reward_exp":exp_reward,"reward_point":point_reward,"reward_crystal":0,
        "pet_exp":pet_exp,
        "reward_rate":1 if is_win else 0,"reward_goods":[],
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


def _pet_grows_range(pet_id: int) -> tuple[int, int]:
    """pet.txt `grows` is a `lo:hi` roll range for the six growth values.

    Low-star species use "0:30", but high stars use e.g. "40:120", so callers must
    NOT assume lo == 0 (doing so graded every high-star pet as "中" or better).
    """
    record = config_tables.pet_record(pet_id) or {}
    parts = [part.strip() for part in str(record.get("grows", "") or "").split(":")]
    if len(parts) == 2 and all(part.lstrip("-").isdigit() for part in parts):
        lo, hi = int(parts[0]), int(parts[1])
        return (lo, hi) if hi > lo else (lo, max(lo, hi))
    return 0, 0


def _gw_rate(total: int, lo: int, hi: int) -> int:
    """1..5 -> ui.txt 51-55 (渣/低/中/高/超), normalised against the pet's range."""
    span = 6 * (hi - lo)
    if span <= 0:
        return 1
    return max(1, min(5, math.ceil((total - 6 * lo) / span * 5)))


def _buffs_for_pet(pet_id: int, generation: int = 1) -> str:
    """Pick traits from pet.txt `buffSkills`.

    help.txt id 10 caps the trait count at floor(sqrt(世代)) + 1, so a first
    generation pet carries two of them. Without this `pets.buffs` stayed empty and
    the 遗忘卡牌 item (10034) always answered error 522.
    """
    record = config_tables.pet_record(pet_id) or {}
    tokens = [token for token in str(record.get("buffSkills", "") or "").split(":") if token.isdigit()]
    cap = min(30, math.isqrt(max(1, int(generation or 1))) + 1)
    return ":".join(tokens[:cap])


def _pet_energy(pet_id: int) -> int:
    record = config_tables.pet_record(pet_id) or {}
    raw = str(record.get("energy", "") or "").strip()
    return int(raw) if raw.isdigit() else 0


def _roll_pet_traits(pet_id: int, generation: int = 1) -> dict[str, object]:
    """LOCAL DEFAULT individual variation for a freshly caught creature.

    pet.txt fixes the species (six stats, star, skill pool, trait pool) and `grows`
    is the growth roll range, so what legitimately differs between two individuals
    is rolled here. The old INSERT wrote `pro` as a literal 1, and `pro` is the
    ELEMENT (ui.txt 29 原 / 33 火 / 31 草 / 32 水 / 34 土), which is why every
    catch showed up as 火 with identical growth, skills and no traits.
    """
    record = config_tables.pet_record(pet_id) or {}
    lo, hi = _pet_grows_range(pet_id)
    growth = [random.randint(lo, hi) for _ in range(6)] if hi > 0 else [0] * 6
    pool = [token for token in str(record.get("skills", "") or "").split(":") if token.isdigit()]
    if pool:
        keep = min(len(pool), random.randint(2, 4))
        born = ":".join(pool[i] for i in sorted(random.sample(range(len(pool)), keep)))
    else:
        born = "101:5101"
    return {"pro": random.randint(0, 4), "gw": growth, "skills": born,
            "buffs": _buffs_for_pet(pet_id, generation)}


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
        rolled=_roll_pet_traits(pet_id, 1)
        cursor=c.execute(
            """INSERT INTO pets (player_id, pet_id, lv, star, pro, icon, skills, generation,
                                 nature, buffs,
                                 gw_hp, gw_speed, gw_phy_att, gw_mag_att, gw_phy_def, gw_mag_def)
               VALUES (?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?)""",
            (p["id"],pet_id,level,int(star) if star.isdigit() else 1,
             rolled["pro"],
             int(icon) if icon.isdigit() else pet_id,
             rolled["skills"],
             random.choice(nature_ids),
             rolled["buffs"],
             *rolled["gw"]),
        )
        index=cursor.lastrowid
        # Catching registers the creature in the picture book, which is what the
        # picStep milestones count.
        newly = set(_unlock_pic(c, p["id"], [pet_id]))
    # Only a FIRST registration may pop the 获得图鉴 banner. This used to list the
    # creature unconditionally, so every catch re-announced an entry the player had
    # registered long ago ("捕捉成功会弹出来获得图鉴呢？我不是已经解锁过图鉴了嘛").
    return _protocol_response(7,{
        "value":"ok","is_success":1,"hid":hid,
        "index":index,"id":pet_id,"icon":int(icon) if icon.isdigit() else pet_id,
        "name":_pet_name(pet_id), "lv":level,
        "pic":[entry for entry in _pic_entries([monster]) if entry["id"] in newly],
    })


def _explore_map_table() -> dict:
    """REAL rows from the shipped exploreMap.txt.

    Replaces the earlier hardcoded LOCAL_EXPLORE_MAPS placeholder: the client
    table carries name, worldId, terrain, star and the reward columns, and
    ExplorePveUI.as:385 resolves map_id through getConfigValue("exploreMap",
    map_id, "iconId"), so the ids have to be the real ones.
    """
    return config_tables._table("exploreMap.txt")


def _explore_reference_level(gid: int) -> int:
    """LOCAL DEFAULT: how strong an expedition map's monsters are.

    exploreMap.txt's `star` cell is a per-difficulty band string shared by every
    row ("1500:1000:700:500"), so the only honest progression signal is the map's
    position inside its own world: first map ~lv10, each later one +10.
    """
    table = _explore_map_table()
    world = _explore_map_world(gid)
    siblings = sorted(m for m in table if _explore_map_world(m) == world)
    try:
        index = siblings.index(gid)
    except ValueError:
        index = 0
    return LOCAL_EXPLORE_LEVEL_BASE + LOCAL_EXPLORE_LEVEL_PER_STAR * index


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
        with _connect_database(database_path) as c:
            # Newest rental first: renting another mount is how the player switches,
            # and row id order is the only "recent" signal the schema carries.
            rented = [row["equip_id"] for row in c.execute(
                "SELECT equip_id FROM explore_rented WHERE player_id=? AND slot_type=1"
                " ORDER BY id DESC",
                (player_id,),
            )]
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
        p=c.execute(
            "SELECT id,nick,lv,sex,point,money,cur_explore_map,explore_ap,max_explore_ap"
            " FROM players WHERE uid=?",(uid,)).fetchone()
        if p is None: return _pet_error(103)
        if gid is None:
            gid=p["cur_explore_map"]
        m=_explore_map_row(gid)
        if m is None: return _pet_error(400)
        # An expedition costs one stamina point; the client renders the value the
        # response reports, so it has to be the post-spend number.
        if (p["explore_ap"] or 0) < 1: return _pet_error(100)
        explore_ap = p["explore_ap"] - 1
        max_explore_ap = p["max_explore_ap"] or LOCAL_DEFAULT_EXPLORE_AP
        if p["point"] < m["cost_point"] or p["money"] < m["cost_money"]: return _pet_error(403)
        c.execute("UPDATE players SET point=point-?,money=money-?,cur_explore_map=?,explore_ap=? WHERE id=?",
                  (m["cost_point"],m["cost_money"],gid,explore_ap,p["id"]))
        # exploreMap.txt's `star` column is a per-difficulty band string
        # ("1500:1000:700:500", identical on every row), so it cannot drive the
        # spawn level. Use the map's position inside its world, but never throw a
        # low-level squad at content far above it: an expedition is rubber-banded
        # to the squad's own level + the hunt band.
        squad_lv = c.execute(
            "SELECT COALESCE(MAX(lv), 1) FROM pets"
            " WHERE player_id=? AND battle_state=0 AND is_locked=0",
            (p["id"],),
        ).fetchone()[0]
        reference_lv = min(
            _explore_reference_level(gid),
            int(squad_lv) + LOCAL_HUNT_LEVEL_BAND,
        )
        defenders = _defenders_for_level(1, reference_lv)
        if defenders and random.random() < LOCAL_ELITE_CHANCE:
            # 探险也吃精英遭遇：领队 ×1.6，奖励翻倍（与狩猎同一套开关）。
            leader = dict(defenders[0])
            leader["elite"] = True
            defenders = [leader] + defenders
        elite_fight = any(d.get("elite") for d in defenders)
        worn = _worn_equipment(c, p["id"])
        pet_rows = c.execute(
            'SELECT id AS "index", pet_id AS id, icon, name, lv, pro_hp, pro_speed,'
            ' pro_phy_att, pro_mag_att, pro_phy_def, pro_mag_def FROM pets'
            ' WHERE player_id=? AND battle_state=0 AND is_locked=0 ORDER BY id LIMIT 2',
            (p["id"],)).fetchall()
        att_list, def_list, combat = _battle_side(
            hunter_skin=_role_skin_string(worn, p["sex"] or 1),
            hunter_name=p["nick"] or "猎人",
            hunter_lv=p["lv"] or 1,
            hunter_stats=_hunter_combat_stats(p, worn),
            pet_rows=pet_rows,
            defenders=defenders,
        )
        record = _battle_record(att_list, def_list, combat)
        is_win = _record_is_win(record)
        # REAL rewards from exploreMap.txt's passReward* columns (the earlier
        # implementation paid a flat LOCAL_EXPLORE_REWARD and no items at all).
        elite_mult = LOCAL_ELITE_REWARD_MULT if elite_fight else 1
        reward_point = (m["pass_reward_point"] + LOCAL_EXPLORE_BONUS_POINT) * elite_mult if is_win else 0
        reward_crystal = m["pass_reward_crystal"] * elite_mult if is_win else 0
        parsed_goods = _parse_map_goods(m["pass_reward_goods"]) if is_win else []
        reward_goods = _grant_goods(
            c, p["id"],
            [(gid, num, icon) for kind, gid, num, icon in parsed_goods if kind == 1],
        )
        # kind 2 is a pet reward; kind 3 registers a picture-book entry (no item row).
        pic_gifts = [gid for kind, gid, _num, _icon in parsed_goods if kind == 3]
        if pic_gifts:
            _unlock_pic(c, p["id"], pic_gifts)
            reward_goods = reward_goods + [{"id": gid, "num": 1} for gid in pic_gifts]
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
        explore_rows=[r for r in c.execute(
            "SELECT id, pet_id FROM pets WHERE player_id=? AND battle_state=0 AND is_locked=0 ORDER BY id LIMIT 2",
            (p["id"],))]
        explore_pets=[r["id"] for r in explore_rows]
        # _pet_energy takes the pet.txt SPECIES id, not the pets.id row id.
        lead_species=int(explore_rows[0]["pet_id"]) if explore_rows else 0
        # A quarter of a level for the squad's own level (the old flat 300,000 was
        # 60 levels at lv1 on the new curve).
        squad_lv = c.execute(
            "SELECT COALESCE(MAX(lv), 1) FROM pets"
            " WHERE player_id=? AND battle_state=0 AND is_locked=0",
            (p["id"],),
        ).fetchone()[0]
        _grant_pet_exp(
            c, explore_pets,
            _battle_exp(squad_lv, LOCAL_EXPLORE_EXP_SHARE)
            * (LOCAL_ELITE_REWARD_MULT if elite_fight else 1)
            if is_win
            else _battle_exp(squad_lv, LOCAL_EXPLORE_EXP_SHARE) // 10,
        )
    horse=_explore_horse(database_path, p["id"])
    return _protocol_response(103,{
        # ExploreUI.as:100 routes to the battle screen only when event_type == 1;
        # anything else (0 here previously) went to ExploreEventResultUI, which
        # never renders a fight, so the expedition silently produced a black page.
        "value":"ok","event_type":_explore_event_type(gid),
        "world":m["world"],"world_id":m["world"],
        "is_tired":0,
        "is_finish":1 if is_win else 0,"explore_ap":explore_ap,"max_explore_ap":max_explore_ap,
        "now_discover_rate":0,"add_discover_rate":0,
        "need_discover_rate":m["need_discover_rate"],
        "energy":_pet_energy(lead_species),"cost_energy":0,"add_energy":0,
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
            "is_win":1 if is_win else 0,"hunt_type":1,"map_id":gid,
            "monster_group":len(def_list)+3,
            "att_list":att_list,"def_list":def_list,"record":record,
            "reward_point":reward_point,"reward_crystal":reward_crystal,
            "reward_goods":reward_goods,"pic":[],
        },
    })


def _explore_list(database_path: Path) -> Response:
    uid=_request_value("uid")
    # ExploreMapListUI.as:177-185 sends {ttype:2, gid:<worldId>, p, n}: the world
    # id travels in `gid`, while ttype is just the page kind. Reading ttype as the
    # world made page 2 of world 1 silently switch to world 2 and replay its first
    # screen forever.
    #
    # The request can also arrive with a missing/garbage `gid`: MainUI.as:262-272
    # answers the world list without calling readDatas, so ExploreMapListUI may
    # still have an empty `data.world` when it re-requests. Answering -1:100 there
    # looked like "探险点不进去", so fall back to world 1 instead of failing.
    def _int_param(name: str, default: int) -> int:
        raw = str(_request_value(name, "") or "").strip()
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    page_type = _int_param("ttype", 1)
    world = _int_param("gid", page_type if page_type > 1 else 1)
    page = _int_param("p", 1)
    size = _int_param("n", 9)
    if page < 1 or not 1 <= size <= 9: return _pet_error(100)
    with _connect_database(database_path) as c:
        player = c.execute(
            "SELECT id,explore_ap,max_explore_ap FROM players WHERE uid=?", (uid,)
        ).fetchone()
        if player is None:
            return _pet_error(103)
        # Refill lazily: a solo offline server has no scheduled job, so topping up
        # on read keeps the HUD from being stuck at 0 after a few expeditions.
        if (player["explore_ap"] or 0) < (player["max_explore_ap"] or 0):
            c.execute(
                "UPDATE players SET explore_ap=max_explore_ap WHERE id=?", (player["id"],)
            )
            player = c.execute(
                "SELECT id,explore_ap,max_explore_ap FROM players WHERE id=?", (player["id"],)
            ).fetchone()
    # ttype=1 is the WORLD picker: MainUI.as:262-272 only routes to WorldMapUI when
    # the response carries type == 1, otherwise it goes straight to a map list.
    # Without this the player was locked into world 1 forever — and world 1 is
    # almost entirely terrain 1, which is the "探险全是平原" report.
    # REVERTED: answering ttype=1 with the world picker (type 1) sent the client
    # into WorldMapUI, where nothing responded to taps — 探险 became unenterable.
    # MainUI.as:262-272 routes on `type`, and the world screen's own buttons never
    # fired a request, so the player was stuck. Until that screen is understood we
    # keep the previously working behaviour: ttype=1 answers world 1's map list
    # (type 2). World switching still works when `gid` is sent explicitly.

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
    # An exhausted page must answer an empty list, not an error: the client only
    # gates the next-page button on "this page came back full"
    # (ExploreMapListUI.as:168-175), so an error would pop up instead of ending
    # the list.
    page_rows = rows[(page - 1) * size: page * size]
    return _protocol_response(98,{
        "type": 2,
        "world":world,
        "explore_ap":player["explore_ap"],
        "max_explore_ap":player["max_explore_ap"],
        "list":page_rows,
    })


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
        # 结算已到期的训练：把开始时就记下的 train_gain 写进对应两项强化值，
        # 然后清空时间与欠账。这样玩家看到的行为是"倒计时走完、下次打开养成页
        # 属性才涨"，与界面预期一致（训练进行中不会提前加）。
        finished = c.execute(
            "SELECT id, train_type, train_gain, pro_hp, pro_speed, pro_phy_att,"
            " pro_mag_att, pro_phy_def, pro_mag_def FROM pets"
            " WHERE player_id=? AND train_end>0 AND train_end<=?",
            (player["id"], now),
        ).fetchall()
        for pet in finished:
            gain = int(pet["train_gain"] or 0)
            for column in LOCAL_TRAIN_GAIN.get(int(pet["train_type"] or 0), ()):
                current = int(pet[column] or 0)
                step = min(gain, max(0, LOCAL_PRO_CAP - current))
                if step:
                    c.execute(f"UPDATE pets SET {column} = ? WHERE id = ?",
                              (current + step, pet["id"]))
            c.execute(
                "UPDATE pets SET train_state=0, train_type=0, train_end=0, train_gain=0"
                " WHERE id=?", (pet["id"],)
            )
        training = c.execute(
            """SELECT id AS "index", pet_id AS id, icon, name, lv, train_state, train_end
               FROM pets WHERE player_id=? AND train_end>?
               ORDER BY train_end LIMIT 9""",
            (player["id"], now),
        ).fetchall()
    # Only RUNNING runs occupy a slot. Filling the empty slots with the roster
    # looked nicer but made the page unusable: DevelopItem.as:171 sets
    # mouseEnabled=false when a slot has data, so with nine pets every slot was
    # filled and none could be tapped to pick a pet — "宠物无法养成".
    # An empty slot draws clip_wand (DevelopItem.as:178) and stays clickable,
    # which is exactly the "choose a pet to train" affordance.
    rows = list(training)
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
            "num": 0, "energy": _pet_energy(row["id"])}


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
        payload={"index":idx,"id":row["pet_id"],"icon":row["icon"],"total_tp":total,"energy":_pet_energy(row["pet_id"]),"hp_tp":row["pro_hp"],"speed_tp":row["pro_speed"],"phy_att_tp":row["pro_phy_att"],"mag_att_tp":row["pro_mag_att"],"phy_def_tp":row["pro_phy_def"],"mag_def_tp":row["pro_mag_def"]}
    return _protocol_response(9,payload)


# LOCAL DEFAULT: the original duration/gain tables are not in the shipped config
# (the config bundle has no training table at all), so these are our numbers.
LOCAL_TRAIN_SECONDS = 600
# prop.txt 10505's remark states a single reinforcement tops out around 1000.
LOCAL_PRO_CAP = 1000
# LOCAL DESIGN: 技能合成的"追加"概率 —— 副宠独有的技能族按此概率并入主宠。
LOCAL_SKILL_ADD_CHANCE = 0.5
# LOCAL DEFAULT gains per training type; the original duration/gain tables are
# not recoverable. Keys match DevelopPetInfoUI's three buttons (ttype 1/2/3).
# ttype -> the two reinforcement columns that run raises (ui.txt 63-68 labels).
LOCAL_TRAIN_GAIN = {
    1: ("pro_hp", "pro_speed"),
    2: ("pro_phy_att", "pro_mag_att"),
    3: ("pro_phy_def", "pro_mag_def"),
}


def _train_gain(lv: int) -> int:
    """LOCAL DEFAULT per-run reinforcement gain, scaled by pet level."""
    return 5 + max(0, int(lv)) // 20


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
        # 训练收益先记账（train_gain），到点由 _training_overview 发放。
        # 直接开始就加属性会让"训练中"和"练完"没有区别，也看不出倒计时的意义。
        per_run = _train_gain(row["lv"] or 1) * (3 if ttype == 3 else 1)
        columns = LOCAL_TRAIN_GAIN[ttype]
        applied: dict[str,int] = {}
        for column in columns:
            current = int(row[column] or 0)
            applied[column] = min(per_run, max(0, LOCAL_PRO_CAP - current))
        if not any(applied.values()):
            return _pet_error(100)  # 已到上限，不白占冷却
        c.execute(
            "UPDATE pets SET train_state=?, train_type=?, train_end=?, train_gain=?"
            " WHERE id=?",
            (ttype, ttype, now + LOCAL_TRAIN_SECONDS, applied[columns[0]], idx),
        )
        reward_point = 50 * int(row["lv"] or 1) if ttype == 2 else 0
        reward_exp = 10 * int(row["lv"] or 1) if ttype == 3 else 0
        if reward_point:
            c.execute("UPDATE players SET point = point + ? WHERE id = ?", (reward_point, player["id"]))
        pet={"id":row["pet_id"],"icon":row["icon"],"name":_pet_name(row["pet_id"], row["name"])}
    if reward_exp:
        with _connect_database(database_path) as c:
            _grant_pet_exp(c, [idx], reward_exp)
    # "pro_hp" -> "add_hp_tp". The client field names carry a "_tp" suffix
    # (DevelopResultUI.as:164-336 reads add_hp_tp and friends).
    adds={f"add_{column.split('_', 1)[1]}_tp": value for column, value in applied.items()}
    return _protocol_response(10,{
        "pet":pet,"train_type":ttype,"reward_point":reward_point,"reward_crystal":0,
        "add_hp_tp":adds.get("add_hp_tp",0),"add_phy_att_tp":adds.get("add_phy_att_tp",0),
        "add_mag_att_tp":adds.get("add_mag_att_tp",0),"add_speed_tp":adds.get("add_speed_tp",0),
        "add_phy_def_tp":adds.get("add_phy_def_tp",0),"add_mag_def_tp":adds.get("add_mag_def_tp",0),
        "add_energy":0,
    })


LOCAL_ARENA_RIVAL_NAME = "试炼对手"
LOCAL_ARENA_RIVAL_LEVEL = 5


LOCAL_EXPLORE_HIRE_SLOTS = 9
# LOCAL DEFAULT: the free starter mount (first row of exploreEquip type=1, 驴).
# Giving every character one keeps the mount page usable; renting others switches.
LOCAL_STARTER_MOUNT_ID = 100001
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
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        # This is the "already hired" list, so it must come from explore_rented.
        # Returning the whole exploreEquip catalogue made list[0] always 100001
        # and HireMountsUI's "everything rented" branch permanent, so the shop
        # (command 100) could never be reached and the mount was unpickable.
        # Filter by the requested category: without it the mount page counted the
        # expedition gear too (equip_count read 6/6) and listed gear as "mounts".
        rented_rows = c.execute(
            "SELECT equip_id, slot_type FROM explore_rented WHERE player_id=? AND slot_type=?"
            " ORDER BY equip_id",
            (player["id"], ttype),
        ).fetchall()
    rented_entries = [
        {"id": row["equip_id"], "type": row["slot_type"]} for row in rented_rows
    ]
    entries = rented_entries[(page - 1) * size: page * size]
    rented = len(rented_rows)
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
        # FightPetListUI.as:160-164 sends 44 with the pet index; `ttype` there is
        # the page kind from HunterTaskUI.as:302 and is ALWAYS 1, so it can never
        # identify the slot. Put the pet in the first free slot instead — that is
        # what makes "tap an empty slot -> pick a pet" fill slot 1, then slot 2.
        used = {
            int(r["squad_slot"])
            for r in c.execute(
                "SELECT squad_slot FROM pets WHERE player_id=? AND squad_slot>0",
                (player["id"],),
            )
        }
        target = next((slot_id for slot_id in (1, 2) if slot_id not in used), None)
        if target is None:
            return _pet_error(506)  # both slots taken; take one off first
        c.execute("UPDATE pets SET squad_slot=? WHERE id=?", (target, index))
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
        # HunterTaskUI.as:287-310 sends 45 when the player taps a slot that
        # ALREADY holds a pet — i.e. "take it off the squad". ttype is hardcoded
        # 1 there (it is a page kind, not a slot), so the pet simply leaves.
        c.execute("UPDATE pets SET squad_slot=0 WHERE id=?", (index,))
        pet = _pet_list_entry(row)
    return _protocol_response(45, {"value": "ok", "pet": pet})


LOCAL_COPY_MAPS = (1001, 1002, 1003, 1004)
# LOCAL DEFAULT: dungeon difficulty per stage (the reference level the defenders
# are picked around). Four stages climb 10 -> 90.
LOCAL_COPY_STAGE_LEVEL = {1001: 10, 1002: 40, 1003: 60, 1004: 90}
# LOCAL DEFAULT payouts. The original arena/dungeon reward tables are not
# recoverable, so these are flat and are credited to players.point on a win.
LOCAL_ARENA_REWARD = 20
LOCAL_COPY_REWARD = 50
# LOCAL DESIGN: 深渊四层的奖励曲线 —— 越深越值钱（×1 / ×1.5 / ×2 / ×3）。
LOCAL_COPY_REWARD_MULT = {1001: 1.0, 1002: 1.5, 1003: 2.0, 1004: 3.0}
LOCAL_EXPLORE_REWARD = 30
# LOCAL DEFAULT: exp each pet gains from one arena bout / one dungeon clear is a
# *fraction of a level at the reference level*, not a flat number — with the
# 4-segment curve a flat 200,000 was worth 40 levels at lv1 and nothing at lv900.
LOCAL_ARENA_EXP_SHARE = 3
LOCAL_COPY_EXP_SHARE = 2


def _battle_exp(level: int, share: int) -> int:
    """A `1/share` slice of one level at `level` (the local exp dial)."""
    return max(1, exp_to_next(max(1, int(level or 1))) // max(1, share))


def _defenders_from_monsters(ids) -> list[dict[str, object]]:
    """Real monster rows for the enemy side of a fight."""
    return [m for m in (_pick_monster(i) for i in ids) if m is not None]


def _defenders_for_level(base_id: int, reference_lv: int, count: int = 2) -> list[dict[str, object]]:
    """Base monster plus the one closest to `reference_lv` (same level or above).

    Fixed id pairs made fights lopsided: the dungeon used monster 1 (L1) together
    with monster 11 (L90), so a starter squad could never clear it while the arena
    (a single L1 monster) could never lose.
    """
    table = _monster_table()
    base = _pick_monster(base_id)
    picked: list[dict[str, object]] = [base] if base else []
    if len(picked) >= count:
        return picked
    candidates: list[tuple[int, int]] = []
    for monster_id in sorted(int(m) for m in table):
        if monster_id == base_id:
            continue
        raw = str(table[monster_id].get("level", "")).strip()
        level = int(raw) if raw.isdigit() else 0
        delta = level - reference_lv
        if delta < 0 or delta > LOCAL_HUNT_LEVEL_BAND:
            continue
        candidates.append((delta, monster_id))
    candidates.sort()
    for _, monster_id in candidates:
        monster = _pick_monster(monster_id)
        if monster is not None:
            picked.append(monster)
        if len(picked) >= count:
            break
    return picked


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
                      pro_hp, pro_speed, pro_phy_att, pro_mag_att, pro_phy_def, pro_mag_def
               FROM pets WHERE player_id=? AND battle_state=0 AND is_locked=0
               ORDER BY id LIMIT 2""",
            (p["id"],),
        ).fetchall()
    att_list, def_list, combat = _battle_side(
        hunter_skin=_role_skin_string(worn,p["sex"]),
        hunter_name=p["nick"] or "猎人",
        hunter_lv=p["lv"] or 1,
        hunter_stats=_hunter_combat_stats(p, worn),
        pet_rows=rows,
        defenders=defenders,
    )
    return att_list, def_list, _battle_record(att_list, def_list, combat)


def _arena_battle(database_path: Path) -> Response:
    """24 (ARENA_KEY) — arena settlement.

    RingResultUI shares the hunt replay contract. FightResultItem.as:349 and :405
    read arena_ap/max_arena_ap/rage_point with no guard and concatenate them into
    text, so all three must be present and numeric.
    """
    uid = _request_value("uid")
    # LOCAL DEFAULT rival: the old fixed monster 1 (lv1) made every arena bout a
    # one-sided win. Rubber-band the rival to the challenger's own squad instead,
    # using the same helper as the hunt/dungeon sides.
    with _connect_database(database_path) as c:
        p = c.execute("SELECT id,arena_ap,max_arena_ap FROM players WHERE uid=?", (uid,)).fetchone()
        if p is None:
            return _pet_error(103)
        squad_lv = c.execute(
            "SELECT COALESCE(MAX(lv), 1) FROM pets"
            " WHERE player_id=? AND battle_state=0 AND is_locked=0",
            (p["id"],),
        ).fetchone()[0]
    parts = _fight_payload(
        database_path, _defenders_for_level(1, max(LOCAL_ARENA_RIVAL_LEVEL, int(squad_lv)))
    )
    if parts is None:
        return _pet_error(103)
    att_list, def_list, record = parts
    is_win = _record_is_win(record)
    with _connect_database(database_path) as c:
        p = c.execute("SELECT id,arena_ap,max_arena_ap FROM players WHERE uid=?", (uid,)).fetchone()
        if p is None:
            return _pet_error(103)
        ap = max(0, (p["arena_ap"] or 0) - 1)
        c.execute("UPDATE players SET arena_ap=? WHERE id=?", (ap, p["id"]))
        max_ap = p["max_arena_ap"] or LOCAL_ARENA_RIVAL_LEVEL
        _credit_battle_rewards(c, p["id"], point=LOCAL_ARENA_REWARD if is_win else 0, crystal=0)
        # Arena bouts train the squad too, matching the hunt/expedition payouts.
        # The slice is a fraction of a level for the squad's own level, so an arena
        # is never worth 40 levels at lv1 nor nothing at lv900.
        arena_pets=[r[0] for r in c.execute(
            "SELECT id FROM pets WHERE player_id=? AND battle_state=0 AND is_locked=0 ORDER BY id LIMIT 2",
            (p["id"],))]
        squad_lv = c.execute(
            "SELECT COALESCE(MAX(lv), 1) FROM pets"
            " WHERE player_id=? AND battle_state=0 AND is_locked=0",
            (p["id"],),
        ).fetchone()[0]
        arena_exp = _battle_exp(squad_lv, LOCAL_ARENA_EXP_SHARE)
        _grant_pet_exp(c, arena_pets, arena_exp if is_win else arena_exp // 10)
    # LOCAL DEFAULT outcome, rewards and rank; the originals are not recoverable.
    return _protocol_response(24, {
        "is_win": 1 if is_win else 0, "arena_ap": ap, "max_arena_ap": max_ap,
        "arena_rank": _local_arena_rank(),
        # RingResultUI feeds this into PercentUItem like the hunt screen does.
        "rage_point": 100 if is_win else 0, "att_list": att_list, "def_list": def_list,
        "record": record, "pic": [],
        "reward_point": LOCAL_ARENA_REWARD if is_win else 0, "reward_crystal": 0,
        "reward_goods": [],
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
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        cleared = {
            row[0] for row in c.execute(
                "SELECT stage_id FROM copy_cleared WHERE player_id=?", (player["id"],)
            )
        }
    # 深渊按层推进：第一层常开，之后每层要求上一层已通关；已通关的层显示
    # 100% 完成度，未解锁的层客户端会画锁（MapItem.as:315 看 is_battle_able）。
    maps = []
    for index, map_id in enumerate(LOCAL_COPY_MAPS[:size]):
        previous_cleared = index == 0 or LOCAL_COPY_MAPS[index - 1] in cleared
        maps.append({
            "code": index + 1,
            "id": map_id,
            "is_battle_able": 1 if previous_cleared else 0,
            "finish_rate": 100 if map_id in cleared else 0,
            "finished_num": 1 if map_id in cleared else 0,
        })
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
    # 副本四层按等级递进；固定 (1, 11) 组合是 L1 + L90，新手必败。
    stage_level = LOCAL_COPY_STAGE_LEVEL.get(hid, 10)
    parts = _fight_payload(database_path, _defenders_for_level(1, stage_level))
    if parts is None:
        return _pet_error(103)
    att_list, def_list, record = parts
    is_win = _record_is_win(record)
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        # 深渊奖励随层数递增（×1 / ×1.5 / ×2 / ×3），越深越值得打。
        copy_mult = LOCAL_COPY_REWARD_MULT.get(hid, 1.0)
        copy_point = int(LOCAL_COPY_REWARD * copy_mult) if is_win else 0
        _credit_battle_rewards(c, player["id"], point=copy_point, crystal=0)
        copy_pets=[r[0] for r in c.execute(
            "SELECT id FROM pets WHERE player_id=? AND battle_state=0 AND is_locked=0 ORDER BY id LIMIT 2",
            (player["id"],))]
        # Half a level at the stage's reference level, so clearing stage 1001 does
        # not hand a lv-1 pet ten levels and stage 1004 is not worthless.
        copy_exp = int(_battle_exp(stage_level, LOCAL_COPY_EXP_SHARE) * copy_mult)
        _grant_pet_exp(c, copy_pets, copy_exp if is_win else copy_exp // 10)
        if is_win:
            # 记通关，73 才能显示完成度并解锁下一层（同层重复通关不重复推进）。
            c.execute(
                "INSERT OR REPLACE INTO copy_cleared (player_id, stage_id, cleared_at)"
                " VALUES (?, ?, ?)",
                (player["id"], hid, time.strftime("%Y-%m-%d %H:%M:%S")),
            )
    # LOCAL DEFAULT rewards; reward_goods[].id resolves through pic.txt
    # (FightResultItem.as:476), so it stays empty rather than guessing an id.
    return _protocol_response(74, {
        "is_win": 1 if is_win else 0, "att_list": att_list, "def_list": def_list,
        "record": record, "pic": [],
        "reward_point": copy_point, "reward_crystal": 0,
        "reward_goods": [],
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
    all_ids = sorted(by_type.get(source, []))
    for equip_id in all_ids[(page - 1) * size: page * size]:
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
        # Mounts (slot_type 1) are a single-slot choice, not a growing roster: the
        # old rows are deleted below, so a full category must not block switching.
        if ttype != 1 and count >= LOCAL_EXPLORE_HIRE_SLOTS:
            return _protocol_response(
                102, {"value": "full", "need_money": 0, "own_money": 0}
            )
        if ttype == 1:
            # A hunter rides one mount at a time: replace first, then insert, so a
            # previously rented mount cannot survive and "switch" actually sticks.
            c.execute(
                "DELETE FROM explore_rented WHERE player_id=? AND slot_type=1",
                (player["id"],),
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


LOCAL_ARENA_LADDER_SIZE = 9


def _local_arena_rank() -> int:
    """The player's rank on the local arena ladder.

    LOCAL DEFAULT: `_arena_rank` builds the board as "player first, then filler",
    so the player always sits at rank 1. The home page, the arena page and the
    battle result all print this number and used to disagree (home said 0 while
    the rank page said 1), which reads as a bug on the home screen.
    """
    return 1


def _arena_rank(database_path: Path) -> Response:
    """507 (REQUEST_ARENA_RANK_KEY) — the leaderboard behind 积分排名.

    RingTopUI.as:206-247 reads refresh_time, arena_rank and a `ranks` array, then
    calls int(ranks.length) with no null guard; each row needs rank/id/name/img.
    rank 1..3 additionally loads `img_top_<rank>` in TopItem.as:126-128.

    LOCAL DEFAULT: this offline server only ever holds the one account, so the
    player sits at rank 1 and the rest of the ladder is filler. TopItem has no
    click handler, so the filler rows are display-only and safe.
    """
    uid = _request_value("uid")
    try:
        page, size = int(_request_value("p", "1")), int(_request_value("n", "9"))
    except ValueError:
        return _pet_error(100)
    if page < 1 or not 1 <= size <= 9:
        return _pet_error(100)
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id,nick,lv,sex FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        worn = _worn_equipment(c, player["id"])
    player_img = _role_skin_string(worn, player["sex"])
    filler_img = _role_skin_string({})
    name = player["nick"] or "猎人"
    ladder = [{"rank": 1, "id": player["id"], "name": name, "img": player_img}]
    for rank in range(2, LOCAL_ARENA_LADDER_SIZE + 1):
        ladder.append({
            "rank": rank,
            "id": rank,
            "name": f"猎人{rank}号",
            "img": filler_img,
        })
    start = (page - 1) * size
    return _protocol_response(507, {
        "refresh_time": int(time.time()) + 86400,
        "arena_rank": _local_arena_rank(),
        "ranks": ladder[start:start + size],
        "value": "ok",
    })


def _unlock_pic(connection, player_id: int, pic_ids) -> list[int]:
    """Register creatures in the player's picture book.

    picStep.txt's milestones count these entries (`value` = how many are needed),
    and IllustrationTaskUI shows own_num/need_num from command 48, so every place
    that awards a `pic` entry has to record it here as well.
    """
    unlocked: list[int] = []
    for pic in pic_ids:
        try:
            pid = int(pic)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        cursor = connection.execute(
            "INSERT OR IGNORE INTO pic_unlocked (player_id, pic_id, unlocked_at) VALUES (?,?,?)",
            (player_id, pid, time.strftime("%Y-%m-%d %H:%M:%S")),
        )
        if cursor.rowcount:
            unlocked.append(pid)
    return unlocked


def _picstep_entries() -> list[dict]:
    """REAL milestones from the shipped picStep.txt, in step order."""
    table = config_tables._table("picStep.txt")
    entries = []
    for step_id in sorted(int(k) for k in table):
        record = table[step_id]
        def num(key: str) -> int:
            raw = str(record.get(key, "") or "").strip()
            return int(raw) if raw.lstrip("-").isdigit() else 0
        entries.append({
            "id": step_id,
            "need_num": num("value"),
            "reward_money": num("rewardMoney"),
            "reward_point": num("rewardPoint"),
            "reward_crystal": num("rewardCrystal"),
            "reward_goods": [(gid, count) for gid, count in _reward_goods_ids(str(record.get("rewardGoods", "") or ""))],
            "remark": record.get("remark", ""),
        })
    return entries


def _picstep_state(connection, player_id: int) -> tuple[dict, int, set[int]]:
    """The milestone the page should show, the collected count and claimed ids."""
    entries = _picstep_entries()
    owned = connection.execute(
        "SELECT COUNT(*) FROM pic_unlocked WHERE player_id=?", (player_id,)
    ).fetchone()[0]
    claimed = {
        row[0] for row in connection.execute(
            "SELECT step_id FROM pic_step_claimed WHERE player_id=?", (player_id,)
        )
    }
    # Show the first milestone that is still claimable, else the next unfinished
    # one, else the last step so the page is never empty.
    current = None
    for entry in entries:
        if entry["id"] not in claimed and owned >= entry["need_num"]:
            current = entry
            break
    if current is None:
        for entry in entries:
            if entry["id"] not in claimed:
                current = entry
                break
    if current is None and entries:
        current = entries[-1]
    return (current or {"id": 1, "need_num": 1, "reward_money": 0, "reward_point": 0,
                        "reward_crystal": 0, "reward_goods": [], "remark": ""}), owned, claimed


def _picstep_payload(entry: dict, owned: int) -> dict:
    """Fields IllustrationTaskUI.as:190-264 reads for one milestone."""
    return {
        "id": entry["id"],
        "own_num": owned,
        "need_num": entry["need_num"],
        "reward_money": entry["reward_money"],
        "reward_point": entry["reward_point"],
        "reward_crystal": entry["reward_crystal"],
        "reward_goods": [{"id": gid, "num": num} for gid, num in entry["reward_goods"]],
        "is_finish": 1 if owned >= entry["need_num"] else 0,
        "value": "ok",
    }


def _picstep_info(database_path: Path) -> Response:
    """48 (PICSTEP_INFO_KEY) — the picture-book milestone page."""
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        entry, owned, _claimed = _picstep_state(c, player["id"])
    return _protocol_response(48, _picstep_payload(entry, owned))


def _picstep_reward(database_path: Path) -> Response:
    """49 (PICSTEP_REWARD_KEY) — claim the current milestone.

    IllustrationTaskUI.as:264-343 re-renders from this response (it shows the
    reward TipItem when reward_* is set), so the claimed step's own numbers are
    echoed back after being credited.
    """
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        entry, owned, claimed = _picstep_state(c, player["id"])
        if entry["id"] in claimed or owned < entry["need_num"]:
            return _pet_error(504)
        _credit_battle_rewards(
            c, player["id"],
            point=entry["reward_point"] + entry["reward_money"],
            crystal=entry["reward_crystal"],
        )
        _grant_goods(c, player["id"], entry["reward_goods"])
        c.execute(
            "INSERT OR REPLACE INTO pic_step_claimed (player_id, step_id, claimed_at) VALUES (?,?,?)",
            (player["id"], entry["id"], time.strftime("%Y-%m-%d %H:%M:%S")),
        )
        nxt, owned_after, _ = _picstep_state(c, player["id"])
    payload = _picstep_payload(entry, owned)
    payload["pic"] = []
    payload["next"] = _picstep_payload(nxt, owned_after)
    return _protocol_response(49, payload)


LOCAL_RAGE_REWARD = 50


def _rage_reward(database_path: Path) -> Response:
    """97 (RAGE_REWARD_KEY) — open the rage chest on a result screen.

    FightResultItem.as:903 and DevelopResultUI.as:338-352 hand the whole response
    to GameUtil.getBox, which switches on `box_type` (1 pic, 2 pet, 3 silver,
    4 crystal) and returns null when the matching amount is zero; the caller then
    calls TipItem.show() with that null. So the payout must be non-zero.

    LOCAL DEFAULT: the original rage/consume formula is not recoverable, so each
    chest pays a flat silver amount.
    """
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        _credit_battle_rewards(c, player["id"], point=LOCAL_RAGE_REWARD, crystal=0)
    return _protocol_response(97, {
        "box_type": 3,
        "id": 0,
        "num": 0,
        "point": LOCAL_RAGE_REWARD,
        "crystal": 0,
        "pic": [],
        "value": "ok",
    })


# LOCAL DEFAULT: the arena star prize is one picture-book entry plus silver, paid
# once per calendar week (the rank page's own note says the board resets weekly).
LOCAL_ARENA_STAR_PIC = 1001
LOCAL_ARENA_STAR_POINT = 500


def _arena_week_key() -> str:
    """ISO year+week, e.g. "2026-W42", so the star prize re-arms each week."""
    now = time.localtime()
    return f"{now.tm_year}-W{time.strftime('%W', now)}"


def _arena_star_state(connection, player_id: int) -> tuple[str, bool]:
    key = _arena_week_key()
    claimed = connection.execute(
        "SELECT 1 FROM arena_star_claimed WHERE player_id=? AND week_key=?",
        (player_id, key),
    ).fetchone()
    return key, claimed is not None


def _arena_star_info(database_path: Path) -> Response:
    """82 (ARENA_STAR_CONFIRM_KEY) — the star prize page behind the rank chest.

    RingTopStarUI.as:178-193 reads id/name/is_reward/img with no null guard and
    feeds `img` straight into a Player paper doll.
    """
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id,nick,sex FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        worn = _worn_equipment(c, player["id"])
        _key, claimed = _arena_star_state(c, player["id"])
    return _protocol_response(82, {
        "id": 1,
        "name": player["nick"] or "猎人",
        "is_reward": 0 if claimed else 1,
        "img": _role_skin_string(worn, player["sex"]),
        "value": "ok",
    })


def _arena_star_reward(database_path: Path) -> Response:
    """83 (ARENA_STAR_REWARD_KEY) — claim the weekly star prize.

    RingTopStarUI.as:195-232 renders top_star_name plus one icon looked up through
    pic.txt (`reward_goods_id` must therefore be a real pic id) and then hands
    `pic` to GameUtil.getPic.
    """
    uid = _request_value("uid")
    pics = config_tables._table("pic.txt")
    if LOCAL_ARENA_STAR_PIC not in pics:
        return _pet_error(504)
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id,nick FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        key, claimed = _arena_star_state(c, player["id"])
        if claimed:
            return _pet_error(504)
        _credit_battle_rewards(c, player["id"], point=LOCAL_ARENA_STAR_POINT, crystal=0)
        _unlock_pic(c, player["id"], [LOCAL_ARENA_STAR_PIC])
        c.execute(
            "INSERT OR REPLACE INTO arena_star_claimed (player_id, week_key, claimed_at) VALUES (?,?,?)",
            (player["id"], key, time.strftime("%Y-%m-%d %H:%M:%S")),
        )
    record = pics[LOCAL_ARENA_STAR_PIC]
    return _protocol_response(83, {
        "top_star_name": player["nick"] or "猎人",
        "reward_goods_id": LOCAL_ARENA_STAR_PIC,
        "reward_goods_num": 1,
        "reward_point": LOCAL_ARENA_STAR_POINT,
        "pic": [{
            "id": LOCAL_ARENA_STAR_PIC,
            "icon": int(str(record.get("iconId", "") or LOCAL_ARENA_STAR_PIC).strip() or LOCAL_ARENA_STAR_PIC),
            "reward_point": 0, "reward_crystal": 0, "reward_goods": [],
        }],
        "value": "ok",
    })


def _own_info(database_path: Path) -> Response:
    """1 (OWN_INFO_KEY) — the paid-gold balance shown on the shop pay page.

    ShopPayUI.as:323-330 does `GameUtil.gold = "" + param2.money` with no guard,
    so a missing field renders the literal string "undefined" next to the gold
    icon. This offline server never grants paid currency, so the balance is 0.
    """
    uid = _request_value("uid")
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
    return _protocol_response(1, {"money": 0, "gold": 0, "value": "ok"})


def _gold_exchange(database_path: Path) -> Response:
    """300 (GOLD_EXCHANG) — Google Play receipt redemption.

    ShopPayUI.as:292-296 posts a store receipt, transaction id and signing key.
    Redeeming that requires the Play billing service, which an offline personal
    server cannot verify, so the request is refused rather than fabricating a
    purchase. Error 100 surfaces the client's generic "操作失败" alert.
    """
    return _pet_error(100)


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


_FORGE_FIELD_ALIASES = {
    "iconId": "iconId",
    "star": "star",
    "pro": "pro",
    "hp": "hp",
    "speed": "speed",
    "phyAtt": "phy_att",
    "magAtt": "mag_att",
    "phyDef": "phy_def",
    "magDef": "mag_def",
    "level": "level",
}


def _forge_equip_field(equip_id: int, column: str) -> int | None:
    """Read one crafting-result stat from the shipped equip.txt.

    The local LOCAL_FORGE_EQUIPMENT table only carried a hand-written row (all zero
    except two defences), so the craft page advertised a sword with 0 attack while
    equip.txt holds the real numbers.
    """
    record = config_tables.equip_record(equip_id)
    if record is None:
        return None
    raw = str(record.get(column, "") or "").strip()
    return int(raw) if raw.lstrip("-").isdigit() else None


# LOCAL DESIGN: the shipped config has no equipment-fusion table (the same is true
# for pet training/evolution), so both the merge rule and the fee are ours.
LOCAL_SYNTHESIS_FEE_BASE = 100
LOCAL_SYNTHESIS_FEE_PER_LEVEL = 50
_SYNTHESIS_STATS = ("hp", "speed", "phy_att", "mag_att", "phy_def", "mag_def")


def _synthesis_fee(level: int) -> int:
    return LOCAL_SYNTHESIS_FEE_BASE + LOCAL_SYNTHESIS_FEE_PER_LEVEL * max(1, int(level or 1))


def _synthesis_merge(rows) -> dict[str, int]:
    """Per stat: keep the better piece and add a quarter of the weaker one."""
    merged: dict[str, int] = {}
    for column in _SYNTHESIS_STATS:
        values = sorted((int(row[column] or 0) for row in rows), reverse=True)
        top, second = values[0], (values[1] if len(values) > 1 else 0)
        merged[column] = top + second // 4
    return merged


def _equipment_row(connection: sqlite3.Connection, player_id: int, index: int):
    return connection.execute(
        "SELECT id, item_id, icon, level, star, pro, hp, speed, phy_att, mag_att,"
        " phy_def, mag_def FROM inventory WHERE id=? AND player_id=? AND team=3",
        (index, player_id),
    ).fetchone()


def _synthesis_candidates(database_path: Path, exclude: int = 0) -> Response:
    """77/78 (CHOOSE_MAIN_EQUIP / CHOOSE_VICE_EQUIP).

    Both screens read `list[]` with index/id/icon/loc (IntegrationListUI.as:227-234),
    and the vice picker sends the chosen `main` so it must not be offered again.
    """
    command_id = 77 if exclude == 0 else 78
    uid = _request_value("uid")
    try:
        page = int(_request_value("p", "1"))
        size = int(_request_value("n", "9"))
    except ValueError:
        return _pet_error(100)
    if page < 1 or not 1 <= size <= 9:
        return _pet_error(100)
    try:
        main = int(_request_value("main", "0") or 0)
    except ValueError:
        main = 0
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id, sex FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        rows = c.execute(
            "SELECT id AS row_index, item_id, icon, level FROM inventory"
            " WHERE player_id=? AND team=3 AND id<>? ORDER BY id LIMIT ? OFFSET ?",
            (player["id"], main or max(0, exclude), size, (page - 1) * size),
        ).fetchall()
    equipment = []
    for row in rows:
        record = config_tables.equip_record(row["item_id"])
        if record is not None and not _equip_matches_sex(row["item_id"], player["sex"]):
            continue
        equipment.append({
            "index": row["row_index"], "id": row["item_id"],
            "icon": row["icon"], "loc": row["level"] or 1,
        })
    return _protocol_response(command_id, {"list": equipment, "type": 2, "value": "ok"})


def _equip_synthesis_confirm(database_path: Path) -> Response:
    """79 (EQUIP_SYN_CONFIRM) — the preview page: merged stats plus the fee."""
    uid = _request_value("uid")
    try:
        main = int(_request_value("main", ""))
        vice = int(_request_value("vice", ""))
    except ValueError:
        return _pet_error(100)
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id,money,point,crystal FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        main_row = _equipment_row(c, player["id"], main)
        vice_row = _equipment_row(c, player["id"], vice)
        if main_row is None or vice_row is None or main == vice:
            return _pet_error(400)
    merged = _synthesis_merge((main_row, vice_row))
    fee = _synthesis_fee(main_row["level"])
    return _protocol_response(79, {
        "id": main_row["item_id"],
        "icon": main_row["icon"],
        "star": main_row["star"],
        "pro": main_row["pro"],
        "level": main_row["level"],
        **merged,
        "skills": [], "buffs": [],
        "need_money": fee, "own_money": player["money"],
        "need_point": 0, "own_point": player["point"],
        "need_crystal": 0, "own_crystal": player["crystal"],
        "need_goods": [],
        "value": "ok",
    })


def _equip_synthesis_perform(database_path: Path) -> Response:
    """80 (SYN_EQUIP) — fuse the vice piece into the main one.

    The vice row is consumed (that is the whole point of the screen), the main row
    keeps its identity and gains the merged stats.
    """
    uid = _request_value("uid")
    try:
        main = int(_request_value("main", ""))
        vice = int(_request_value("vice", ""))
    except ValueError:
        return _pet_error(100)
    if main == vice:
        return _pet_error(400)
    with _connect_database(database_path) as c:
        player = c.execute("SELECT id,money FROM players WHERE uid=?", (uid,)).fetchone()
        if player is None:
            return _pet_error(103)
        main_row = _equipment_row(c, player["id"], main)
        vice_row = _equipment_row(c, player["id"], vice)
        if main_row is None or vice_row is None:
            return _pet_error(400)
        fee = _synthesis_fee(main_row["level"])
        if player["money"] < fee:
            return _pet_error(403)
        merged = _synthesis_merge((main_row, vice_row))
        c.execute(
            "UPDATE players SET money = money - ? WHERE id = ? AND money >= ?",
            (fee, player["id"], fee),
        )
        assignments = ", ".join(f"{column} = ?" for column in _SYNTHESIS_STATS)
        c.execute(
            f"UPDATE inventory SET {assignments} WHERE id = ?",
            (*[merged[column] for column in _SYNTHESIS_STATS], main),
        )
        c.execute("DELETE FROM inventory WHERE id = ? AND player_id = ?", (vice, player["id"]))
        current = c.execute("SELECT id, item_id, icon FROM inventory WHERE id = ?", (main,)).fetchone()
    return _protocol_response(80, {
        "index": current["id"], "id": current["item_id"], "icon": current["icon"],
        "pic": [], "value": "ok",
    })


def _forge_list(database_path: Path) -> Response:
    try: ttype = int(_request_value("ttype", "1")); page = int(_request_value("p", "1")); size = int(_request_value("n", "9"))
    except ValueError: return _pet_error(100)
    if ttype != 1: return _protocol_response(32, {"list": []})
    # `id` must be the CRAFTED EQUIP id: BlacksmithListUI.as:245 resolves the row
    # name with getConfigValue("pic", row.id, "name"), and a recipe id (32001) has
    # no pic row, so the list rendered nameless. `index` stays the recipe id
    # because that is what the client sends back as `gid` to command 33.
    rows = [
        {
            "index": rid,
            "id": recipe["output"],
            "icon": _forge_equip_field(recipe["output"], "iconId") or recipe["output"],
            "level": _forge_equip_field(recipe["output"], "level") or 1,
        }
        for rid, recipe in LOCAL_FORGE_RECIPES.items()
    ]
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
    def stat(column: str) -> int:
        value = _forge_equip_field(recipe["output"], column)
        if value is not None:
            return value
        return output.get(_FORGE_FIELD_ALIASES[column], 0)

    return _protocol_response(33, {
        "id": recipe["output"],
        "icon": stat("iconId") or output["icon"],
        "star": stat("star"),
        "pro": stat("pro"),
        "hp": stat("hp"),
        "phy_att": stat("phyAtt"),
        "mag_att": stat("magAtt"),
        "phy_def": stat("phyDef"),
        "mag_def": stat("magDef"),
        "speed": stat("speed"),
        "level": stat("level"),
        "need_money": recipe["money"], "own_money": player["money"],
        "need_point": recipe["point"], "own_point": player["point"],
        "need_crystal": recipe["crystal"], "own_crystal": player["crystal"],
        "need_goods": needs,
    })


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
        SELECT id AS "index", id, pet_id, icon, name, lv, exp, star, pro, battle_state, is_locked,
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
        # The pet page itself prints Lv only, but every other exp surface (10/50)
        # already ships `exp`; sending it keeps the two in sync for tooling.
        "exp": row["exp"] if "exp" in row.keys() else 0,
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


_PET_STAT_COLUMNS = (
    ("hp", "hp"),
    ("speed", "speed"),
    ("phy_att", "phyAtt"),
    ("mag_att", "magAtt"),
    ("phy_def", "phyDef"),
    ("mag_def", "magDef"),
)


def _pet_base_stats(pet_id: int) -> dict[str, int]:
    """Six base stats straight from pet.txt.

    LOCAL_PET_BASE_STATS used to hardcode only 1001 and 2019 and fall back to
    1001 for every other species, so all caught creatures displayed 火龙's
    39/65/52/60/43/50 — the "attributes are all identical" symptom. pet.txt
    carries the real per-species numbers (5001 is 99/90/115/90/78/95).
    """
    record = config_tables.pet_record(pet_id)
    if record is not None:
        stats = {}
        for field, column in _PET_STAT_COLUMNS:
            raw = str(record.get(column, "") or "").strip()
            stats[field] = int(raw) if raw.lstrip("-").isdigit() else 0
        if any(stats.values()):
            return stats
    # LOCAL DEFAULT: unknown species falls back to the starter's line.
    return {"hp": 39, "speed": 65, "phy_att": 52, "mag_att": 60, "phy_def": 43, "mag_def": 50}


def _player_pet_full_detail(database_path: Path) -> Response:
    uid = _request_value("uid")
    pet_index = _pet_index_from_request()
    if pet_index is None:
        return _pet_error(100)
    with _connect_database(database_path) as connection:
        player, row = _find_player_pet(connection, uid, pet_index)
        if player is None: return _pet_error(103)
        if row is None: return _pet_error(506)
        stats = _pet_base_stats(row["pet_id"])
        skills = _skill_rows(row["skills"])
        growth_total = sum(row[k] for k in ("gw_hp","gw_speed","gw_phy_att","gw_mag_att","gw_phy_def","gw_mag_def"))
        raw_grows = str((config_tables.pet_record(row["pet_id"]) or {}).get("grows", "") or "").strip()
        parts = [part.strip() for part in raw_grows.split(":")]
        lo, hi = 0, 0
        if len(parts) == 2 and all(part.lstrip("-").isdigit() for part in parts):
            lo, hi = int(parts[0]), int(parts[1])
        # ui.txt 51-55 scale. Normalise against the pet's own `grows` range: high
        # stars start at 10..80, so a birth-value roll must not read as "中超".
        span = 6 * (hi - lo)
        growth_rate = max(1, min(5, math.ceil((growth_total - 6 * lo) / span * 5))) if span > 0 else 1
        payload = {"index": row["index"], "id": row["pet_id"], "icon": row["icon"], "star": row["star"], "lv": row["lv"], "pro": row["pro"], "nature": row["nature"], "generation": row["generation"], "skills": skills, "buffs": [{"id": int(x)} for x in (row["buffs"] or "").split(":") if x.isdigit()], "hp": stats["hp"], "speed": stats["speed"], "phy_att": stats["phy_att"], "mag_att": stats["mag_att"], "phy_def": stats["phy_def"], "mag_def": stats["mag_def"], "hp_tp": row["pro_hp"], "speed_tp": row["pro_speed"], "phy_att_tp": row["pro_phy_att"], "mag_att_tp": row["pro_mag_att"], "phy_def_tp": row["pro_phy_def"], "mag_def_tp": row["pro_mag_def"], "hp_gw": row["gw_hp"], "speed_gw": row["gw_speed"], "phy_att_gw": row["gw_phy_att"], "mag_att_gw": row["gw_mag_att"], "phy_def_gw": row["gw_phy_def"], "mag_def_gw": row["gw_mag_def"], "total_gw": sum(row[k] for k in ("gw_hp","gw_speed","gw_phy_att","gw_mag_att","gw_phy_def","gw_mag_def")), "gw_rate": growth_rate}
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
        stats = _pet_base_stats(pet["pet_id"])
        # Command 19 rerolls every growth value inside pet.txt `grows` (lo:hi).
        # It used to merely *rotate* the six numbers, so `total_gw` — the value
        # ui.txt 36 labels 成长 — never changed, and the sixth use restored the
        # starting layout exactly. That is the "using the item does nothing" report.
        lo, hi = _pet_grows_range(pet["pet_id"])
        if hi <= lo:
            lo, hi = 0, max(1, hi)
        values = [random.randint(lo, hi) for _ in range(6)]
        total = sum(values)
        columns = ("gw_hp", "gw_speed", "gw_phy_att", "gw_mag_att", "gw_phy_def", "gw_mag_def")
        connection.execute("UPDATE pets SET " + ", ".join(f"{c} = ?" for c in columns) + ", gw_flush_count = gw_flush_count + 1 WHERE id = ?", (*values, pet_index))
        _consume_mutation_item(connection, item)
        payload = {"value": "ok", "hp": stats["hp"], "hp_gw": values[0], "speed": stats["speed"], "speed_gw": values[1], "phy_att": stats["phy_att"], "phy_att_gw": values[2], "mag_att": stats["mag_att"], "mag_att_gw": values[3], "phy_def": stats["phy_def"], "phy_def_gw": values[4], "mag_def": stats["mag_def"], "mag_def_gw": values[5], "total_gw": total, "gw_rate": _gw_rate(total, lo, hi)}
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
        payload = {"id": pet["pet_id"], "name": _pet_name(pet["pet_id"], pet["name"]),
                   "nature": nature, "value": "ok"}
    return _protocol_response(20, payload)


def _skill_rows(skill_text: str):
    """skill.txt carries a real `damageType` column (1 physical, 2 magical).

    The previous `startswith("51")` guess labelled 5002 斗气 / 5201 毒雾 / 5202 /
    5004 as physical, so the stat panel and the forget-skill tip showed the wrong
    school for several pets in the live save.
    """
    table = config_tables._table("skill.txt")
    result = []
    for token in (skill_text or "").split(":"):
        if not token.isdigit(): continue
        sid = int(token)
        raw = str(table.get(sid, {}).get("damageType", "")).strip()
        result.append({"id": sid, "dm_type": int(raw) if raw in ("1", "2") else 1})
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
        chosen = _request_value("index2", "")
        if chosen:
            # The item is only needed (and only consumed) once a trait is picked:
            # the first 85 call is the picker, and the client draws it from the
            # response alone. Requiring 遗忘卡牌 up front made the picker itself
            # answer -1:100 for every player who had not bought one yet.
            if chosen not in buffs: return _pet_error(100)
            item = _mutation_inventory(c, player["id"], 10034)
            if item is None or item["quantity"] <= 0: return _pet_error(400)
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
            return _protocol_response(114, {"id": pet["pet_id"], "icon": pet["icon"], "name": _pet_name(pet["pet_id"], pet["name"]), "add_type": names[dest], "diff_type": names[source], "value": amount})
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
        # pet.txt `recyclePoint` is "goodsId:num" per species (2019 -> 11100:8).
        # PetInfoUI.as:278-285 reads free_goods_id/free_goods_num to draw the
        # refund line; without it releasing destroyed the pet for nothing.
        record = config_tables.pet_record(row["pet_id"]) or {}
        free_goods_id = free_goods_num = 0
        raw = str(record.get("recyclePoint", "") or "").strip()
        if ":" in raw:
            gid_raw, num_raw = (part.strip() for part in raw.split(":", 1))
            if gid_raw.isdigit() and num_raw.isdigit():
                free_goods_id, free_goods_num = int(gid_raw), int(num_raw)
        if free_goods_id and free_goods_num:
            _grant_goods(connection, player["id"], ((free_goods_id, free_goods_num),))
        connection.execute(
            "DELETE FROM pets WHERE id = ? AND player_id = ?",
            (pet_index, player["id"]),
        )
    return _protocol_response(15, {"value": "ok",
                                   "free_goods_id": free_goods_id,
                                   "free_goods_num": free_goods_num})


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
        # LOCKED pets cannot be consumed or used as material, and the vice-pet
        # picker (63) must not offer the main pet the player just chose — the
        # client sends it as `main`, and picking it made 65 fail with -1:100.
        try:
            main_filter = int(_request_value("main", "0") or 0)
        except ValueError:
            main_filter = 0
        rows = connection.execute(
            """
            SELECT id AS "index", pet_id AS id, icon, name, lv FROM pets
            WHERE player_id=? AND battle_state=0 AND is_locked=0 AND id <> ?
            ORDER BY id LIMIT ? OFFSET ?
            """,
            (player["id"], main_filter, page_size, (page - 1) * page_size),
        ).fetchall()
    return _protocol_response(
        command_id,
        {"list": [_pet_list_entry(r) for r in rows]},
    )


_SKILL_FAMILY_INDEX: dict[str, dict[int, int]] | None = None


def _skill_family_index() -> dict[str, dict[int, int]]:
    """family name -> {level: skill id}, from the shipped skill.txt.

    A skill's family is `name` with the leading "N级" stripped ("1级十字斩（物理）"
    -> "十字斩（物理）"), so levels 1..15 of the same move share one key.
    """
    global _SKILL_FAMILY_INDEX
    if _SKILL_FAMILY_INDEX is None:
        index: dict[str, dict[int, int]] = {}
        for skill_id, record in config_tables._table("skill.txt").items():
            name = str(record.get("name", "") or "").strip()
            level_raw = str(record.get("level", "") or "").strip()
            if not name or not level_raw.isdigit():
                continue
            family = name.split("级", 1)[-1].strip() if "级" in name else name
            if not family:
                continue
            index.setdefault(family, {})[int(level_raw)] = int(skill_id)
        _SKILL_FAMILY_INDEX = index
    return _SKILL_FAMILY_INDEX


def _skill_cap(star: int, generation: int) -> int:
    """LOCAL DESIGN: 稀有/高世代宠物能带更多技能。

    固定上限 4 会让所有宠物长得一样，稀有感就没了。按星级与世代给槽位：
    3★1代=4、5★1代=5、8★2代=8、12★3代=10，硬上限 12。
    """
    star = max(1, int(star or 1))
    generation = max(1, int(generation or 1))
    return max(1, min(12, 3 + star // 2 + generation // 2))


def _merge_skills(main_skills: str, vice_skills: str, cap: int = 4) -> str:
    """Skill synthesis (command 65 with ttype=1).

    LOCAL DESIGN — the client ships no rule text for this, only help.txt's one line
    about "skills being recombined". The rule implemented here:
      * the pool is the union of both pets' skills,
      * one skill per family (highest level wins, so breeding never downgrades),
      * each surviving family has a chance to gain one level,
      * the cap comes from the pet's rarity (`_skill_cap`), not a flat four.
    """
    index = _skill_family_index()
    by_id = config_tables._table("skill.txt")

    def families(text: str) -> dict[str, int]:
        found: dict[str, int] = {}
        for token in str(text or "").split(":"):
            if not token.isdigit():
                continue
            record = by_id.get(int(token))
            if record is None:
                continue
            name = str(record.get("name", "") or "")
            family = name.split("级", 1)[-1].strip() if "级" in name else name
            if not family:
                continue
            level = int(str(record.get("level", "1") or 1) or 1)
            found[family] = max(found.get(family, 0), level)
        return found

    # 替换/升级：两宠共有的族取最高级；追加：副宠独有的族按概率并入。
    levels = families(main_skills)
    for family, level in families(vice_skills).items():
        if family in levels:
            levels[family] = max(levels[family], level)
        elif random.random() < LOCAL_SKILL_ADD_CHANCE:
            levels[family] = level

    merged: list[int] = []
    for family, level in sorted(levels.items()):
        available = index.get(family, {})
        if not available:
            continue
        # LOCAL DESIGN: 30% chance to inherit one level higher, capped by the family.
        if random.random() < 0.30:
            level = min(max(available), level + 1)
        level = max(min(available), min(max(available), level))
        merged.append(available[level])
    merged.sort(key=lambda sid: (
        int(str(by_id.get(sid, {}).get("level", "0") or 0)),
        int(str(by_id.get(sid, {}).get("damage", "0") or 0)),
    ), reverse=True)
    keep = max(1, min(12, int(cap or 4), len(merged)))
    return ":".join(str(sid) for sid in merged[:keep])


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

        # help.txt id 10 规则③⑥：合成必增世代；主宠继承副宠 100% 世代与 50% 强化值。
        # 旧实现是"固定 +5、世代 +1"，与客户端自带的帮助文案完全不符，而且副宠的
        # 培养投入（pro_*）对结果没有任何影响。
        try:
            ttype = int(_request_value("ttype", "1") or 1)
        except ValueError:
            ttype = 1
        if ttype not in (1, 2):
            ttype = 1
        main_generation = int(main_row["generation"] or 1)
        vice_generation = int(vice_row["generation"] or 1)
        generation = max(main_generation, vice_generation)
        if vice_generation <= main_generation:
            generation += 1
        # 结果页的文案是「继承生命强化值」并要求 >0 才显示（PetSynthesisResultUI
        # .as:173-195），所以这里必须记录**实际继承到的增量**，不能报绝对值——
        # 主宠原有 100、继承 50 时若报 150，玩家会以为一次合成加了 150。
        inherited: dict[str, int] = {}
        for column in ("pro_hp", "pro_speed", "pro_phy_att",
                       "pro_mag_att", "pro_phy_def", "pro_mag_def"):
            current = int(main_row[column] or 0)
            step = min(int(vice_row[column] or 0) // 2, max(0, LOCAL_PRO_CAP - current))
            inherited[column] = step
            connection.execute(
                f"UPDATE pets SET {column} = ? WHERE id = ?",
                (current + step, main_index),
            )
        if ttype == 1:
            # 技能合成（ttype=1）：并集去重、按族取最高级、有概率再升一级，
            # 槽位上限按"星级 + 世代"给（稀有宠带得更多）。
            main_skill_count = len([t for t in str(main_row["skills"] or "").split(":") if t.isdigit()])
            skill_cap = max(main_skill_count, _skill_cap(main_row["star"], generation))
            connection.execute(
                "UPDATE pets SET skills = ? WHERE id = ?",
                (_merge_skills(main_row["skills"], vice_row["skills"], skill_cap), main_index),
            )
        if ttype == 2:
            # 特性合成：副宠特性并入主宠，数量受世代上限 floor(sqrt(世代))+1 约束。
            cap = min(30, math.isqrt(generation) + 1)
            merged = [token for token in str(main_row["buffs"] or "").split(":") if token.isdigit()]
            for token in str(vice_row["buffs"] or "").split(":"):
                if token.isdigit() and token not in merged and len(merged) < cap:
                    merged.append(token)
            connection.execute("UPDATE pets SET buffs=? WHERE id=?", (":".join(merged), main_index))
        connection.execute("UPDATE pets SET generation=? WHERE id=?", (generation, main_index))
        connection.execute("DELETE FROM pets WHERE id=?", (vice_index,))
        updated = connection.execute(
            """SELECT id AS "index", pet_id AS id, icon, name, lv, star, pro, skills, buffs,
                      pro_hp, pro_speed, pro_phy_att, pro_mag_att, pro_phy_def, pro_mag_def
               FROM pets WHERE id=?""",
            (main_index,),
        ).fetchone()

    skills = [s for s in str(updated["skills"] or "").replace(";", ":").split(":") if s.strip()]
    buffs = [int(b) for b in str(updated["buffs"] or "").split(":") if b.isdigit()]
    payload = {
        "index": updated["index"],
        "id": updated["id"],
        "icon": updated["icon"],
        "name": _pet_name(updated["id"], updated["name"]),
        "lv": updated["lv"],
        "exd_generation": generation,
        "type": ttype,
        "skills": [{"id": int(s)} for s in skills if s.isdigit()],
        "buffs": [{"id": b} for b in buffs],
        # 增量语义：与「继承…强化值」「增加世代」的文案一致。
        "exd_generation": generation - main_generation,
        "exd_hp_tp": inherited["pro_hp"],
        "exd_speed_tp": inherited["pro_speed"],
        "exd_phy_att_tp": inherited["pro_phy_att"],
        "exd_mag_att_tp": inherited["pro_mag_att"],
        "exd_phy_def_tp": inherited["pro_phy_def"],
        "exd_mag_def_tp": inherited["pro_mag_def"],
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
        if command == "show" and _request_value("showId") == "89":
            return _guild_change_name(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "90":
            return _quit_guild(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "92":
            return _create_guild(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "94":
            return _guild_battle(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "3":
            return _player_detail_social(current_app.config["DATABASE"])
        # 41 (SHOW_MORE_INFO) and 107 (ACHIEVEMENT_LIST) are not implemented yet,
        # but their screens dereference the payload WITHOUT a null guard:
        #   InfoUI.as:232        var _loc8_:Array = param2.list; _loc8_.length
        #   ArtifactListUI.as:365 _list = param2.pics; _list.length
        # The generic {"value":"ok"} fallback therefore threw a TypeError and froze
        # the page. Answer with correctly-shaped empty payloads instead.
        if command == "show" and _request_value("showId") == "41":
            return _protocol_response(41, {"list": [], "value": "ok"})
        if command == "show" and _request_value("showId") == "107":
            return _protocol_response(107, {"id": 0, "need_money": 0,
                                            "pics": [], "list": [], "is_reward": 0})
        if command == "show" and _request_value("showId") == "51":
            return _friend_list(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "52":
            return _friend_detail(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") in ("512", "513"):
            return _friend_request(current_app.config["DATABASE"])
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
        if command == "show" and _request_value("showId") == "49":
            return _picstep_reward(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "82":
            return _arena_star_info(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "83":
            return _arena_star_reward(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "97":
            return _rage_reward(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "1":
            return _own_info(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "300":
            return _gold_exchange(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "506":
            return _arena_fighter(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "507":
            return _arena_rank(current_app.config["DATABASE"])
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
        if command == "show" and _request_value("showId") == "77":
            return _synthesis_candidates(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "78":
            return _synthesis_candidates(current_app.config["DATABASE"], exclude=-1)
        if command == "show" and _request_value("showId") == "79":
            return _equip_synthesis_confirm(current_app.config["DATABASE"])
        if command == "show" and _request_value("showId") == "80":
            return _equip_synthesis_perform(current_app.config["DATABASE"])
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

    @app.after_request
    def _log_protocol_errors(response):
        """把业务错误写进日志。

        `-1:<errorId>` 是协议层错误，HTTP 状态仍是 200，所以以前只会在客户端
        弹一句「非法操作」而服务端日志干净得像没发生过——排查时完全看不见。
        这里统一记录 showId / m / uid 后缀 / 参数名，方便对着真机复现。
        """
        if request.path != "/flash.do":
            return response
        try:
            body = response.get_data(as_text=True)
        except (RuntimeError, AttributeError):
            return response
        if not body.startswith("-1:"):
            return response
        app.logger.warning(
            "PROTOCOL_ERROR showId=%s m=%s error=%s uid=...%s fields=%s",
            request.form.get("showId", ""),
            request.form.get("m", ""),
            body.strip()[:12],
            (request.form.get("uid", "") or "")[-8:],
            ",".join(sorted(request.form.keys())),
        )
        return response

    return app
