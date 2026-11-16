"""Importing a week file into the database, using the made-up sample week."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from mycal import Block, FlexPreset, Item, store
from mycal.demo import load_week
from mycal.importer import import_week, main

EXAMPLE = Path(__file__).parent.parent / "examples" / "week.toml"
SAMPLE_RULES = len(load_week(EXAMPLE).constraints)  # the next-week copy keeps them all


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "data" / "mycal.db"


def test_import_stores_the_whole_week(db: Path) -> None:
    summary = import_week(EXAMPLE, db)
    week = load_week(EXAMPLE)
    conn = store.connect(db)

    items = store.list_items(conn)
    titles = [i.title for i in items]
    # The file's own items, plus one occurrence per series date this week.
    assert titles[: len(week.items)] == [i.title for i in week.items]
    assert titles.count("Algorithms lecture") == 2  # Tue and Thu
    assert {"Gym", "Weekly problem set"} <= set(titles)
    assert all(i.series_id is not None for i in items[len(week.items) :])

    # Parsing the file again makes fresh UUIDs, so compare what the file says.
    assert store.load_settings(conn) == week.settings
    frame = lambda f: (f.name, f.weekdays, f.start_time, f.end_time, f.timezone)  # noqa: E731
    assert [frame(f) for f in store.list_work_frames(conn)] == [frame(f) for f in week.work_frames]
    kinds = lambda cs: [(c.kind, c.weight, c.hard) for c in cs]  # noqa: E731
    assert kinds(store.list_constraints(conn)) == kinds(week.constraints)
    assert store.list_blocks(conn) == []  # planned on first view, not imported
    assert summary.startswith(f"Imported {len(items)} items and {len(week.constraints)} constraints from week.toml")


def test_dependencies_survive_the_import(db: Path) -> None:
    import_week(EXAMPLE, db)
    items = {i.title: i for i in store.list_items(store.connect(db))}
    assert items["Project 3: write-up"].depends_on == [items["Project 3: implement"].id]
    assert items["Project 3: implement"].depends_on == [items["Project 3: design"].id]


def test_constraint_targets_point_at_imported_items(db: Path) -> None:
    import_week(EXAMPLE, db)
    conn = store.connect(db)
    item_ids = {i.id for i in store.list_items(conn)}
    series_ids = {i.series_id for i in store.list_items(conn)}
    for constraint in store.list_constraints(conn):
        assert set(constraint.params.get("item_ids", [])) <= item_ids
        assert set(constraint.params.get("series_ids", [])) <= series_ids


def next_week(tmp_path: Path) -> Path:
    """A second made-up week file: the sample with renamed items and one weekend frame."""
    text = EXAMPLE.read_text(encoding="utf-8").replace("Project 3", "Project 4").replace('title = "Call home"', 'title = "Call grandma"')
    text = text.replace("week_start = 2026-11-16", "week_start = 2026-11-23")
    start = text.index('[[work_frames]]\nname = "Weekdays"')
    end = text.index("[[work_frames]]", start + 1)
    path = tmp_path / "2026-11-23.toml"
    path.write_text(text[:start] + text[end:], encoding="utf-8")  # drops the weekday frame
    return path


def items_by_source(db: Path) -> dict[str | None, list[str]]:
    rows = store.connect(db).execute("SELECT source, title FROM items ORDER BY rowid").fetchall()
    grouped: dict[str | None, list[str]] = {}
    for row in rows:
        grouped.setdefault(row["source"], []).append(row["title"])
    return grouped


def test_importing_another_file_adds_to_the_database(db: Path, tmp_path: Path) -> None:
    import_week(EXAMPLE, db)
    import_week(next_week(tmp_path), db)
    grouped = items_by_source(db)
    assert set(grouped) == {"week.toml", "2026-11-23.toml"}
    assert "Project 3: design" in grouped["week.toml"]
    assert "Project 4: design" in grouped["2026-11-23.toml"]
    # Work frames are mine, not a week's: the latest file's frames replace the old ones.
    assert [f.name for f in store.list_work_frames(store.connect(db))] == ["Weekend"]
    sources = [r["source"] for r in store.connect(db).execute("SELECT source FROM constraints")]
    assert sorted(sources) == ["2026-11-23.toml"] * SAMPLE_RULES + ["week.toml"] * SAMPLE_RULES


def test_the_same_file_again_needs_replace(db: Path) -> None:
    import_week(EXAMPLE, db)
    first = store.list_items(store.connect(db))
    with pytest.raises(FileExistsError, match="--replace"):
        import_week(EXAMPLE, db)
    assert store.list_items(store.connect(db)) == first  # untouched


def test_replace_swaps_only_that_files_items(db: Path, tmp_path: Path) -> None:
    import_week(EXAMPLE, db)
    import_week(next_week(tmp_path), db)
    conn = store.connect(db)
    added = Item("Added in the app", FlexPreset.DAY, preset_params={"day": date(2026, 11, 18)}, estimate_min=30)
    store.put_item(conn, added)
    sample_item = next(i for i in store.list_items(conn) if i.title == "Call home")
    other_item = next(i for i in store.list_items(conn) if i.title == "Call grandma")
    store.put_blocks(conn, [block_for(sample_item), block_for(other_item), block_for(added)])
    before = items_by_source(db)

    summary = import_week(EXAMPLE, db, replace=True)

    after = items_by_source(db)
    assert after["week.toml"] == before["week.toml"]  # same titles, fresh items
    assert after["2026-11-23.toml"] == before["2026-11-23.toml"]
    assert after[None] == ["Added in the app"]
    titles = {i.id: i.title for i in store.list_items(store.connect(db))}
    kept = sorted(titles.get(b.item_id, "gone") for b in store.list_blocks(store.connect(db)))
    assert kept == ["Added in the app", "Call grandma"]  # the replaced item's block went with it
    assert f"Replaced {len(before['week.toml'])} items" in summary
    sources = [r["source"] for r in store.connect(db).execute("SELECT source FROM constraints")]
    assert sorted(sources) == ["2026-11-23.toml"] * SAMPLE_RULES + ["week.toml"] * SAMPLE_RULES  # no duplicates


def block_for(item: Item) -> Block:
    start = datetime(2026, 11, 18, 17, tzinfo=UTC)
    return Block(item.id, start, start + timedelta(hours=1))


def test_a_bad_file_changes_nothing(db: Path, tmp_path: Path) -> None:
    import_week(EXAMPLE, db)
    before = store.list_items(store.connect(db))
    broken = tmp_path / "broken.toml"
    broken.write_text('timezone = "America/Los_Angeles"\n', encoding="utf-8")
    with pytest.raises(KeyError):
        import_week(broken, db, replace=True)
    assert store.list_items(store.connect(db)) == before


def test_command_line(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(EXAMPLE), "--db", str(db)]) == 0
    assert "Imported" in capsys.readouterr().out
    assert main([str(EXAMPLE), "--db", str(db)]) == 1
    assert "already imported" in capsys.readouterr().err
    assert main([str(EXAMPLE), "--db", str(db), "--replace"]) == 0
    assert main(["missing.toml", "--db", str(db)]) == 1
