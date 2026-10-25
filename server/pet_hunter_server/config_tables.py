"""Read the configuration tables that ship with the AIR client.

The repack under ``client/air51-repack/src/data`` is the authoritative source for
every id, name, icon and stat in the game. The original server is gone, so these
tables are the only trustworthy record of what an item *is*. Numeric gameplay
rules (prices, AP costs, refine fees) are NOT in these files and remain local
defaults declared in app.py.

Only ``prop.txt``/``equip.txt``/``skin.txt``/``pet.txt``/``equipEnchant.txt`` are
needed here; they are tab separated with a header row.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _config_root() -> Path | None:
    """Locate the repack's data directory by walking up from this file.

    Tables sit at ``<root>/zh-CN/config/*.txt`` (prop/equip) with ``skin.txt``
    one level up at ``<root>/skin.txt``.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (
            parent / "client" / "air51-repack" / "src" / "data",
            parent / "client" / "air51-repack" / "src",
        ):
            if (candidate / "zh-CN" / "config").is_dir():
                return candidate
    override = os.environ.get("PETHUNTER_CONFIG_ROOT")
    return Path(override) if override else None


@lru_cache(maxsize=None)
def _table(zh_cn_name: str) -> dict[int, dict[str, str]]:
    root = _config_root()
    if root is None:
        return {}
    # prop/equip/skin live in zh-CN/config, skin.txt sits one level up in data.
    path = root / "zh-CN" / "config" / zh_cn_name
    if not path.is_file():
        path = root / zh_cn_name
    if not path.is_file():
        return {}
    rows: dict[int, dict[str, str]] = {}
    # equip.txt and prop.txt ship with a UTF-8 BOM; skin.txt does not.
    with path.open("r", encoding="utf-8-sig") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            cells = line.split("\t")
            record = dict(zip(header, cells))
            raw_id = record.get("id")
            if not raw_id:
                continue
            try:
                key = int(raw_id)
            except ValueError:
                continue
            record["id"] = str(key)
            rows[key] = record
    return rows


def _number(record: dict[str, str], key: str) -> int:
    """Stat cells are shipped with trailing spaces ("0  ")."""
    try:
        return int(str(record.get(key, "0")).strip() or 0)
    except ValueError:
        return 0


@lru_cache(maxsize=1)
def _equip_table() -> dict[int, dict[str, str]]:
    return _table("equip.txt")


@lru_cache(maxsize=1)
def _prop_table() -> dict[int, dict[str, str]]:
    return _table("prop.txt")


@lru_cache(maxsize=1)
def _skin_table() -> dict[int, dict[str, str]]:
    return _table("skin.txt")


def equip_table() -> dict[int, dict[str, str]]:
    return _equip_table()


def prop_table() -> dict[int, dict[str, str]]:
    return _prop_table()


def skin_table() -> dict[int, dict[str, str]]:
    return _skin_table()


@lru_cache(maxsize=1)
def _equip_enchant_table() -> dict[int, dict[str, str]]:
    """equipEnchant.txt, keyed by the *equipment* id (20031 == equip.txt 20031).

    The shipped file's header ends with a leading space (``" rate"``), so the
    column keys are stripped here; ``_table`` keeps its raw cache untouched.
    Cells are decoded by the helpers below because ``extSkills``/``rate`` are
    parallel comma/colon lists, not single numbers.
    """
    return {
        item_id: {str(column).strip(): value for column, value in record.items()}
        for item_id, record in _table("equipEnchant.txt").items()
    }


def equip_enchant_table() -> dict[int, dict[str, str]]:
    return _equip_enchant_table()


def equip_enchant_record(item_id: int) -> dict[str, str] | None:
    """REAL equipEnchant.txt row for one equipment id, or None if the piece has
    no enchant slot at all (the 18 starter-tier equips 20001-20026 are absent)."""
    return _equip_enchant_table().get(item_id)


def equip_enchant_max_count(record: dict[str, str]) -> int:
    """`maxCount` = how many traits the piece may carry (remark: "N个M等级特性")."""
    return max(0, _number(record, "maxCount"))


def equip_enchant_need(record: dict[str, str]) -> dict[str, int]:
    """`needMoney`/`needPoint`/`needCrystal`; all three are single cells."""
    return {
        "money": _number(record, "needMoney"),
        "point": _number(record, "needPoint"),
        "crystal": _number(record, "needCrystal"),
    }


def _id_num_pairs(raw: str) -> list[tuple[int, int]]:
    """Parse ``"10032:1,10033:2"`` (needGoods / rewardGoods shape); "0" is empty."""
    pairs: list[tuple[int, int]] = []
    for chunk in str(raw or "").split(","):
        gid, _, num = chunk.strip().partition(":")
        if gid.isdigit() and num.isdigit() and int(num) > 0:
            pairs.append((int(gid), int(num)))
    return pairs


def equip_enchant_goods(record: dict[str, str]) -> list[tuple[int, int]]:
    """`needGoods` (prop id, count) pairs; e.g. artifacts charge one 10032."""
    return _id_num_pairs(record.get("needGoods", ""))


def equip_enchant_ext_skills(record: dict[str, str]) -> list[tuple[int, int, int]]:
    """`extSkills` decoded to (level-1 skill id, min level, max level).

    The table writes ``"12101:1-2"``: 12101 is skill.txt id 12101
    ``1级火系专精``, i.e. the *level 1* id of the family, and the shipped families
    are contiguous, so level L is ``base + L - 1`` (12110 is ``10级火系专精``).
    """
    out: list[tuple[int, int, int]] = []
    for chunk in str(record.get("extSkills", "") or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        base, _, level_range = chunk.partition(":")
        low, _, high = level_range.partition("-")
        base = base.strip()
        if not base.isdigit():
            continue
        low_lv = int(low) if low.strip().isdigit() else 1
        high_lv = int(high) if high.strip().isdigit() else low_lv
        out.append((int(base), low_lv, max(low_lv, high_lv)))
    return out


def equip_enchant_rates(record: dict[str, str]) -> list[int]:
    """`rate` decoded to one weight per extSkills entry (the table uses 万分比:
    every shipped row sums to 10000)."""
    weights: list[int] = []
    for chunk in str(record.get("rate", "") or "").split(":"):
        chunk = chunk.strip()
        weights.append(int(chunk) if chunk.isdigit() else 0)
    return weights


@lru_cache(maxsize=1)
def _pet_table() -> dict[int, dict[str, str]]:
    return _table("pet.txt")


def pet_table() -> dict[int, dict[str, str]]:
    return _pet_table()


def pet_record(pet_id: int) -> dict[str, str] | None:
    """REAL pet.txt row: hp/speed/phyAtt/magAtt/phyDef/magDef, grows, buffSkills…"""
    return pet_table().get(pet_id)


def equip_record(item_id: int) -> dict[str, str] | None:
    return equip_table().get(item_id)


def prop_record(item_id: int) -> dict[str, str] | None:
    return prop_table().get(item_id)


def equip_slot(record: dict[str, str]) -> int:
    """equip.txt `type`: 1 weapon, 2 clothes, 3 hat (per the shipped rows)."""
    return _number(record, "type")


def equip_icon(record: dict[str, str]) -> int:
    return _number(record, "iconId")


def equip_image_id(record: dict[str, str]) -> int:
    """equip.txt `imageId` is a `skin.txt` id; ShowItem instantiates `s<id>`."""
    return _number(record, "imageId")


def equip_sex(record: dict[str, str]) -> int | None:
    """equip.txt `sex`: 1 male, 0 female, None when the column is unreadable.

    Every equipment id exists twice, once per sex, with a different `imageId`
    (e.g. 20002 male -> 100020, 20005 female -> 100040). Mixing them is what made
    a male hunter render with a female armour layer stacked on his male body.
    """
    raw = str(record.get("sex", "") or "").strip()
    return int(raw) if raw in ("0", "1") else None


_EQUIP_NAME_TYPE_INDEX: dict[tuple[str, int, int], int] | None = None


def equip_same_slot_other_sex(item_id: int) -> int | None:
    """The same equipment for the other sex, matched on (name, type).

    Used when a cross-sex piece is already equipped: rather than dropping the
    layer (leaving the hunter unarmoured) we draw the matching piece, so an old
    save's mis-seeded gear still looks right.
    """
    global _EQUIP_NAME_TYPE_INDEX
    table = equip_table()
    record = table.get(item_id)
    if record is None:
        return None
    if _EQUIP_NAME_TYPE_INDEX is None:
        index: dict[tuple[str, int, int], int] = {}
        for other_id, other in table.items():
            sex = equip_sex(other)
            if sex is None:
                continue
            key = (str(other.get("name", "")).strip(), equip_slot(other), sex)
            index.setdefault(key, other_id)
        _EQUIP_NAME_TYPE_INDEX = index
    sex = equip_sex(record)
    if sex is None:
        return None
    key = (str(record.get("name", "")).strip(), equip_slot(record), 0 if sex == 1 else 1)
    return _EQUIP_NAME_TYPE_INDEX.get(key)


def equip_stats(record: dict[str, str]) -> dict[str, int]:
    return {
        "hp": _number(record, "hp"),
        "speed": _number(record, "speed"),
        "phy_att": _number(record, "phyAtt"),
        "mag_att": _number(record, "magAtt"),
        "phy_def": _number(record, "phyDef"),
        "mag_def": _number(record, "magDef"),
    }


def equip_name(record: dict[str, str]) -> str:
    return record.get("name", "").strip()


def equip_star(record: dict[str, str]) -> int:
    return max(1, _number(record, "star"))


def equip_sell_price(record: dict[str, str]) -> int:
    return _number(record, "recyclePoint") or _number(record, "point")


def equip_skills(record: dict[str, str]) -> list[int]:
    raw = record.get("skills", "").strip()
    out: list[int] = []
    if not raw:
        return out
    for part in raw.replace(";", ":").split(":"):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def prop_icon(record: dict[str, str]) -> int:
    return _number(record, "iconId")


def prop_name(record: dict[str, str]) -> str:
    return record.get("name", "").strip()


def prop_use_type(record: dict[str, str]) -> int:
    return _number(record, "useType")


def prop_team(record: dict[str, str]) -> int:
    """prop.txt `team` is the bag tab the item belongs to (1 prop, 3 equip)."""
    return _number(record, "team")


def prop_value(record: dict[str, str]) -> int:
    return _number(record, "value")


def prop_sell_price(record: dict[str, str]) -> int:
    return _number(record, "recyclePoint") or _number(record, "point")


def all_equips() -> list[dict[str, str]]:
    return list(equip_table().values())


def all_props() -> list[dict[str, str]]:
    return list(prop_table().values())


@lru_cache(maxsize=1)
def up_role_table() -> dict[int, dict[str, str]]:
    """The 120 hunter titles from upRole.txt, keyed by `job` (not `id`).

    upRole.txt has no `id` column: its primary key is `job`, and the row also
    carries `needLevel` (the level required to promote), `rewardGoods`
    ("id:num,...") and `lowerLevel` (how many levels the promotion costs).
    """
    root = _config_root()
    if root is None:
        return {}
    path = root / "zh-CN" / "config" / "upRole.txt"
    if not path.is_file():
        return {}
    rows: dict[int, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig") as handle:
        header = handle.readline().rstrip("\r\n").split("\t")
        for line in handle:
            line = line.rstrip("\r\n")
            if not line:
                continue
            record = dict(zip(header, line.split("\t")))
            raw = record.get("job", "").strip()
            if raw.isdigit():
                rows[int(raw)] = record
    return rows


def clear_caches() -> None:
    for fn in (
        _equip_table, _prop_table, _skin_table, up_role_table, _table,
        _equip_enchant_table,
    ):
        fn.cache_clear()