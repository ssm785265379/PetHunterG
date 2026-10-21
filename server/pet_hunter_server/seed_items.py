"""Fill a player's bag from the client's own prop.txt / equip.txt tables.

Every item id, name, icon, slot and stat comes from the shipped configuration,
so nothing here is invented. Quantities are a LOCAL DEFAULT chosen so each
item is testable without grind; pass ``--quantity`` to change it.

Usage:
    python -m pet_hunter_server.seed_items --uid <player uid> [--quantity N]
                                            [--props-only|--equip-only]
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from . import config_tables


def _database_path() -> Path:
    return Path(__file__).resolve().parent.parent / "instance" / "game.sqlite3"


def seed_player_bag(
    database: Path,
    uid: str,
    quantity: int = 5,
    include_props: bool = True,
    include_equipment: bool = True,
) -> dict[str, int]:
    """Insert every prop and equip into the bag. Idempotent per item id."""
    if quantity < 1:
        raise ValueError("quantity must be >= 1")

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    added = {"props": 0, "equipment": 0}
    try:
        player = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            raise SystemExit(f"no player with uid={uid!r} in {database}")
        player_id = player["id"]

        if include_props:
            for record in config_tables.all_props():
                item_id = int(record["id"])
                team = config_tables.prop_team(record) or 1
                if team not in (1, 2):
                    continue
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO inventory (
                        player_id, item_id, team, quantity, icon, item_type, use_type
                    ) VALUES (?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        player_id,
                        item_id,
                        team,
                        quantity,
                        config_tables.prop_icon(record),
                        config_tables.prop_use_type(record),
                    ),
                )
                added["props"] += cursor.rowcount if cursor.rowcount > 0 else 0

        if include_equipment:
            for record in config_tables.all_equips():
                item_id = int(record["id"])
                stats = config_tables.equip_stats(record)
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO inventory (
                        player_id, item_id, team, quantity, icon, item_type, use_type,
                        level, star, pro, hp, speed, phy_att, mag_att, phy_def, mag_def
                    ) VALUES (?, ?, 3, 1, ?, ?, 1, 1, ?, 0, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        player_id,
                        item_id,
                        config_tables.equip_icon(record),
                        config_tables.equip_slot(record),
                        config_tables.equip_star(record),
                        stats["hp"],
                        stats["speed"],
                        stats["phy_att"],
                        stats["mag_att"],
                        stats["phy_def"],
                        stats["mag_def"],
                    ),
                )
                added["equipment"] += cursor.rowcount if cursor.rowcount > 0 else 0

        connection.commit()
    finally:
        connection.close()
    return added


def seed_player_pets(
    database: Path, uid: str, count: int = 6, level: int = 5
) -> int:
    """Add real pets from pet.txt so synthesis / evolution can be exercised."""
    if count < 1 or level < 1:
        raise ValueError("count and level must be >= 1")
    table = config_tables._table("pet.txt")
    candidates = [
        (int(pid), row)
        for pid, row in sorted(table.items())
        if row.get("iconId", "").isdigit() and str(row.get("star", "1")).isdigit()
    ]
    if not candidates:
        return 0

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    added = 0
    try:
        player = connection.execute(
            "SELECT id FROM players WHERE uid = ?", (uid,)
        ).fetchone()
        if player is None:
            raise SystemExit(f"no player with uid={uid!r} in {database}")
        existing = {
            r[0] for r in connection.execute(
                "SELECT pet_id FROM pets WHERE player_id = ?", (player["id"],)
            )
        }
        for pet_id, row in candidates:
            if len(existing) >= count:
                break
            if pet_id in existing:
                continue
            connection.execute(
                """
                INSERT INTO pets (player_id, pet_id, lv, star, pro, icon, skills, generation)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    player["id"],
                    pet_id,
                    level,
                    int(row.get("star", "1") or 1),
                    1,
                    int(row["iconId"]),
                    row.get("skills", "").strip() or "101:5101",
                ),
            )
            existing.add(pet_id)
            added += 1
        connection.commit()
    finally:
        connection.close()
    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uid", required=True, help="player uid from the players table")
    parser.add_argument(
        "--database", default=str(_database_path()), help="path to game.sqlite3"
    )
    parser.add_argument(
        "--quantity", type=int, default=5, help="LOCAL DEFAULT stack size for props"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--props-only", action="store_true")
    group.add_argument("--equip-only", action="store_true")
    parser.add_argument(
        "--pets", type=int, default=0,
        help="also add N real pets from pet.txt (LOCAL DEFAULT level 5)",
    )
    parser.add_argument("--pet-level", type=int, default=5)
    args = parser.parse_args(argv)

    result = seed_player_bag(
        Path(args.database),
        args.uid,
        quantity=args.quantity,
        include_props=not args.equip_only,
        include_equipment=not args.props_only,
    )
    print(f"added {result['props']} props and {result['equipment']} equipment to {args.uid}")
    if args.pets:
        added = seed_player_pets(Path(args.database), args.uid, args.pets, args.pet_level)
        print(f"added {added} pets (target {args.pets})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())