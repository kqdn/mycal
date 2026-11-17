"""Import a TOML week file into the database (Milestone 3): uv run mycal-import WEEK.toml

Not part of the solver: a caller, like api.py, demo.py and store.py.

Each week file adds to the database. Its items and constraints are stored
with the file's name as their source; series come in as that week's
occurrence items, since series are not stored yet. The timezone, slot size
and work frames come only from the first import into an empty database; after
that they are edited in the app and later imports leave them alone. Engine
settings never come from a file. No blocks are imported: the API plans a week
the first time it is viewed.

Importing a file whose name is already in the database is refused unless
--replace is given. Then only that file's items and constraints are replaced
(their blocks go with them); other files' items and items added in the app
stay. The whole import is one transaction: it all goes in or nothing does.
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

    The file's name is its source. Raises FileExistsError if that source was
    imported before and `replace` is false.
    """
    week = load_week(path)  # parse fully before touching the database
    items = week_items(week)
    source = path.name
    conn = store.connect(db)
    try:
        if store.has_source(conn, source) and not replace:
            raise FileExistsError(
                f"{source} was already imported into {db}. "
                f"Use --replace to replace the items and constraints that came from it."
            )
        replaced, first = store.import_source(conn, source, week.settings, week.work_frames, items, week.constraints)
    finally:
        conn.close()
    if first:
        frames = f"set the timezone and {len(week.work_frames)} work frames"
    else:
        frames = "kept the timezone and work frames already in the database"
    summary = f"Imported {len(items)} items and {len(week.constraints)} constraints from {source} into {db}, and {frames}."
    return summary + (f" Replaced {replaced} items from the earlier import." if replace else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mycal-import", description="Import a TOML week file into the database.")
    parser.add_argument("week", type=Path, help="the week file, for example weeks/2026-11-16.toml")
    parser.add_argument("--db", type=Path, default=None, help=f"database file (default: ${store.DB_ENV} or data/mycal.db)")
    parser.add_argument("--replace", action="store_true", help="replace the items and constraints from an earlier import of this file")
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
