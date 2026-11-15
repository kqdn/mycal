"""SQLite storage for items, blocks, work frames, constraints and settings (Milestone 3).

Not part of the solver: like api.py and demo.py, this module is a caller. The
core modules never import it.

Storage rules:
    - Every entity is keyed by its UUID, stored as text (rule 3).
    - Exact moments are UTC ISO strings like "2026-11-16T17:00:00+00:00", so
      they sort and compare as text (rule 4).
    - Work-frame times stay local "HH:MM:SS" plus an IANA timezone (rule 4).
    - Item.windows is not stored: it is compiled from the preset whenever we
      solve (rule 6). Loaded items come back with no windows.
    - Blocks keep completed_at and actual_min (rule 8).
    - Items and constraints remember their `source`: the week file they were
      imported from, or None if added in the app. Saving one again keeps its
      source, so re-importing that file still finds it. Source lives only in
      the database, not on the model classes.
    - preset_params and constraint params are JSON. Values JSON has no type
      for (datetimes, dates, times, UUIDs, windows) are tagged, for example
      {"$type": "date", "value": "2026-11-16"}, so they load back exactly.

The schema version lives in PRAGMA user_version. MIGRATIONS[n] upgrades a
database from version n to n + 1; a database newer than this code is refused.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from uuid import UUID

from mycal.model import Block, BlockStatus, Constraint, FlexPreset, Item, OnMiss, Window, WorkFrame
from mycal.settings import SolverSettings

MIGRATIONS = [
    """
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE items (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        flex_preset TEXT NOT NULL,
        preset_params TEXT NOT NULL,
        checkable INTEGER NOT NULL,
        estimate_min INTEGER,
        deadline TEXT,
        parent_id TEXT REFERENCES items (id) ON DELETE CASCADE,
        max_chunk_min INTEGER,
        one_block_per_day INTEGER NOT NULL,
        on_miss TEXT NOT NULL,
        catch_up_of TEXT,
        series_id TEXT,
        occurrence_date TEXT,
        UNIQUE (series_id, occurrence_date)
    );
    CREATE TABLE item_deps (
        item_id TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
        depends_on TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        PRIMARY KEY (item_id, depends_on)
    );
    CREATE TABLE blocks (
        id TEXT PRIMARY KEY,
        item_id TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
        start TEXT NOT NULL,
        "end" TEXT NOT NULL,
        locked INTEGER NOT NULL,
        status TEXT NOT NULL,
        completed_at TEXT,
        actual_min INTEGER
    );
    CREATE INDEX blocks_by_start ON blocks (start);
    CREATE INDEX blocks_by_item ON blocks (item_id);
    CREATE TABLE work_frames (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        weekdays TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        timezone TEXT NOT NULL
    );
    CREATE TABLE constraints (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        params TEXT NOT NULL,
        weight REAL NOT NULL,
        hard INTEGER NOT NULL
    );
    """,
    # 2: where items and constraints came from. The week file's name, or NULL
    # for things added in the app.
    """
    ALTER TABLE items ADD COLUMN source TEXT;
    ALTER TABLE constraints ADD COLUMN source TEXT;
    CREATE INDEX items_by_source ON items (source);
    """,
    # 3: which weeks have a stored plan. A week with no row has never been
    # planned (or its plan was cleared); feasible is 0 when nothing fit.
    """
    CREATE TABLE planned_weeks (
        week_start TEXT PRIMARY KEY,
        feasible INTEGER NOT NULL,
        planned_at TEXT NOT NULL
    );
    """,
]
SCHEMA_VERSION = len(MIGRATIONS)

DB_ENV = "MYCAL_DB"


def db_path() -> Path:
    """Where the database lives: $MYCAL_DB, or data/mycal.db (run from solver/, gitignored)."""
    return Path(os.environ.get(DB_ENV, "data/mycal.db"))


# Connection and migrations


def connect(path: Path | str) -> sqlite3.Connection:
    """Open (or create) the database at `path` and bring its schema up to date.

    ":memory:" gives a throwaway database, which is handy in tests.
    """
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # off by default in SQLite
    migrate(conn)
    return conn


def copy_in_memory(conn: sqlite3.Connection) -> sqlite3.Connection:
    """A throwaway in-memory copy of the whole database, to try a change on before keeping it."""
    copy = sqlite3.connect(":memory:")
    conn.backup(copy)
    copy.row_factory = sqlite3.Row
    copy.execute("PRAGMA foreign_keys = ON")
    return copy


def keep_copy(copy: sqlite3.Connection, conn: sqlite3.Connection) -> None:
    """Write a copy made by copy_in_memory back over the database, replacing it as a whole."""
    copy.backup(conn)


def migrate(conn: sqlite3.Connection) -> None:
    """Run every migration the database hasn't had yet, each in its own transaction."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {current} is newer than this code ({SCHEMA_VERSION}); update mycal"
        )
    for version in range(current, SCHEMA_VERSION):
        # executescript commits first, so wrap each step in an explicit transaction.
        conn.executescript(f"BEGIN; {MIGRATIONS[version]} PRAGMA user_version = {version + 1}; COMMIT;")


# Imports


def has_source(conn: sqlite3.Connection, source: str) -> bool:
    """Whether anything was imported from `source` (a week file's name)."""
    query = "SELECT 1 FROM items WHERE source = ? UNION ALL SELECT 1 FROM constraints WHERE source = ? LIMIT 1"
    return conn.execute(query, (source, source)).fetchone() is not None


def import_source(
    conn: sqlite3.Connection,
    source: str,
    settings: SolverSettings,
    frames: list[WorkFrame],
    items: list[Item],
    constraints: list[Constraint],
) -> int:
    """Import one week file's contents in one transaction, and return how many earlier items it replaced.

    Items and constraints from an earlier import of the same `source` are
    replaced (their blocks go with them). Everything else stays: other files'
    items and items added in the app. Settings and work frames describe me, not
    a week, so the imported ones replace the current ones. If anything fails,
    nothing changes.
    """
    with conn:
        conn.execute("DELETE FROM planned_weeks")  # frames and items change, so every week re-plans
        replaced = conn.execute("DELETE FROM items WHERE source = ?", (source,)).rowcount
        conn.execute("DELETE FROM constraints WHERE source = ?", (source,))
        conn.execute("DELETE FROM work_frames")
        _write_settings(conn, settings)
        for frame in frames:
            _write_work_frame(conn, frame)
        # Item rows before dependency links, and parents before their subtasks,
        # since foreign keys are checked right away.
        for item in _parents_first(items):
            _write_item(conn, item, source)
        for item in items:
            _write_deps(conn, item)
        for constraint in constraints:
            _write_constraint(conn, constraint, source)
    return replaced


def _parents_first(items: list[Item]) -> list[Item]:
    """Items ordered so each parent comes before its subtasks; otherwise in the given order."""
    by_id = {item.id: item for item in items}
    ordered: list[Item] = []
    placed: set[UUID] = set()

    def place(item: Item) -> None:
        if item.id in placed:
            return
        if item.parent_id in by_id:
            place(by_id[item.parent_id])
        placed.add(item.id)
        ordered.append(item)

    for item in items:
        place(item)
    return ordered


# Plans


def plan_status(conn: sqlite3.Connection, week_start: date) -> bool | None:
    """Whether the stored plan for the week is feasible, or None if the week has no stored plan."""
    row = conn.execute("SELECT feasible FROM planned_weeks WHERE week_start = ?", (week_start.isoformat(),)).fetchone()
    return None if row is None else bool(row["feasible"])


def save_plan(
    conn: sqlite3.Connection,
    drop: list[UUID],
    blocks: list[Block],
    marks: dict[date, bool],
    planned_at: datetime,
) -> None:
    """Store a plan in one transaction: drop the old plan's blocks, write the new ones, mark weeks.

    `marks` maps a week's Monday to whether it fit. Weeks not in it keep their mark (or lack of one).
    """
    with conn:
        conn.executemany("DELETE FROM blocks WHERE id = ?", [(str(i),) for i in drop])
        _write_blocks(conn, blocks)
        conn.executemany(
            "INSERT OR REPLACE INTO planned_weeks (week_start, feasible, planned_at) VALUES (?, ?, ?)",
            [(week.isoformat(), int(fit), _moment(planned_at)) for week, fit in marks.items()],
        )


def clear_plans(conn: sqlite3.Connection) -> None:
    """Forget which weeks are planned, so each one re-plans when next viewed. Blocks stay as the current plan."""
    with conn:
        conn.execute("DELETE FROM planned_weeks")


# Settings


def save_settings(conn: sqlite3.Connection, settings: SolverSettings) -> None:
    with conn:
        _write_settings(conn, settings)


def _write_settings(conn: sqlite3.Connection, settings: SolverSettings) -> None:
    values = {
        "timezone": settings.timezone,
        "slot_min": settings.slot_min,
        "engine": settings.engine,
        "earliness_slack_min": settings.earliness_slack_min,
        "work_limit": settings.work_limit,
    }
    conn.executemany(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        [(key, json.dumps(value)) for key, value in values.items()],
    )


def load_settings(conn: sqlite3.Connection) -> SolverSettings | None:
    """The saved settings, or None before any are saved (there is no default timezone)."""
    values = {row["key"]: json.loads(row["value"]) for row in conn.execute("SELECT key, value FROM settings")}
    if "timezone" not in values:
        return None
    return SolverSettings(**values)


# Items


def put_item(conn: sqlite3.Connection, item: Item, source: str | None = None) -> None:
    """Insert or update an item and its dependencies. Its windows are not stored.

    `source` is recorded when the item is new; an update keeps the item's source.
    """
    with conn:
        _write_item(conn, item, source)
        _write_deps(conn, item)


def _write_item(conn: sqlite3.Connection, item: Item, source: str | None) -> None:
    conn.execute(
        """
        INSERT INTO items (id, title, flex_preset, preset_params, checkable, estimate_min, deadline,
                           parent_id, max_chunk_min, one_block_per_day, on_miss, catch_up_of,
                           series_id, occurrence_date, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            title = excluded.title, flex_preset = excluded.flex_preset,
            preset_params = excluded.preset_params, checkable = excluded.checkable,
            estimate_min = excluded.estimate_min, deadline = excluded.deadline,
            parent_id = excluded.parent_id, max_chunk_min = excluded.max_chunk_min,
            one_block_per_day = excluded.one_block_per_day, on_miss = excluded.on_miss,
            catch_up_of = excluded.catch_up_of, series_id = excluded.series_id,
            occurrence_date = excluded.occurrence_date
        """,
        (
            str(item.id),
            item.title,
            item.flex_preset.value,
            dump_json(item.preset_params),
            int(item.checkable),
            item.estimate_min,
            _moment(item.deadline),
            _id(item.parent_id),
            item.max_chunk_min,
            int(item.one_block_per_day),
            item.on_miss.value,
            _id(item.catch_up_of),
            _id(item.series_id),
            item.occurrence_date.isoformat() if item.occurrence_date else None,
            source,
        ),
    )


def _write_deps(conn: sqlite3.Connection, item: Item) -> None:
    conn.execute("DELETE FROM item_deps WHERE item_id = ?", (str(item.id),))
    conn.executemany(
        "INSERT INTO item_deps (item_id, depends_on, position) VALUES (?, ?, ?)",
        [(str(item.id), str(dep), i) for i, dep in enumerate(item.depends_on)],
    )


def get_item(conn: sqlite3.Connection, item_id: UUID) -> Item | None:
    row = conn.execute("SELECT * FROM items WHERE id = ?", (str(item_id),)).fetchone()
    return _item(conn, row) if row else None


def list_items(conn: sqlite3.Connection) -> list[Item]:
    return [_item(conn, row) for row in conn.execute("SELECT * FROM items ORDER BY rowid")]


def delete_item(conn: sqlite3.Connection, item_id: UUID) -> None:
    """Delete an item. Its blocks, subtasks and dependency links go with it."""
    with conn:
        conn.execute("DELETE FROM items WHERE id = ?", (str(item_id),))


def _item(conn: sqlite3.Connection, row: sqlite3.Row) -> Item:
    deps = conn.execute(
        "SELECT depends_on FROM item_deps WHERE item_id = ? ORDER BY position", (row["id"],)
    ).fetchall()
    return Item(
        id=UUID(row["id"]),
        title=row["title"],
        flex_preset=FlexPreset(row["flex_preset"]),
        preset_params=load_json(row["preset_params"]),
        checkable=bool(row["checkable"]),
        estimate_min=row["estimate_min"],
        deadline=_from_moment(row["deadline"]),
        parent_id=_from_id(row["parent_id"]),
        depends_on=[UUID(dep["depends_on"]) for dep in deps],
        max_chunk_min=row["max_chunk_min"],
        one_block_per_day=bool(row["one_block_per_day"]),
        on_miss=OnMiss(row["on_miss"]),
        catch_up_of=_from_id(row["catch_up_of"]),
        series_id=_from_id(row["series_id"]),
        occurrence_date=date.fromisoformat(row["occurrence_date"]) if row["occurrence_date"] else None,
    )


# Blocks


def put_blocks(conn: sqlite3.Connection, blocks: list[Block]) -> None:
    """Insert or replace blocks."""
    with conn:
        _write_blocks(conn, blocks)


def _write_blocks(conn: sqlite3.Connection, blocks: list[Block]) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO blocks (id, item_id, start, "end", locked, status, completed_at, actual_min)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                str(b.id),
                str(b.item_id),
                _moment(b.start),
                _moment(b.end),
                int(b.locked),
                b.status.value,
                _moment(b.completed_at),
                b.actual_min,
            )
            for b in blocks
        ],
    )


def list_blocks(
    conn: sqlite3.Connection, start: datetime | None = None, end: datetime | None = None
) -> list[Block]:
    """Blocks by start time. With `start` and `end`, only blocks that overlap [start, end)."""
    query, args = 'SELECT * FROM blocks', []
    if start is not None and end is not None:
        query += ' WHERE start < ? AND "end" > ?'
        args = [_moment(end), _moment(start)]
    rows = conn.execute(query + " ORDER BY start, id", args)
    return [
        Block(
            id=UUID(row["id"]),
            item_id=UUID(row["item_id"]),
            start=_from_moment(row["start"]),
            end=_from_moment(row["end"]),
            locked=bool(row["locked"]),
            status=BlockStatus(row["status"]),
            completed_at=_from_moment(row["completed_at"]),
            actual_min=row["actual_min"],
        )
        for row in rows
    ]


def delete_blocks(conn: sqlite3.Connection, block_ids: list[UUID]) -> None:
    with conn:
        conn.executemany("DELETE FROM blocks WHERE id = ?", [(str(i),) for i in block_ids])


# Work frames


def put_work_frame(conn: sqlite3.Connection, frame: WorkFrame) -> None:
    with conn:
        _write_work_frame(conn, frame)


def _write_work_frame(conn: sqlite3.Connection, frame: WorkFrame) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO work_frames (id, name, weekdays, start_time, end_time, timezone)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(frame.id),
            frame.name,
            json.dumps(frame.weekdays),
            frame.start_time.isoformat(),
            frame.end_time.isoformat(),
            frame.timezone,
        ),
    )


def list_work_frames(conn: sqlite3.Connection) -> list[WorkFrame]:
    return [
        WorkFrame(
            id=UUID(row["id"]),
            name=row["name"],
            weekdays=json.loads(row["weekdays"]),
            start_time=time.fromisoformat(row["start_time"]),
            end_time=time.fromisoformat(row["end_time"]),
            timezone=row["timezone"],
        )
        for row in conn.execute("SELECT * FROM work_frames ORDER BY rowid")
    ]


def delete_work_frame(conn: sqlite3.Connection, frame_id: UUID) -> None:
    with conn:
        conn.execute("DELETE FROM work_frames WHERE id = ?", (str(frame_id),))


# Constraints


def put_constraint(conn: sqlite3.Connection, constraint: Constraint, source: str | None = None) -> None:
    """Insert or update a constraint. Like items, an update keeps its source."""
    with conn:
        _write_constraint(conn, constraint, source)


def _write_constraint(conn: sqlite3.Connection, constraint: Constraint, source: str | None) -> None:
    conn.execute(
        """
        INSERT INTO constraints (id, kind, params, weight, hard, source) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            kind = excluded.kind, params = excluded.params, weight = excluded.weight, hard = excluded.hard
        """,
        (str(constraint.id), constraint.kind, dump_json(constraint.params), constraint.weight, int(constraint.hard), source),
    )


def list_constraints(conn: sqlite3.Connection) -> list[Constraint]:
    return [
        Constraint(
            id=UUID(row["id"]),
            kind=row["kind"],
            params=load_json(row["params"]),
            weight=row["weight"],
            hard=bool(row["hard"]),
        )
        for row in conn.execute("SELECT * FROM constraints ORDER BY rowid")
    ]


def delete_constraint(conn: sqlite3.Connection, constraint_id: UUID) -> None:
    with conn:
        conn.execute("DELETE FROM constraints WHERE id = ?", (str(constraint_id),))


# JSON with tagged values


def dump_json(value: Any) -> str:
    return json.dumps(_tag(value), sort_keys=True)


def load_json(text: str) -> Any:
    return json.loads(text, object_hook=_untag)


def _tag(value: Any) -> Any:
    """Turn values JSON has no type for into {"$type": ..., "value": ...}."""
    if isinstance(value, datetime):  # before date: a datetime is also a date
        return {"$type": "datetime", "value": _moment(value)}
    if isinstance(value, date):
        return {"$type": "date", "value": value.isoformat()}
    if isinstance(value, time):
        return {"$type": "time", "value": value.isoformat()}
    if isinstance(value, UUID):
        return {"$type": "uuid", "value": str(value)}
    if isinstance(value, Window):
        return {"$type": "window", "start": _moment(value.start), "end": _moment(value.end)}
    if isinstance(value, dict):
        return {key: _tag(v) for key, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_tag(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"Can't store {type(value).__name__} in JSON: {value!r}")


def _untag(obj: dict[str, Any]) -> Any:
    kind = obj.get("$type")
    if kind == "datetime":
        return _from_moment(obj["value"])
    if kind == "date":
        return date.fromisoformat(obj["value"])
    if kind == "time":
        return time.fromisoformat(obj["value"])
    if kind == "uuid":
        return UUID(obj["value"])
    if kind == "window":
        return Window(_from_moment(obj["start"]), _from_moment(obj["end"]))
    return obj


# Column helpers


def _moment(value: datetime | None) -> str | None:
    """A UTC moment as ISO text. Every stored moment has the same +00:00 suffix, so text order is time order."""
    return value.astimezone(UTC).isoformat() if value is not None else None


def _from_moment(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text).astimezone(UTC) if text is not None else None


def _id(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _from_id(text: str | None) -> UUID | None:
    return UUID(text) if text is not None else None
