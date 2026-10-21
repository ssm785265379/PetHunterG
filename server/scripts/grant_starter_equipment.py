"""Give every existing local character the local starter equipment.

Local maintenance helper only. It never deletes or overwrites existing rows.
Run from the server directory:

    .\\.venv\\Scripts\\python.exe scripts\\grant_starter_equipment.py
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pet_hunter_server.app import grant_starter_equipment  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "instance" / "game.sqlite3",
    )
    args = parser.parse_args()
    seeded = grant_starter_equipment(args.database)
    print(f"seeded_equipment={seeded} database={args.database}")


if __name__ == "__main__":
    main()
