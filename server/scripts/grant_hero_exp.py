"""Local maintenance: give a hunter exp, or set level/job directly.

This is a development helper only (T04). It is deliberately NOT wired into any
in-game command: the real progression still comes from hunt/explore/arena/copy
battles and 72 promotions. Use it to reach the upRole level gates on a local save
when checking the desktop/device screens.

Run from the server directory (the DB defaults to server/instance/game.sqlite3):

    .\\.venv\\Scripts\\python.exe scripts\\grant_hero_exp.py --uid local-xxx --exp 5000
    .\\.venv\\Scripts\\python.exe scripts\\grant_hero_exp.py --uid local-xxx --lv 400 --job 2

`--exp` uses the same curve/auto-level as battle rewards; `--lv/--job` are direct
overrides for reproducing 71/72 states (they do not grant the promotion chest).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet_hunter_server.app import _connect_database, _grant_hero_exp  # noqa: E402


def main() -> int:
    server_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uid", required=True)
    parser.add_argument("--exp", type=int, default=0)
    parser.add_argument("--lv", type=int, default=0)
    parser.add_argument("--job", type=int, default=0)
    parser.add_argument("--db", type=Path, default=server_dir / "instance" / "game.sqlite3")
    args = parser.parse_args()
    if not args.exp and not args.lv and not args.job:
        parser.error("give at least one of --exp/--lv/--job")

    with _connect_database(args.db) as connection:
        row = connection.execute(
            "SELECT id, lv, exp, job FROM players WHERE uid=?", (args.uid,)
        ).fetchone()
        if row is None:
            print(f"no such uid: {args.uid}", file=sys.stderr)
            return 1
        if args.exp:
            print("lv ->", _grant_hero_exp(connection, row["id"], args.exp))
        if args.lv or args.job:
            sets: list[str] = []
            params: list[int] = []
            if args.lv:
                sets.append("lv=?")
                params.append(max(1, args.lv))
            if args.job:
                sets.append("job=?")
                params.append(min(120, max(1, args.job)))
            connection.execute(
                f"UPDATE players SET {', '.join(sets)} WHERE id=?",
                (*params, row["id"]),
            )
            print("updated")
        final = connection.execute(
            "SELECT lv, exp, job FROM players WHERE id=?", (row["id"],)
        ).fetchone()
    print(f"uid={args.uid} lv={final['lv']} exp={final['exp']} job={final['job']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
