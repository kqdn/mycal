"""Importing a week file into the database, using the made-up sample week."""

from pathlib import Path

import pytest

from mycal import store
from mycal.demo import load_week
from mycal.importer import import_week, main

EXAMPLE = Path(__file__).parent.parent / "examples" / "week.toml"


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
    assert summary.startswith(f"Imported {len(items)} items, 2 work frames and 3 constraints")


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


def test_a_second_import_needs_replace(db: Path) -> None:
    import_week(EXAMPLE, db)
    first = store.list_items(store.connect(db))
    with pytest.raises(FileExistsError, match="--replace"):
        import_week(EXAMPLE, db)
    assert store.list_items(store.connect(db)) == first  # untouched


def test_replace_swaps_everything(db: Path) -> None:
    import_week(EXAMPLE, db)
    import_week(EXAMPLE, db, replace=True)
    week = load_week(EXAMPLE)
    titles = [i.title for i in store.list_items(store.connect(db))]
    assert len(titles) == len(set(titles)) + 1  # only the two lecture occurrences share a title
    assert len(store.list_work_frames(store.connect(db))) == len(week.work_frames)


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
    assert "--replace" in capsys.readouterr().err
    assert main([str(EXAMPLE), "--db", str(db), "--replace"]) == 0
    assert main(["missing.toml", "--db", str(db)]) == 1
