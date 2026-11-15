"""Import a TOML week file into the database (Milestone 3): uv run mycal-import WEEK.toml

Not part of the solver: a caller, like api.py, demo.py and store.py.

Week files are imported once. The file's settings, work frames, items and
constraints go in; series come in as that week's occurrence items, since
series are not stored until Milestone 5. No blocks are imported: the API
plans a week the first time it is viewed.

If the database already has items, the import refuses unless --replace is
given, and then it replaces everything in the database, blocks included.
Either way the whole import is one transaction: it all goes in or nothing does.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

from mycal import store
from mycal.demo import Week, load_week
from mycal.model import Item
from mycal.recurrence import expand_series


def week_items(week: Week) -> list[Item]:
    """The file's items plus this week's occurrences of its series."""
    last_day = week.start + timedelta(days=6)
    occurrences = [item for s in week.series for item in expand_series(s, week.items, week.start, last_day)]
    return week.items + occurrences


def import_week(path: Path, db: Path, replace: bool = False) -> str:
    """Import the week file at `path` into the database at `db` and return a summary line.

    Raises FileExistsError if the database has items and `replace` is false.
    """
    week = load_week(path)  # parse fully before touching the database
    items = week_items(week)
    conn = store.connect(db)
    try:
        if store.has_items(conn) and not replace:
            raise FileExistsError(
                f"{db} already has items. Use --replace to replace everything in it with {path.name}."
            )
        store.replace_all(conn, week.settings, week.work_frames, items, week.constraints)
    finally:
        conn.close()
    return (
        f"Imported {len(items)} items, {len(week.work_frames)} work frames and "
        f"{len(week.constraints)} constraints from {path.name} into {db}."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mycal-import", description="Import a TOML week file into the database.")
    parser.add_argument("week", type=Path, help="the week file, for example weeks/2026-11-16.toml")
    parser.add_argument("--db", type=Path, default=None, help=f"database file (default: ${store.DB_ENV} or data/mycal.db)")
    parser.add_argument("--replace", action="store_true", help="replace everything in a database that already has items")
    args = parser.parse_args(argv)
    try:
        print(import_week(args.week, args.db or store.db_path(), args.replace))
    except FileExistsError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except (OSError, KeyError, ValueError) as error:
        print(f"error: {args.week}: {error}", file=sys.stderr)
        return 1
    return 0
