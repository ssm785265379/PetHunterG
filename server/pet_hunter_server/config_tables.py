"""Read the configuration tables that ship with the AIR client.

The repack under ``client/air51-repack/src/data`` is the authoritative source for
every id, name, icon and stat in the game. The original server is gone, so these
tables are the only trustworthy record of what an item *is*. Numeric gameplay
rules (prices, AP costs, refine fees) are NOT in these files and remain local
defaults declared in app.py.

Only ``prop.txt``/``equip.txt``/``skin.txt``/``pet.txt`` are needed here; they are
tab separated with a header row.
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


def clear_caches() -> None:
    for fn in (_equip_table, _prop_table, _skin_table, _table):
        fn.cache_clear()