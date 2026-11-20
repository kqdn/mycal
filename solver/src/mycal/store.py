"""SQLite storage for items, series, blocks, work frames, constraints and settings (Milestone 3).

Not part of the solver: like api.py and demo.py, this module is a caller. The
core modules never import it.

Storage rules:
    - Every entity is keyed by its UUID, stored as text (rule 3).
    - Exact moments are UTC ISO strings like "2026-11-16T17:00:00+00:00", so
      they sort and compare as text (rule 4).
    - Work-frame times stay local "HH:MM:SS" plus an IANA timezone (rule 4).
    - Item.windows is not stored: it is compiled from the preset whenever we
      solve (rule 6). Loaded items come back with no windows.
    - Blocks keep completed_at, actual_min and missed_action (rule 8).
    - Items and constraints remember their `source`: the week file they were
      imported from, or None if added in the app. Saving one again keeps its
      source, so re-importing that file still finds it. Source lives only in
      the database, not on the model classes.
    - Series (Milestone 6) store their rule and template as JSON, and remember
      their source like items. Occurrences point to their series by
      series_id, without a foreign key: occurrences imported before series
      were stored point to series that were never saved.
    - Items remember whether they were edited by hand (hand_edited), so a
      series edit leaves an occurrence changed on its own alone. Like source,
      it lives only in the database.
    - Items with check-in history are archived instead of deleted (Milestone
      7). list_items and list_blocks skip archived items and their blocks
      unless asked for them, so the app never plans or shows them.
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
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from uuid import UUID

from mycal.model import (
    Block,
    BlockStatus,
    Constraint,
    FlexPreset,
    Item,
    ItemTemplate,
    OnMiss,
    Rule,
    Series,
    Window,
    WorkFrame,
)
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
    # 4: engine settings come from the code's defaults, not from week files.
    # Imports used to store them, which pinned old values.
    """
    DELETE FROM settings WHERE key IN ('engine', 'work_limit', 'earliness_slack_min');
    """,
    # 5: series (Milestone 6), and which items were edited by hand. rule,
    # skipped_dates and template are JSON.
    """
    CREATE TABLE series (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        rule TEXT NOT NULL,
        timezone TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT,
        skipped_dates TEXT NOT NULL,
        template TEXT NOT NULL,
        source TEXT
    );
    ALTER TABLE items ADD COLUMN hand_edited INTEGER NOT NULL DEFAULT 0;
    CREATE INDEX items_by_series ON items (series_id);
    """,
    # 6: the on-miss policy that ran on a block's missed part (Milestone 7).
    # NULL when there is no missed part, or an Ask is still waiting.
    """
    ALTER TABLE blocks ADD COLUMN missed_action TEXT;
    """,
    # 7: "N times a week" items whose fewer sessions were accepted, and how
    # many sessions that was, so the banner shows again if it drops further.
    """
    CREATE TABLE shortfall_acks (
        item_id TEXT PRIMARY KEY REFERENCES items (id) ON DELETE CASCADE,
        gets INTEGER NOT NULL
    );
    """,
    # 8: archived items (Milestone 7): deleting an item with check-in history
    # archives it instead, keeping its finished blocks.
    """
    ALTER TABLE items ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
    """,
    # 9: items whose sessions are never shortened (Milestone 8, Don't shorten sessions).
    """
    ALTER TABLE items ADD COLUMN keep_length INTEGER NOT NULL DEFAULT 0;
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
    copy = sqlite3.connect(":memory:", check_same_thread=False)  # a proposal is used by later requests
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
    query = (
        "SELECT 1 FROM items WHERE source = ? UNION ALL SELECT 1 FROM constraints WHERE source = ? "
        "UNION ALL SELECT 1 FROM series WHERE source = ? LIMIT 1"
    )
    return conn.execute(query, (source, source, source)).fetchone() is not None


def import_source(
    conn: sqlite3.Connection,
    source: str,
    settings: SolverSettings,
    frames: list[WorkFrame],
    items: list[Item],
    constraints: list[Constraint],
    series: Sequence[Series] = (),
) -> tuple[int, bool]:
    """Import one week file's contents in one transaction.

    Returns how many earlier items it replaced, and whether it set the
    settings and work frames. Items, series and constraints from an earlier
    import of the same `source` are replaced (their blocks go with them, and so
    do occurrences the planner created for those series). Everything else
    stays: other files' items and series, and things added in the app. The timezone, slot
    size and work frames are set only by the first import into an empty
    database; after that they are edited in the app, and imports leave them
    alone. Engine settings never come from a file. If anything fails, nothing
    changes.
    """
    first = load_settings(conn) is None
    with conn:
        conn.execute("DELETE FROM planned_weeks")  # items change, so every week re-plans
        replaced = conn.execute("DELETE FROM items WHERE source = ?", (source,)).rowcount
        conn.execute("DELETE FROM series WHERE source = ?", (source,))
        conn.execute("DELETE FROM constraints WHERE source = ?", (source,))
        if first:
            _write_settings(conn, settings, FILE_SETTINGS)
            for frame in frames:
                _write_work_frame(conn, frame)
        # Item rows before dependency links, and parents before their subtasks,
        # since foreign keys are checked right away.
        for item in _parents_first(items):
            _write_item(conn, item, source)
        for item in items:
            _write_deps(conn, item)
        for one in series:
            _write_series(conn, one, source)
        for constraint in constraints:
            _write_constraint(conn, constraint, source)
        # Last, so a rule from the app naming a series that came back with the
        # same id keeps it.
        _drop_deleted_targets(conn)
    return replaced, first


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


def planned_weeks(conn: sqlite3.Connection) -> list[date]:
    """Every week (its Monday) that has a stored plan, earliest first."""
    return [date.fromisoformat(row["week_start"]) for row in conn.execute("SELECT week_start FROM planned_weeks ORDER BY week_start")]


def clear_plans(conn: sqlite3.Connection) -> None:
    """Forget which weeks are planned, so each one re-plans when next viewed. Blocks stay as the current plan."""
    with conn:
        conn.execute("DELETE FROM planned_weeks")


# Settings


# The settings a week file sets (on the first import). The rest belong to the
# engine and come from SolverSettings' defaults unless saved on purpose.
FILE_SETTINGS = ("timezone", "slot_min")
ALL_SETTINGS = FILE_SETTINGS + ("engine", "earliness_slack_min", "work_limit")


def save_settings(conn: sqlite3.Connection, settings: SolverSettings) -> None:
    """Store every setting, engine ones included (tests use it to set a small work limit)."""
    with conn:
        _write_settings(conn, settings, ALL_SETTINGS)


def _write_settings(conn: sqlite3.Connection, settings: SolverSettings, keys: tuple[str, ...]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        [(key, json.dumps(getattr(settings, key))) for key in keys],
    )


def load_settings(conn: sqlite3.Connection) -> SolverSettings | None:
    """The saved settings, or None before any are saved (there is no default timezone).

    Settings that aren't stored take SolverSettings' defaults.
    """
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
                           series_id, occurrence_date, source, keep_length)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            title = excluded.title, flex_preset = excluded.flex_preset,
            preset_params = excluded.preset_params, checkable = excluded.checkable,
            estimate_min = excluded.estimate_min, deadline = excluded.deadline,
            parent_id = excluded.parent_id, max_chunk_min = excluded.max_chunk_min,
            one_block_per_day = excluded.one_block_per_day, on_miss = excluded.on_miss,
            catch_up_of = excluded.catch_up_of, series_id = excluded.series_id,
            occurrence_date = excluded.occurrence_date, keep_length = excluded.keep_length
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
            int(item.keep_length),
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


def item_source(conn: sqlite3.Connection, item_id: UUID) -> str | None:
    """The week file an item was imported from, or None if it was added in the app (or is gone)."""
    row = conn.execute("SELECT source FROM items WHERE id = ?", (str(item_id),)).fetchone()
    return row["source"] if row else None


def list_items(conn: sqlite3.Connection, include_archived: bool = False) -> list[Item]:
    """Every item, in the order added. Archived items only with include_archived."""
    where = "" if include_archived else " WHERE archived = 0"
    return [_item(conn, row) for row in conn.execute(f"SELECT * FROM items{where} ORDER BY rowid")]


def archive_item(conn: sqlite3.Connection, item_id: UUID, moment: datetime) -> list[Block]:
    """Archive an item and its subtasks, keeping their history. Returns the blocks removed.

    Archived items leave the app: list_items and list_blocks skip them and
    their blocks, so nothing plans or shows them. Their planned blocks that
    haven't started are deleted, other items stop depending on them, and
    constraints stop naming them (see _drop_deleted_targets).
    """
    ids = _with_subtasks(conn, item_id)
    removed = [
        b for b in list_blocks(conn) if b.item_id in ids and b.status is BlockStatus.PLANNED and b.start > moment
    ]
    marks = [(str(i),) for i in ids]
    with conn:
        conn.executemany("UPDATE items SET archived = 1 WHERE id = ?", marks)
        conn.executemany("DELETE FROM item_deps WHERE depends_on = ? OR item_id = ?", [(m[0], m[0]) for m in marks])
        conn.executemany("DELETE FROM blocks WHERE id = ?", [(str(b.id),) for b in removed])
        _drop_deleted_targets(conn)
    return removed


def is_archived(conn: sqlite3.Connection, item_id: UUID) -> bool:
    row = conn.execute("SELECT archived FROM items WHERE id = ?", (str(item_id),)).fetchone()
    return bool(row and row["archived"])


def _with_subtasks(conn: sqlite3.Connection, item_id: UUID) -> set[UUID]:
    ids, frontier = {item_id}, [item_id]
    while frontier:
        rows = conn.execute("SELECT id FROM items WHERE parent_id = ?", (str(frontier.pop()),)).fetchall()
        for row in rows:
            child = UUID(row["id"])
            if child not in ids:
                ids.add(child)
                frontier.append(child)
    return ids


def delete_item(conn: sqlite3.Connection, item_id: UUID) -> None:
    """Delete an item. Its blocks, subtasks and dependency links go with it, and so does
    every constraint's reference to it (see _drop_deleted_targets)."""
    with conn:
        conn.execute("DELETE FROM items WHERE id = ?", (str(item_id),))
        _drop_deleted_targets(conn)


def _drop_deleted_targets(conn: sqlite3.Connection) -> None:
    """Remove ids of items and series that no longer exist (or are archived) from every constraint's targets.

    A series counts as existing while it is stored or any item still points to
    it, since occurrences imported before series were stored point to series
    that were never saved. A constraint left with no targets at all is
    deleted: no targets would mean "every item", turning a rule for one item
    into a rule for everything. The solver refuses unknown ids on purpose, so
    without this, deleting an item a constraint names would stop every week
    from planning.
    """
    items = {row["id"] for row in conn.execute("SELECT id FROM items WHERE archived = 0")}
    series = {row["id"] for row in conn.execute("SELECT id FROM series")}
    series |= {row["series_id"] for row in conn.execute("SELECT series_id FROM items WHERE series_id IS NOT NULL")}
    for row in conn.execute("SELECT id, params FROM constraints").fetchall():
        params = load_json(row["params"])
        item_ids, series_ids = params.get("item_ids") or [], params.get("series_ids") or []
        kept_items = [i for i in item_ids if str(i) in items]
        kept_series = [i for i in series_ids if str(i) in series]
        if len(kept_items) == len(item_ids) and len(kept_series) == len(series_ids):
            continue
        if not kept_items and not kept_series:
            conn.execute("DELETE FROM constraints WHERE id = ?", (row["id"],))
            continue
        for key, kept in (("item_ids", kept_items), ("series_ids", kept_series)):
            if key in params:
                params[key] = kept
        conn.execute("UPDATE constraints SET params = ? WHERE id = ?", (dump_json(params), row["id"]))


def mark_hand_edited(conn: sqlite3.Connection, item_id: UUID) -> None:
    """Record that an item was edited directly, so a series edit won't rebuild it."""
    with conn:
        conn.execute("UPDATE items SET hand_edited = 1 WHERE id = ?", (str(item_id),))


def hand_edited(conn: sqlite3.Connection, item_id: UUID) -> bool:
    row = conn.execute("SELECT hand_edited FROM items WHERE id = ?", (str(item_id),)).fetchone()
    return bool(row and row["hand_edited"])


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
        keep_length=bool(row["keep_length"]),
        on_miss=OnMiss(row["on_miss"]),
        catch_up_of=_from_id(row["catch_up_of"]),
        series_id=_from_id(row["series_id"]),
        occurrence_date=date.fromisoformat(row["occurrence_date"]) if row["occurrence_date"] else None,
    )


# Series


def put_series(conn: sqlite3.Connection, series: Series, source: str | None = None) -> None:
    """Insert or update a series. Like items, an update keeps its source."""
    with conn:
        _write_series(conn, series, source)


def _write_series(conn: sqlite3.Connection, series: Series, source: str | None) -> None:
    rule = {"freq": series.rule.freq, "interval": series.rule.interval, "weekdays": series.rule.weekdays}
    t = series.template
    template = {
        "flex_preset": t.flex_preset.value,
        "preset_params": t.preset_params,
        "estimate_min": t.estimate_min,
        "deadline_time": t.deadline_time,
        "checkable": t.checkable,
        "on_miss": t.on_miss.value,
        "max_chunk_min": t.max_chunk_min,
        "one_block_per_day": t.one_block_per_day,
        "keep_length": t.keep_length,
    }
    conn.execute(
        """
        INSERT INTO series (id, title, rule, timezone, start_date, end_date, skipped_dates, template, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            title = excluded.title, rule = excluded.rule, timezone = excluded.timezone,
            start_date = excluded.start_date, end_date = excluded.end_date,
            skipped_dates = excluded.skipped_dates, template = excluded.template
        """,
        (
            str(series.id),
            series.title,
            dump_json(rule),
            series.timezone,
            series.start_date.isoformat(),
            series.end_date.isoformat() if series.end_date else None,
            dump_json(series.skipped_dates),
            dump_json(template),
            source,
        ),
    )


def get_series(conn: sqlite3.Connection, series_id: UUID) -> Series | None:
    row = conn.execute("SELECT * FROM series WHERE id = ?", (str(series_id),)).fetchone()
    return _series(row) if row else None


def series_source(conn: sqlite3.Connection, series_id: UUID) -> str | None:
    """The week file a series was imported from, or None if it was added in the app (or is gone)."""
    row = conn.execute("SELECT source FROM series WHERE id = ?", (str(series_id),)).fetchone()
    return row["source"] if row else None


def list_series(conn: sqlite3.Connection) -> list[Series]:
    return [_series(row) for row in conn.execute("SELECT * FROM series ORDER BY rowid")]


def delete_series(conn: sqlite3.Connection, series_id: UUID) -> None:
    """Delete a series and every occurrence of it (their blocks go with them), and drop it from constraints."""
    with conn:
        conn.execute("DELETE FROM items WHERE series_id = ?", (str(series_id),))
        conn.execute("DELETE FROM series WHERE id = ?", (str(series_id),))
        _drop_deleted_targets(conn)


def _series(row: sqlite3.Row) -> Series:
    rule = load_json(row["rule"])
    t = load_json(row["template"])
    template = ItemTemplate(
        flex_preset=FlexPreset(t["flex_preset"]),
        preset_params=t["preset_params"],
        estimate_min=t["estimate_min"],
        deadline_time=t["deadline_time"],
        checkable=t["checkable"],
        on_miss=OnMiss(t["on_miss"]),
        max_chunk_min=t["max_chunk_min"],
        one_block_per_day=t["one_block_per_day"],
        keep_length=t.get("keep_length", False),  # added later than the other fields
    )
    return Series(
        id=UUID(row["id"]),
        title=row["title"],
        rule=Rule(rule["freq"], rule["interval"], rule["weekdays"]),
        timezone=row["timezone"],
        start_date=date.fromisoformat(row["start_date"]),
        end_date=date.fromisoformat(row["end_date"]) if row["end_date"] else None,
        skipped_dates=load_json(row["skipped_dates"]),
        template=template,
    )


# Blocks


def acknowledge_shortfall(conn: sqlite3.Connection, item_id: UUID, gets: int) -> None:
    """Remember that an item getting `gets` sessions was accepted, so its banner hides."""
    with conn:
        conn.execute("INSERT OR REPLACE INTO shortfall_acks (item_id, gets) VALUES (?, ?)", (str(item_id), gets))


def shortfall_acks(conn: sqlite3.Connection) -> dict[UUID, int]:
    """Accepted shortfalls: item id to the number of sessions that was accepted."""
    return {UUID(row["item_id"]): row["gets"] for row in conn.execute("SELECT item_id, gets FROM shortfall_acks")}


def put_blocks(conn: sqlite3.Connection, blocks: list[Block]) -> None:
    """Insert or replace blocks."""
    with conn:
        _write_blocks(conn, blocks)


def _write_blocks(conn: sqlite3.Connection, blocks: list[Block]) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO blocks
            (id, item_id, start, "end", locked, status, completed_at, actual_min, missed_action)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                None if b.missed_action is None else b.missed_action.value,
            )
            for b in blocks
        ],
    )


def list_blocks(
    conn: sqlite3.Connection,
    start: datetime | None = None,
    end: datetime | None = None,
    include_archived: bool = False,
) -> list[Block]:
    """Blocks by start time. With `start` and `end`, only blocks that overlap [start, end).

    Blocks of archived items only with include_archived.
    """
    query = "SELECT blocks.* FROM blocks JOIN items ON items.id = blocks.item_id"
    conditions: list[str] = [] if include_archived else ["items.archived = 0"]
    args: list[str | None] = []
    if start is not None and end is not None:
        conditions.append('blocks.start < ? AND blocks."end" > ?')
        args = [_moment(end), _moment(start)]
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    rows = conn.execute(query + " ORDER BY blocks.start, blocks.id", args)
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
            missed_action=None if row["missed_action"] is None else OnMiss(row["missed_action"]),
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


def constraint_source(conn: sqlite3.Connection, constraint_id: UUID) -> str | None:
    """The week file a constraint was imported from, or None if it was added in the app (or is gone)."""
    row = conn.execute("SELECT source FROM constraints WHERE id = ?", (str(constraint_id),)).fetchone()
    return row["source"] if row else None


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
