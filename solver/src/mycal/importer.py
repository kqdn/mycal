"""Import a TOML week file into the database (Milestone 3): uv run mycal-import WEEK.toml

Not part of the solver: a caller, like api.py, demo.py and store.py.

Each week file adds to the database. Its items, series and constraints are
stored with the file's name as their source, plus the occurrences of its
series in the file's week; the planner creates later weeks' occurrences. A
series whose title is already stored from another file or the app is kept as
stored, and the file's rules that name it point to the stored one, so a week
file that repeats last week's series never doubles them. The timezone, slot size
and work frames come only from the first import into an empty database; after
that they are edited in the app and later imports leave them alone. Engine
settings never come from a file. No blocks are imported: the API plans a week
the first time it is viewed.

Importing a file whose name is already in the database is refused unless
--replace is given. Then only that file's items, series and constraints are
replaced (their blocks go with them); other files' items and things added in
the app stay. A replaced series keeps its id, so rules made in the app that
name it keep working. The whole import is one transaction: it all goes in or nothing does.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from mycal import store
from mycal.demo import Week, load_week
from mycal.model import Constraint, Item, Series
from mycal.recurrence import expand_series


@dataclass(slots=True)
class Contents:
    """What one import writes: the file's items and this week's occurrences, its own series and its rules."""

    items: list[Item]
    series: list[Series]
    constraints: list[Constraint]
    kept: list[str]  # titles of series already stored from elsewhere, kept as they are


def week_contents(week: Week, conn: sqlite3.Connection, source: str) -> Contents:
    """The file's contents, with its series matched by title against the series already stored.

    A title stored from another source (a file or the app) is kept as stored.
    A title stored from this same source (a --replace) keeps its id.
    """
    others: dict[str, UUID] = {}
    own: dict[str, UUID] = {}
    for stored in store.list_series(conn):
        (own if store.series_source(conn, stored.id) == source else others)[stored.title] = stored.id

    ids: dict[UUID, UUID] = {}
    series, kept = [], []
    for one in week.series:
        if one.title in others:
            ids[one.id] = others[one.title]
            kept.append(one.title)
        else:
            mine = replace(one, id=own.get(one.title, one.id))
            ids[one.id] = mine.id
            series.append(mine)

    last_day = week.start + timedelta(days=6)
    occurrences = [item for s in series for item in expand_series(s, week.items, week.start, last_day)]
    constraints = [_renamed(c, ids) for c in week.constraints]
    return Contents(week.items + occurrences, series, constraints, kept)


def _renamed(constraint: Constraint, ids: dict[UUID, UUID]) -> Constraint:
    if "series_ids" not in constraint.params:
        return constraint
    series_ids = list(dict.fromkeys(ids.get(i, i) for i in constraint.params["series_ids"]))
    return replace(constraint, params=constraint.params | {"series_ids": series_ids})


def import_week(path: Path, db: Path, replace: bool = False) -> str:
    """Import the week file at `path` into the database at `db` and return a summary line.

    The file's name is its source. Raises FileExistsError if that source was
    imported before and `replace` is false.
    """
    week = load_week(path)  # parse fully before touching the database
    source = path.name
    conn = store.connect(db)
    try:
        if store.has_source(conn, source) and not replace:
            raise FileExistsError(
                f"{source} was already imported into {db}. "
                f"Use --replace to replace the items, series and constraints that came from it."
            )
        contents = week_contents(week, conn, source)
        replaced, first = store.import_source(
            conn, source, week.settings, week.work_frames, contents.items, contents.constraints, contents.series
        )
    finally:
        conn.close()
    if first:
        frames = f"set the timezone and {len(week.work_frames)} work frames"
    else:
        frames = "kept the timezone and work frames already in the database"
    summary = (
        f"Imported {len(contents.items)} items, {len(contents.series)} series and {len(contents.constraints)} constraints "
        f"from {source} into {db}, and {frames}."
    )
    if contents.kept:
        summary += f" Kept the series already stored: {', '.join(contents.kept)}."
    return summary + (f" Replaced {replaced} items from the earlier import." if replace else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mycal-import", description="Import a TOML week file into the database.")
    parser.add_argument("week", type=Path, help="the week file, for example weeks/2026-11-16.toml")
    parser.add_argument("--db", type=Path, default=None, help=f"database file (default: ${store.DB_ENV} or data/mycal.db)")
    parser.add_argument("--replace", action="store_true", help="replace the items, series and constraints from an earlier import of this file")
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
