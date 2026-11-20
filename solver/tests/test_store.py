"""SQLite store: every entity round-trips exactly, deletes cascade, and the schema migrates."""

import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from mycal import Block, BlockStatus, Constraint, FlexPreset, Item, OnMiss, SolverSettings, Window, WorkFrame
from mycal import store
from mycal.model import ItemTemplate, Rule, Series

LA = "America/Los_Angeles"
MON_9AM = datetime(2026, 11, 16, 17, tzinfo=UTC)  # 9am PST


@pytest.fixture
def conn() -> sqlite3.Connection:
    return store.connect(":memory:")


def item(title: str = "Task", preset: FlexPreset = FlexPreset.DAY, **fields) -> Item:  # type: ignore[no-untyped-def]
    fields.setdefault("preset_params", {"day": date(2026, 11, 16)})
    return Item(title, preset, **fields)


# Items


@pytest.mark.parametrize(
    ("preset", "params"),
    [
        (FlexPreset.EXACT, {"start": MON_9AM, "end": MON_9AM + timedelta(hours=1, minutes=30)}),
        (FlexPreset.DAY, {"day": date(2026, 11, 18)}),
        (FlexPreset.DAY_RANGE, {"day": date(2026, 11, 19), "start_time": time(17), "end_time": time(21)}),
        (FlexPreset.DAYS, {"weekdays": [0, 2, 4], "start_time": time(16), "end_time": time(21)}),
        (FlexPreset.BEFORE_DEADLINE, {}),
        (FlexPreset.CUSTOM, {"windows": [Window(MON_9AM, MON_9AM + timedelta(hours=2))]}),
    ],
)
def test_item_round_trips_with_its_preset_params(conn: sqlite3.Connection, preset: FlexPreset, params: dict) -> None:
    original = item("Gym", preset, preset_params=params, estimate_min=60)
    store.put_item(conn, original)
    assert store.get_item(conn, original.id) == original


def test_item_round_trips_every_field(conn: sqlite3.Connection) -> None:
    parent = item("Project 3")
    design = item("Design")
    store.put_item(conn, parent)
    store.put_item(conn, design)
    full = Item(
        "Implement",
        FlexPreset.BEFORE_DEADLINE,
        checkable=True,
        estimate_min=300,
        deadline=datetime(2026, 11, 23, 0, tzinfo=UTC),
        parent_id=parent.id,
        depends_on=[design.id, parent.id],  # order is kept
        max_chunk_min=120,
        one_block_per_day=True,
        keep_length=True,
        on_miss=OnMiss.CATCH_UP,
        catch_up_of=uuid4(),
        series_id=uuid4(),
        occurrence_date=date(2026, 11, 16),
    )
    store.put_item(conn, full)
    assert store.get_item(conn, full.id) == full
    assert [i.title for i in store.list_items(conn)] == ["Project 3", "Design", "Implement"]


def test_windows_are_not_stored(conn: sqlite3.Connection) -> None:
    compiled = item(windows=[Window(MON_9AM, MON_9AM + timedelta(hours=8))])
    store.put_item(conn, compiled)
    assert store.get_item(conn, compiled.id).windows == []


def test_putting_an_item_again_updates_it(conn: sqlite3.Connection) -> None:
    first = item("Draft", estimate_min=30)
    store.put_item(conn, first)
    first.title, first.estimate_min = "Final", 45
    store.put_item(conn, first)
    assert [(i.title, i.estimate_min) for i in store.list_items(conn)] == [("Final", 45)]


def test_deleting_an_item_takes_its_blocks_and_links(conn: sqlite3.Connection) -> None:
    keep, gone = item("Keep"), item("Gone")
    store.put_item(conn, gone)
    keep.depends_on = [gone.id]
    store.put_item(conn, keep)
    store.put_blocks(conn, [Block(gone.id, MON_9AM, MON_9AM + timedelta(hours=1))])

    store.delete_item(conn, gone.id)

    assert store.get_item(conn, gone.id) is None
    assert store.list_blocks(conn) == []
    assert store.get_item(conn, keep.id).depends_on == []


def test_two_occurrences_of_a_series_cannot_share_a_date(conn: sqlite3.Connection) -> None:
    series_id = uuid4()
    store.put_item(conn, item("Gym", series_id=series_id, occurrence_date=date(2026, 11, 16)))
    with pytest.raises(sqlite3.IntegrityError):
        store.put_item(conn, item("Gym", series_id=series_id, occurrence_date=date(2026, 11, 16)))


# Series


def lecture(**fields) -> Series:  # type: ignore[no-untyped-def]
    template = ItemTemplate(FlexPreset.EXACT, {"start_time": time(11), "end_time": time(12, 30)}, checkable=True)
    return Series("Lecture", Rule("weekly", 1, [1, 3]), LA, date(2026, 11, 16), template, **fields)


@pytest.mark.parametrize(
    "template",
    [
        ItemTemplate(FlexPreset.EXACT, {"start_time": time(11), "end_time": time(12, 30)}, checkable=True),
        ItemTemplate(FlexPreset.DAY_RANGE, {"start_time": time(17), "end_time": time(21)}, estimate_min=30),
        ItemTemplate(
            FlexPreset.DAYS,
            {"weekdays": [0, 2, 4], "every_day": True, "session_min": 30},
            estimate_min=90,
            max_chunk_min=30,
            one_block_per_day=True,
            keep_length=True,
            on_miss=OnMiss.SKIP,
        ),
        ItemTemplate(FlexPreset.BEFORE_DEADLINE, estimate_min=240, deadline_time=time(23, 59)),
    ],
)
def test_series_round_trips_with_its_template(conn: sqlite3.Connection, template: ItemTemplate) -> None:
    original = Series(
        "Weekly thing",
        Rule("weekly", 2, [1, 3]),
        LA,
        date(2026, 11, 16),
        template,
        end_date=date(2026, 12, 18),
        skipped_dates=[date(2026, 11, 26)],
    )
    store.put_series(conn, original)
    assert store.get_series(conn, original.id) == original
    assert store.list_series(conn) == [original]


def test_a_daily_series_with_no_end_round_trips(conn: sqlite3.Connection) -> None:
    piano = Series("Piano", Rule("daily", 1), LA, date(2026, 11, 16), ItemTemplate(FlexPreset.DAY, estimate_min=30))
    store.put_series(conn, piano)
    assert store.get_series(conn, piano.id) == piano


def test_saving_a_series_again_updates_it_and_keeps_its_source(conn: sqlite3.Connection) -> None:
    series = lecture()
    store.put_series(conn, series, source="2026-11-16.toml")
    series.end_date = date(2026, 12, 18)
    store.put_series(conn, series)
    assert store.get_series(conn, series.id) == series
    assert store.series_source(conn, series.id) == "2026-11-16.toml"


def test_deleting_a_series_takes_its_occurrences_and_their_blocks(conn: sqlite3.Connection) -> None:
    series = lecture()
    store.put_series(conn, series)
    tue = item("Lecture", series_id=series.id, occurrence_date=date(2026, 11, 17))
    other = item("Other")
    store.put_item(conn, tue)
    store.put_item(conn, other)
    store.put_blocks(conn, [Block(tue.id, MON_9AM, MON_9AM + timedelta(hours=1))])

    store.delete_series(conn, series.id)

    assert store.get_series(conn, series.id) is None
    assert store.list_items(conn) == [other]
    assert store.list_blocks(conn) == []


def test_deleting_a_series_drops_it_from_rules(conn: sqlite3.Connection) -> None:
    series = lecture()
    store.put_series(conn, series)
    gym = item("Gym")
    store.put_item(conn, gym)
    only_series = Constraint(kind="rest_between", params={"series_ids": [series.id]})
    both = Constraint(kind="rest_between", params={"item_ids": [gym.id], "series_ids": [series.id]})
    store.put_constraint(conn, only_series)
    store.put_constraint(conn, both)

    store.delete_series(conn, series.id)

    [left] = store.list_constraints(conn)  # a rule with no targets left is deleted, never "every item"
    assert left.id == both.id
    assert left.params == {"item_ids": [gym.id], "series_ids": []}


def test_a_series_known_only_from_its_occurrences_stays_a_rule_target(conn: sqlite3.Connection) -> None:
    # Occurrences imported before series were stored point to a series that was never saved.
    series_id = uuid4()
    store.put_item(conn, item("Lecture", series_id=series_id, occurrence_date=date(2026, 11, 17)))
    other = item("Other")
    store.put_item(conn, other)
    rule = Constraint(kind="rest_between", params={"series_ids": [series_id]})
    store.put_constraint(conn, rule)

    store.delete_item(conn, other.id)

    assert store.list_constraints(conn) == [rule]


def test_an_item_remembers_being_edited_by_hand(conn: sqlite3.Connection) -> None:
    occurrence = item("Lecture", series_id=uuid4(), occurrence_date=date(2026, 11, 17))
    store.put_item(conn, occurrence)
    assert not store.hand_edited(conn, occurrence.id)

    store.mark_hand_edited(conn, occurrence.id)
    occurrence.title = "Lecture (moved)"
    store.put_item(conn, occurrence)  # saving again keeps the mark

    assert store.hand_edited(conn, occurrence.id)


# Blocks


def test_block_round_trips_with_its_history(conn: sqlite3.Connection) -> None:
    owner = item()
    store.put_item(conn, owner)
    done = Block(
        owner.id,
        MON_9AM,
        MON_9AM + timedelta(minutes=45),
        locked=True,
        status=BlockStatus.PARTIAL,
        completed_at=MON_9AM + timedelta(minutes=50),
        actual_min=30,
        missed_action=OnMiss.CATCH_UP,
    )
    store.put_blocks(conn, [done])
    [loaded] = store.list_blocks(conn)
    assert loaded == done
    assert loaded.start.tzinfo is not None and loaded.start.utcoffset() == timedelta(0)


def test_blocks_can_be_listed_by_time_range(conn: sqlite3.Connection) -> None:
    owner = item()
    store.put_item(conn, owner)
    hour = timedelta(hours=1)
    early = Block(owner.id, MON_9AM, MON_9AM + hour)
    overnight = Block(owner.id, MON_9AM + 14 * hour, MON_9AM + 18 * hour)  # 11pm to 3am
    later = Block(owner.id, MON_9AM + 48 * hour, MON_9AM + 49 * hour)
    store.put_blocks(conn, [later, early, overnight])

    assert store.list_blocks(conn) == [early, overnight, later]
    assert store.list_blocks(conn, MON_9AM + 15 * hour, MON_9AM + 16 * hour) == [overnight]
    assert store.list_blocks(conn, MON_9AM + hour, MON_9AM + 14 * hour) == []  # touching is not overlapping


def test_a_block_needs_an_existing_item(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        store.put_blocks(conn, [Block(uuid4(), MON_9AM, MON_9AM + timedelta(hours=1))])


def test_blocks_can_be_deleted(conn: sqlite3.Connection) -> None:
    owner = item()
    store.put_item(conn, owner)
    a, b = (Block(owner.id, MON_9AM + timedelta(hours=h), MON_9AM + timedelta(hours=h + 1)) for h in (0, 2))
    store.put_blocks(conn, [a, b])
    store.delete_blocks(conn, [a.id])
    assert store.list_blocks(conn) == [b]


# Work frames, constraints, settings


def test_work_frame_round_trips(conn: sqlite3.Connection) -> None:
    night = WorkFrame("Weekday night", [0, 1, 2, 3, 4], time(21), time(2), LA)
    store.put_work_frame(conn, night)
    assert store.list_work_frames(conn) == [night]
    store.delete_work_frame(conn, night.id)
    assert store.list_work_frames(conn) == []


def test_constraint_round_trips_with_nested_params(conn: sqlite3.Connection) -> None:
    pref = Constraint(
        kind="time_preference",
        params={
            "mode": "prefer",
            "item_ids": [uuid4()],
            "series_ids": [uuid4()],
            "ranges": [{"weekdays": [5, 6], "start_time": time(12), "end_time": time(14)}],
        },
        weight=1.5,
    )
    limit = Constraint(kind="daily_limit", params={"max_min": 120, "weekdays": [5, 6]}, hard=True)
    store.put_constraint(conn, pref)
    store.put_constraint(conn, limit)
    assert store.list_constraints(conn) == [pref, limit]
    store.delete_constraint(conn, pref.id)
    assert store.list_constraints(conn) == [limit]


def test_settings_round_trip(conn: sqlite3.Connection) -> None:
    assert store.load_settings(conn) is None  # no default timezone, on purpose
    settings = SolverSettings(LA, slot_min=30, earliness_slack_min=10, work_limit=5.0)
    store.save_settings(conn, settings)
    assert store.load_settings(conn) == settings


def test_unstorable_values_are_refused() -> None:
    with pytest.raises(TypeError):
        store.dump_json({"when": object()})


# Schema


def test_a_new_database_gets_the_current_schema_and_keeps_its_data(tmp_path: Path) -> None:
    path = tmp_path / "data" / "mycal.db"
    conn = store.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    saved = item("Survives a restart")
    store.put_item(conn, saved)
    conn.close()

    reopened = store.connect(path)  # migrations don't run twice
    assert store.list_items(reopened) == [saved]


def test_a_newer_database_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "mycal.db"
    store.connect(path).execute(f"PRAGMA user_version = {store.SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError, match="newer"):
        store.connect(path)


def test_saving_again_keeps_the_source(conn: sqlite3.Connection) -> None:
    imported = item("From a week file")
    store.put_item(conn, imported, source="2026-11-16.toml")
    imported.title = "Edited in the app"
    store.put_item(conn, imported)  # an edit passes no source
    row = conn.execute("SELECT source FROM items WHERE id = ?", (str(imported.id),)).fetchone()
    assert row["source"] == "2026-11-16.toml"
    assert store.has_source(conn, "2026-11-16.toml")
    assert not store.has_source(conn, "2026-11-23.toml")


def test_a_version_1_database_upgrades_in_place(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(f"BEGIN; {store.MIGRATIONS[0]} PRAGMA user_version = 1; COMMIT;")
    old.execute(
        "INSERT INTO items (id, title, flex_preset, preset_params, checkable, one_block_per_day, on_miss) "
        "VALUES (?, 'Old item', 'day', ?, 0, 0, 'reschedule')",
        (str(uuid4()), store.dump_json({"day": date(2026, 11, 16)})),
    )
    old.commit()
    old.close()

    conn = store.connect(path)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    [row] = conn.execute("SELECT title, source FROM items").fetchall()
    assert (row["title"], row["source"]) == ("Old item", None)  # existing rows count as added in the app


def test_engine_settings_stored_by_old_imports_are_dropped(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(f"BEGIN; {''.join(store.MIGRATIONS[:3])} PRAGMA user_version = 3; COMMIT;")
    old.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)",
        [("timezone", '"America/Los_Angeles"'), ("slot_min", "15"), ("work_limit", "20.0"), ("engine", '"cp_sat"')],
    )
    old.commit()
    old.close()

    settings = store.load_settings(store.connect(path))

    assert settings == SolverSettings(LA)  # the old work limit of 20 is gone; the default applies


def test_a_version_4_database_gets_series_and_keeps_its_items(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(f"BEGIN; {''.join(store.MIGRATIONS[:4])} PRAGMA user_version = 4; COMMIT;")
    old.execute(
        "INSERT INTO items (id, title, flex_preset, preset_params, checkable, one_block_per_day, on_miss) "
        "VALUES (?, 'Old item', 'day', ?, 0, 0, 'reschedule')",
        (str(uuid4()), store.dump_json({"day": date(2026, 11, 16)})),
    )
    old.commit()
    old.close()

    conn = store.connect(path)

    [old_item] = store.list_items(conn)
    assert not store.hand_edited(conn, old_item.id)
    assert store.list_series(conn) == []


def test_a_rule_that_also_targets_a_series_keeps_it_when_its_item_goes(conn: sqlite3.Connection) -> None:
    gym = item("Gym")
    store.put_item(conn, gym)
    series_id = lecture().id
    store.put_series(conn, lecture(id=series_id))
    rule = Constraint(kind="rest_between", params={"item_ids": [gym.id], "series_ids": [series_id]})
    store.put_constraint(conn, rule)

    store.delete_item(conn, gym.id)

    [left] = store.list_constraints(conn)
    assert left.params == {"item_ids": [], "series_ids": [series_id]}


def test_archiving_hides_an_item_and_frees_what_named_it(conn: sqlite3.Connection) -> None:
    owner, other, sub = item(), item(), item()
    sub.parent_id = owner.id
    other.depends_on = [owner.id]
    for i in (owner, sub, other):
        store.put_item(conn, i)
    rule = Constraint(kind="rest_between", params={"min_gap_days": 1, "item_ids": [owner.id, other.id]})
    store.put_constraint(conn, rule)
    hour = timedelta(hours=1)
    done = Block(owner.id, MON_9AM, MON_9AM + hour, status=BlockStatus.DONE, actual_min=60)
    ahead = Block(owner.id, MON_9AM + 48 * hour, MON_9AM + 49 * hour)
    store.put_blocks(conn, [done, ahead])

    removed = store.archive_item(conn, owner.id, MON_9AM + 2 * hour)

    assert removed == [ahead]
    assert [i.id for i in store.list_items(conn)] == [other.id]  # its subtask is archived too
    assert {i.id for i in store.list_items(conn, include_archived=True)} == {owner.id, sub.id, other.id}
    assert store.list_blocks(conn) == [] and store.list_blocks(conn, include_archived=True) == [done]
    assert store.get_item(conn, other.id).depends_on == []  # type: ignore[union-attr]
    [kept] = store.list_constraints(conn)
    assert kept.params["item_ids"] == [other.id]


def test_a_series_saved_before_keep_length_loads_with_it_off(conn: sqlite3.Connection) -> None:
    series = Series("Weekly thing", Rule("weekly", 1, [1]), LA, date(2026, 11, 16), ItemTemplate(FlexPreset.DAY, estimate_min=60))
    store.put_series(conn, series)
    template = store.load_json(conn.execute("SELECT template FROM series").fetchone()["template"])
    del template["keep_length"]
    conn.execute("UPDATE series SET template = ?", (store.dump_json(template),))
    assert store.get_series(conn, series.id) == series
