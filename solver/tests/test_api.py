"""The week API, serving stored plans from a temporary database with the made-up sample week."""

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from mycal import Block, Constraint, FlexPreset, Item, api, store
from mycal.importer import import_week
from mycal.solve import solve

EXAMPLE = Path(__file__).parent.parent / "examples" / "week.toml"
WEEK = "2026-11-16"
BEFORE_THE_WEEK = datetime(2026, 11, 15, 12, tzinfo=UTC)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "mycal.db"
    monkeypatch.setenv(store.DB_ENV, str(path))
    monkeypatch.setattr(api, "now", lambda: BEFORE_THE_WEEK)
    import_week(EXAMPLE, path)
    end_series(path, date(2026, 11, 22))
    return path


def end_series(path: Path, last_day: date) -> None:
    """End every stored series on `last_day`. The tests here were written when the
    example's series came in for its own week only, so later weeks stay empty."""
    conn = store.connect(path)
    for series in store.list_series(conn):
        store.put_series(conn, replace(series, end_date=last_day))
    conn.close()


@pytest.fixture
def client(db: Path) -> TestClient:
    return TestClient(app=api.app)


@pytest.fixture
def solves(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Counts calls to solve() made while planning."""
    calls: list[int] = []

    def counting_solve(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(1)
        return solve(*args, **kwargs)

    monkeypatch.setattr("mycal.planner.solve", counting_solve)
    return calls


def get(client: TestClient, week: str = WEEK) -> dict:
    response = client.get(f"/api/weeks/{week}")
    assert response.status_code == 200, response.text
    return response.json()


def plan_again(db: Path, when: datetime, monkeypatch: pytest.MonkeyPatch) -> None:
    store.clear_plans(store.connect(db))
    monkeypatch.setattr(api, "now", lambda: when)


# Serving


def test_a_week_is_planned_and_returned_in_utc(client: TestClient) -> None:
    week = get(client)
    assert (week["week_start"], week["timezone"], week["slot_min"], week["feasible"]) == (WEEK, "America/Los_Angeles", 15, True)
    blocks = {b["title"]: b for b in reversed(week["blocks"])}  # the first block of each title wins
    lecture = blocks["Algorithms lecture"]
    assert (lecture["start"], lecture["end"], lecture["fixed"]) == (
        "2026-11-17T19:00:00Z",  # Tue 11am PST
        "2026-11-17T20:30:00Z",
        True,
    )
    assert blocks["Chemistry lab"]["fixed"] is False
    assert week["frames"][0] == {"start": "2026-11-16T17:00:00Z", "end": "2026-11-17T02:00:00Z"}  # Mon 9 to 6
    assert week["unscheduled"] == [
        {"id": week["unscheduled"][0]["id"], "title": "Email advisor", "estimate_min": 15, "reason": None, "sessions": 0, "editable": False, "series_id": None,
         "history": False, "kept": 0}
    ]
    stored = {s.title: s.id for s in store.list_series(store.connect(store.db_path()))}
    assert lecture["series_id"] == str(stored["Algorithms lecture"])
    assert blocks["Chemistry lab"]["series_id"] is None
    repeats = {r["id"]: r for r in week["series"]}
    assert repeats[str(stored["Algorithms lecture"])] == {
        "id": str(stored["Algorithms lecture"]), "freq": "weekly", "interval": 1, "weekdays": [1, 3], "per_week": False,
        "end_date": "2026-11-22",  # the fixture ends the example's series with its week
    }
    assert repeats[str(stored["Gym"])]["per_week"] is True


def test_a_stored_plan_is_served_without_solving_again(client: TestClient, solves: list[int]) -> None:
    first = get(client)
    assert TestClient(app=api.app).get(f"/api/weeks/{WEEK}").json() == first  # a restart too
    assert len(solves) == 1


def test_an_empty_week_still_shows_its_frames(client: TestClient) -> None:
    week = get(client, "2026-12-07")
    assert (week["feasible"], week["blocks"], len(week["frames"])) == (True, [], 7)


def test_nothing_imported_is_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(store.DB_ENV, str(tmp_path / "empty.db"))
    response = TestClient(app=api.app).get(f"/api/weeks/{WEEK}")
    assert response.status_code == 404
    assert "mycal-import" in response.json()["detail"]


@pytest.mark.parametrize("bad", ["not-a-date", "2026-13-01"])
def test_bad_date_is_422(client: TestClient, bad: str) -> None:
    assert client.get(f"/api/weeks/{bad}").status_code == 422


def test_path_tricks_match_no_route(client: TestClient) -> None:
    assert client.get("/api/weeks/..%2F..%2Fpyproject").status_code == 404


# Re-planning


def test_an_import_clears_plans_so_weeks_re_plan(db: Path, client: TestClient, solves: list[int]) -> None:
    get(client)
    import_week(EXAMPLE, db, replace=True)
    get(client)
    assert len(solves) == 2


def test_re_planning_keeps_blocks_in_place(db: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    before = get(client)["blocks"]
    plan_again(db, BEFORE_THE_WEEK, monkeypatch)
    assert get(client)["blocks"] == before  # same ids, same times


def test_blocks_that_started_never_move_and_new_ones_go_after_now(
    db: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    get(client)
    wednesday_noon = datetime(2026, 11, 18, 20, tzinfo=UTC)
    conn = store.connect(db)
    started = [b for b in store.list_blocks(conn) if b.start < wednesday_noon]
    assert started and len(started) < len(store.list_blocks(conn))  # some before, some after

    plan_again(db, wednesday_noon, monkeypatch)
    week = get(client)

    def spots(blocks: list[Block]) -> list[tuple[UUID, datetime, datetime]]:
        return [(b.id, b.start, b.end) for b in blocks]

    # Checkable ones went unanswered by now (Milestone 7), but none moved.
    assert spots([b for b in store.list_blocks(store.connect(db)) if b.start < wednesday_noon]) == spots(started)
    started_ids = {str(b.id) for b in started}
    new = [b for b in week["blocks"] if b["id"] not in started_ids]
    assert new and all(datetime.fromisoformat(b["start"]) >= wednesday_noon for b in new)


def test_work_planned_in_another_week_counts(db: Path, client: TestClient) -> None:
    # 2h due the next Tuesday, allowed any day. The first week takes it all, so the next week adds nothing.
    conn = store.connect(db)
    report = Item(
        "Report",
        FlexPreset.BEFORE_DEADLINE,
        estimate_min=120,
        deadline=datetime(2026, 11, 25, 2, tzinfo=UTC),  # Tue Nov 24, 6pm PST
    )
    store.put_item(conn, report)
    store.clear_plans(conn)

    this_week = [b for b in get(client)["blocks"] if b["title"] == "Report"]
    next_week = [b for b in get(client, "2026-11-23")["blocks"] if b["title"] == "Report"]

    assert sum(minutes(b) for b in this_week) == 120
    assert next_week == []


def test_a_week_that_cannot_fit_is_stored_as_infeasible(db: Path, client: TestClient, solves: list[int]) -> None:
    conn = store.connect(db)
    store.put_item(conn, Item("Too much", FlexPreset.DAY, preset_params={"day": date(2026, 11, 18)}, estimate_min=20 * 60))
    store.clear_plans(conn)
    first = get(client)
    assert (first["feasible"], first["blocks"]) == (False, [])
    assert get(client) == first  # stored, not solved again
    assert len(solves) == 1


def minutes(block: dict) -> float:
    start, end = (datetime.fromisoformat(block[k]) for k in ("start", "end"))
    return (end - start) / timedelta(minutes=1)


# Adding and deleting items


def add(client: TestClient, **fields) -> dict:  # type: ignore[no-untyped-def]
    response = client.post("/api/items", json={"week_start": WEEK, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def refused(client: TestClient, **fields) -> str:  # type: ignore[no-untyped-def]
    response = client.post("/api/items", json={"week_start": WEEK, **fields})
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, str)  # a sentence the dialog can show
    return detail


def blocks_titled(week: dict, title: str) -> list[dict]:
    return [b for b in week["blocks"] if b["title"] == title]


def local(block: dict) -> tuple[str, str]:
    """A block's start and end as local "Day HH:MM"."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/Los_Angeles")
    return tuple(datetime.fromisoformat(block[k]).astimezone(zone).strftime("%a %H:%M") for k in ("start", "end"))  # type: ignore[return-value]


def test_add_an_exact_item(client: TestClient) -> None:
    week = add(client, title="Dentist", preset="exact", day="2026-11-19", start_time="13:00", end_time="14:00")
    [block] = blocks_titled(week, "Dentist")
    assert local(block) == ("Thu 13:00", "Thu 14:00")
    assert block["fixed"] is True


def test_add_an_exact_item_off_the_slot_grid(client: TestClient) -> None:
    week = add(client, title="Class", preset="exact", day="2026-11-19", start_time="13:10", end_time="14:00")
    assert [local(b) for b in blocks_titled(week, "Class")] == [("Thu 13:10", "Thu 14:00")]


def test_add_an_overnight_exact_item(client: TestClient) -> None:
    week = add(client, title="Night drive", preset="exact", day="2026-11-19", start_time="23:00", end_time="01:00")
    assert [local(b) for b in blocks_titled(week, "Night drive")] == [("Thu 23:00", "Fri 01:00")]


def test_add_items_on_a_day_and_in_a_range(client: TestClient) -> None:
    add(client, title="Errand", preset="day", day="2026-11-18", estimate_min=30)
    week = add(
        client, title="Call", preset="day_range", day="2026-11-19", start_time="17:00", end_time="21:00", estimate_min=30
    )
    [errand] = blocks_titled(week, "Errand")
    [call] = blocks_titled(week, "Call")
    assert local(errand)[0].startswith("Wed")
    assert "17:00" <= local(call)[0][4:] and local(call)[1][4:] <= "21:00" and local(call)[0].startswith("Thu")


def test_a_days_item_stays_in_the_viewed_week(client: TestClient) -> None:
    week = add(client, title="Swim", preset="days", weekdays=[1, 3], estimate_min=120, max_chunk_min=60, one_block_per_day=True)
    assert sorted(local(b)[0][:3] for b in blocks_titled(week, "Swim")) == ["Thu", "Tue"]
    assert blocks_titled(get(client, "2026-11-23"), "Swim") == []


MONDAY_MORNING = datetime(2026, 11, 16, 8, tzinfo=UTC)  # Mon Nov 16, 12am PST


def test_a_deadline_item_fills_the_earliest_week_first(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Due next Wednesday, added on Monday morning: this week takes all of it.
    monkeypatch.setattr(api, "now", lambda: MONDAY_MORNING)
    essay = {"title": "Essay", "preset": "before_deadline", "deadline_date": "2026-11-25", "deadline_time": "17:00"}
    week = add(client, **essay, estimate_min=120)
    assert sum(minutes(b) for b in blocks_titled(week, "Essay")) == 120
    assert blocks_titled(get(client, "2026-11-23"), "Essay") == []


def test_a_deadline_item_only_uses_the_weeks_up_to_its_deadline(client: TestClient) -> None:
    # Added Sunday Nov 15, due Wed Nov 25. Spans hold at most two weeks, so it is
    # planned in the weeks of Nov 16 and 23, not that Sunday (three weeks back),
    # and the earlier of the two takes it.
    essay = {"title": "Essay", "preset": "before_deadline", "deadline_date": "2026-11-25", "deadline_time": "17:00"}
    add(client, **essay, estimate_min=60)
    assert blocks_titled(get(client, "2026-11-09"), "Essay") == []
    assert sum(minutes(b) for b in blocks_titled(get(client), "Essay")) == 60


def test_adding_keeps_other_blocks_in_place(client: TestClient) -> None:
    before = {b["id"]: b for b in get(client)["blocks"]}
    # Sunday has free frame time and nothing else wants it.
    week = add(client, title="Tea", preset="day", day="2026-11-22", estimate_min=15)
    after = {b["id"]: b for b in week["blocks"] if b["title"] != "Tea"}
    assert after == before


def test_an_added_item_is_stored_as_added_in_the_app(db: Path, client: TestClient) -> None:
    add(client, title="Errand", preset="day", day="2026-11-18", estimate_min=30)
    row = store.connect(db).execute("SELECT source FROM items WHERE title = 'Errand'").fetchone()
    assert row["source"] is None


def test_an_item_that_does_not_fit_is_refused_and_nothing_changes(db: Path, client: TestClient) -> None:
    before = get(client)
    items_before = len(store.list_items(store.connect(db)))
    detail = refused(client, title="Marathon", preset="day", day="2026-11-18", estimate_min=20 * 60)
    assert "doesn't fit" in detail
    assert get(client) == before
    assert len(store.list_items(store.connect(db))) == items_before


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"title": "  ", "preset": "day", "day": "2026-11-18", "estimate_min": 30}, "title"),
        ({"title": "X", "preset": "day", "day": "2026-11-18"}, "estimate"),
        ({"title": "X", "preset": "exact", "day": "2026-11-18", "start_time": "09:00", "end_time": "10:00", "estimate_min": 60}, "no estimate"),
        ({"title": "X", "preset": "exact", "day": "2026-11-18", "start_time": "9", "end_time": "10:00"}, "start_time"),
        ({"title": "X", "preset": "day_range", "day": "2026-11-18", "start_time": "09:00", "estimate_min": 30}, "start and an end"),
        ({"title": "X", "preset": "days", "weekdays": [], "estimate_min": 30}, "at least one day"),
        ({"title": "X", "preset": "before_deadline", "deadline_date": "2026-11-10", "deadline_time": "12:00", "estimate_min": 30}, "already passed"),
        ({"title": "X", "preset": "day", "day": "2026-11-10", "estimate_min": 30}, "already passed"),
        ({"title": "X", "preset": "day", "estimate_min": 30}, "date"),
        ({"title": "X", "preset": "every_day", "weekdays": [0]}, "length for each day"),
        ({"title": "X", "preset": "every_day", "weekdays": [0], "session_min": 30, "estimate_min": 30}, "no estimate"),
        ({"title": "X", "preset": "every_day", "weekdays": [], "session_min": 30}, "at least one day"),
    ],
)
def test_bad_items_are_refused_with_a_message(client: TestClient, fields: dict, message: str) -> None:
    assert message in refused(client, **fields)


def test_custom_items_cannot_be_added_yet(client: TestClient) -> None:
    response = client.post("/api/items", json={"week_start": WEEK, "title": "X", "preset": "custom", "estimate_min": 30})
    assert response.status_code == 422


def test_delete_an_item_and_its_blocks(db: Path, client: TestClient) -> None:
    week = add(client, title="Errand", preset="day", day="2026-11-18", estimate_min=30)
    [errand] = blocks_titled(week, "Errand")
    response = client.delete(f"/api/items/{errand['item_id']}", params={"week": WEEK})
    assert response.status_code == 200
    assert blocks_titled(response.json(), "Errand") == []
    assert store.get_item(store.connect(db), UUID(errand["item_id"])) is None


def test_delete_an_imported_item(db: Path, client: TestClient) -> None:
    [lab] = blocks_titled(get(client), "Chemistry lab")
    response = client.delete(f"/api/items/{lab['item_id']}", params={"week": WEEK})
    assert blocks_titled(response.json(), "Chemistry lab") == []


def test_deleting_a_missing_item_is_404(client: TestClient) -> None:
    response = client.delete(f"/api/items/{uuid4()}", params={"week": WEEK})
    assert response.status_code == 404


SATURDAY_EVENING = datetime(2026, 11, 15, 3, 44, tzinfo=UTC)  # Sat Nov 14, 7:44pm PST


def test_work_that_cannot_fit_the_rest_of_this_week_goes_to_next_week(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reproduces a reported bug. On Saturday evening only Sunday is left of the
    # week of Nov 9, and 2h in 1h sessions, one per day, needs two days. The week
    # of Nov 16 has plenty of room, so the add must succeed, with the work there.
    monkeypatch.setattr(api, "now", lambda: SATURDAY_EVENING)
    get(client)  # the page shows Nov 16 first...
    get(client, "2026-11-09")  # ...then prefetches the week before, which fits
    week = add(
        client,
        title="Reading",
        preset="before_deadline",
        deadline_date="2026-11-21",
        deadline_time="23:59",
        estimate_min=120,
        max_chunk_min=60,
        one_block_per_day=True,
    )
    reading = blocks_titled(week, "Reading") + blocks_titled(get(client, "2026-11-09"), "Reading")
    assert sum(minutes(b) for b in reading) == 120
    assert len({local(b)[0][:3] for b in reading}) == 2  # two different days


# Spans and broken weeks. Week 2 is Nov 23 to 29, week 3 is Nov 30 to Dec 6.

WEEK_2, WEEK_3 = "2026-11-23", "2026-11-30"


def pacific(day: int, hour: int, month: int = 12) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime(2026, month, day, hour, tzinfo=ZoneInfo("America/Los_Angeles")).astimezone(UTC)


def break_week_3(db: Path) -> None:
    """Two fixed events in the same hour on Tue Dec 1: week 3 can't be planned."""
    conn = store.connect(db)
    for title in ("Dentist", "Exam"):
        store.put_item(conn, Item(title, FlexPreset.EXACT, preset_params={"start": pacific(1, 13), "end": pacific(1, 14)}))
    store.clear_plans(conn)


def status(db: Path, week: str) -> bool | None:
    return store.plan_status(store.connect(db), date.fromisoformat(week))


def test_viewing_a_week_plans_its_span_and_marks_only_that_week(db: Path, client: TestClient) -> None:
    # Due next Tuesday: the span is this week and next, and the work lands in this week.
    conn = store.connect(db)
    store.put_item(conn, Item("Report", FlexPreset.BEFORE_DEADLINE, estimate_min=60, deadline=pacific(24, 17, month=11)))
    store.clear_plans(conn)
    assert sum(minutes(b) for b in blocks_titled(get(client), "Report")) == 60
    assert (status(db, WEEK), status(db, WEEK_2)) == (True, None)  # next week re-plans when viewed


def test_an_item_due_far_ahead_is_only_planned_in_the_weeks_up_to_its_deadline(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "now", lambda: MONDAY_MORNING)
    add(client, title="Thesis", preset="before_deadline", deadline_date="2027-01-13", deadline_time="17:00", estimate_min=120)
    assert blocks_titled(get(client), "Thesis") == []  # not this week, eight weeks early
    assert sum(minutes(b) for b in blocks_titled(get(client, "2027-01-04"), "Thesis")) == 120


def test_a_broken_week_is_blamed_alone_and_its_waiting_item_is_listed(db: Path, client: TestClient) -> None:
    # Report is due Wed of the broken week, with more work than week 2 can hold.
    break_week_3(db)
    conn = store.connect(db)
    store.put_item(
        conn, Item("Report", FlexPreset.BEFORE_DEADLINE, estimate_min=55 * 60, max_chunk_min=9 * 60, deadline=pacific(2, 17))
    )
    store.clear_plans(conn)

    week_2 = get(client, WEEK_2)

    assert (week_2["feasible"], status(db, WEEK_2), status(db, WEEK_3)) == (True, True, False)
    assert blocks_titled(week_2, "Report") == []
    [waiting] = [u for u in week_2["unscheduled"] if u["title"] == "Report"]
    assert waiting["reason"] == "Waiting on Nov 30 to Dec 6, which can't be planned."
    assert get(client, WEEK_3)["feasible"] is False


def test_an_item_due_before_the_broken_week_is_added(db: Path, client: TestClient) -> None:
    break_week_3(db)
    add(client, week_start=WEEK_2, title="Memo", preset="before_deadline", deadline_date="2026-11-27", deadline_time="17:00", estimate_min=60)
    memo = blocks_titled(get(client), "Memo") + blocks_titled(get(client, WEEK_2), "Memo")
    assert sum(minutes(b) for b in memo) == 60  # the earlier week takes it
    assert status(db, WEEK_3) is None  # the broken week wasn't part of it


def test_an_item_due_in_the_broken_week_goes_before_it(db: Path, client: TestClient) -> None:
    break_week_3(db)
    week = add(client, week_start=WEEK_2, title="Memo", preset="before_deadline", deadline_date="2026-12-02", deadline_time="17:00", estimate_min=60)
    [memo] = blocks_titled(week, "Memo")
    assert datetime.fromisoformat(memo["end"]) <= pacific(30, 0, month=11)  # in week 2


def test_an_item_that_can_only_go_in_the_broken_week_is_refused(db: Path, client: TestClient) -> None:
    break_week_3(db)
    detail = refused(client, week_start=WEEK_3, title="Errand", preset="day", day="2026-12-01", estimate_min=30)
    assert detail.startswith("Nothing was added: the week of Nov 30 to Dec 6 already can't be planned.")
    assert all(i.title != "Errand" for i in store.list_items(store.connect(db)))


def test_work_deferred_by_the_span_cap_is_not_listed_as_waiting(db: Path, client: TestClient) -> None:
    # Due four weeks out: deferred while this week is planned, but nothing is broken.
    conn = store.connect(db)
    store.put_item(conn, Item("Thesis", FlexPreset.BEFORE_DEADLINE, estimate_min=120, deadline=pacific(16, 17)))
    store.clear_plans(conn)
    week = get(client)
    assert blocks_titled(week, "Thesis") == []
    assert all(u["title"] != "Thesis" for u in week["unscheduled"])



# Planner timeouts: the work limit ran out before any arrangement was found.


@pytest.fixture
def slow(db: Path) -> Path:
    """A database whose solves always run out of work budget."""
    from dataclasses import replace as replaced

    conn = store.connect(db)
    store.save_settings(conn, replaced(store.load_settings(conn), work_limit=0.001))
    store.clear_plans(conn)
    return db


def test_a_timeout_while_viewing_is_503_and_the_week_stays_unplanned(slow: Path, client: TestClient) -> None:
    response = client.get(f"/api/weeks/{WEEK}")
    assert response.status_code == 503
    assert response.json()["detail"] == "The planner ran out of time planning this week. Its old plan is kept."
    assert status(slow, WEEK) is None  # the next view tries again


def test_a_timeout_while_adding_is_503_not_doesnt_fit_and_adds_nothing(slow: Path, client: TestClient) -> None:
    response = client.post(
        "/api/items", json={"week_start": WEEK, "title": "Errand", "preset": "day", "day": "2026-11-18", "estimate_min": 30}
    )
    assert response.status_code == 503
    assert "ran out of time" in response.json()["detail"] and "doesn't fit" not in response.json()["detail"]
    assert all(i.title != "Errand" for i in store.list_items(store.connect(slow)))


def test_a_timeout_while_deleting_still_deletes(slow: Path, client: TestClient) -> None:
    lab = next(i for i in store.list_items(store.connect(slow)) if i.title == "Chemistry lab")
    response = client.delete(f"/api/items/{lab.id}", params={"week": WEEK})
    assert response.status_code == 200
    assert store.get_item(store.connect(slow), lab.id) is None


# Session details on each block


def test_sessions_are_counted_across_weeks(db: Path, client: TestClient) -> None:
    # One session placed by hand in week 2 (locked), one placed by the solver in week 1.
    conn = store.connect(db)
    report = Item("Report", FlexPreset.BEFORE_DEADLINE, estimate_min=120, max_chunk_min=60, deadline=pacific(27, 17, month=11))
    store.put_item(conn, report)
    store.put_blocks(conn, [Block(report.id, pacific(24, 9, month=11), pacific(24, 10, month=11), locked=True)])
    store.clear_plans(conn)

    [first] = blocks_titled(get(client), "Report")
    [second] = blocks_titled(get(client, WEEK_2), "Report")

    assert (first["session"], second["session"], first["sessions"], second["sessions"]) == (1, 2, 2, 2)
    assert (second["placed_min"], second["estimate_min"]) == (120, 120)


def test_waiting_work_shows_less_placed_than_estimated(db: Path, client: TestClient) -> None:
    # Work due in a broken week, after an hour of it was placed by hand in week 2.
    break_week_3(db)
    conn = store.connect(db)
    report = Item("Report", FlexPreset.BEFORE_DEADLINE, estimate_min=55 * 60, max_chunk_min=9 * 60, deadline=pacific(2, 17))
    store.put_item(conn, report)
    store.put_blocks(conn, [Block(report.id, pacific(24, 9, month=11), pacific(24, 10, month=11), locked=True)])
    store.clear_plans(conn)

    [block] = blocks_titled(get(client, WEEK_2), "Report")
    assert (block["sessions"], block["placed_min"], block["estimate_min"]) == (1, 60, 55 * 60)


def test_an_exact_item_has_no_estimate_and_one_session(client: TestClient) -> None:
    lecture = blocks_titled(get(client), "Algorithms lecture")[0]
    assert (lecture["estimate_min"], lecture["sessions"], lecture["session"]) == (None, 1, 1)


def test_two_overlapping_requests_run_one_at_a_time(db: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    import time as clock

    from mycal import planner

    get(client)
    conn = store.connect(db)
    lab = next(i for i in store.list_items(conn) if i.title == "Chemistry lab")
    call = next(i for i in store.list_items(conn) if i.title == "Call home")

    inside, most_inside = 0, 0
    counting = threading.Lock()
    real_plan_weeks = planner.plan_weeks

    def watched_plan_weeks(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal inside, most_inside
        with counting:
            inside += 1
            most_inside = max(most_inside, inside)
        clock.sleep(0.2)  # widen the window two requests could overlap in
        try:
            return real_plan_weeks(*args, **kwargs)
        finally:
            with counting:
                inside -= 1

    monkeypatch.setattr(api, "plan_weeks", watched_plan_weeks)
    start = threading.Barrier(2)
    codes: list[int] = []

    def delete(item_id: UUID) -> None:
        start.wait()
        codes.append(TestClient(app=api.app).delete(f"/api/items/{item_id}", params={"week": WEEK}).status_code)

    threads = [threading.Thread(target=delete, args=(i.id,)) for i in (lab, call)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert codes == [200, 200]
    assert most_inside == 1  # never two plans at once
    conn = store.connect(db)
    items = {i.id for i in store.list_items(conn)}
    assert lab.id not in items and call.id not in items
    blocks = sorted(store.list_blocks(conn), key=lambda b: b.start)
    assert all(b.item_id in items for b in blocks)
    assert all(a.end <= b.start for a, b in zip(blocks, blocks[1:]))
    assert store.plan_status(conn, date.fromisoformat(WEEK)) is True



def test_deleting_an_item_a_constraint_targets_keeps_planning_working(db: Path, client: TestClient) -> None:
    # A rest rule for the lab alone, and a time preference for the lab and the call.
    conn = store.connect(db)
    items = {i.title: i for i in store.list_items(conn)}
    lab, call = items["Chemistry lab"], items["Call home"]
    rest = Constraint(kind="rest_between", params={"item_ids": [lab.id]})
    prefer = Constraint(
        kind="time_preference",
        params={"item_ids": [lab.id, call.id], "mode": "prefer", "weekdays": [0, 1, 2, 3, 4], "start_time": time(9), "end_time": time(12)},
    )
    store.put_constraint(conn, rest)
    store.put_constraint(conn, prefer)
    store.clear_plans(conn)
    get(client)

    response = client.delete(f"/api/items/{lab.id}", params={"week": WEEK})

    assert response.status_code == 200, response.text
    assert get(client, WEEK_3)["feasible"] is True  # later weeks still plan
    left = {c.id: c for c in store.list_constraints(store.connect(db))}
    assert rest.id not in left  # its only target is gone, so the rule goes too
    assert left[prefer.id].params["item_ids"] == [call.id]


def test_an_every_day_item_shows_the_work_it_still_has(db: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # The week was planned before it began; Piano arrives on Wednesday at noon. Mon and Tue
    # have passed, so its work is three sessions, not the five its stored estimate says.
    get(client)
    conn = store.connect(db)
    params = {"week": date(2026, 11, 16), "weekdays": [0, 1, 2, 3, 4], "every_day": True, "session_min": 30}
    store.put_item(conn, Item("Piano", FlexPreset.DAYS, preset_params=params, estimate_min=150, max_chunk_min=30, one_block_per_day=True))
    plan_again(db, pacific(18, 12, month=11), monkeypatch)

    piano = blocks_titled(get(client), "Piano")

    assert sorted(local(b)[0][:3] for b in piano) == ["Fri", "Thu", "Wed"]
    assert {(b["placed_min"], b["estimate_min"]) for b in piano} == {(90, 90)}


def test_add_an_every_day_item_mid_week(db: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Added on Wednesday at noon: all five picked days are saved, sessions go on Wed, Thu and Fri.
    get(client)
    monkeypatch.setattr(api, "now", lambda: pacific(18, 12, month=11))

    week = add(client, title="Piano", preset="every_day", weekdays=[0, 1, 2, 3, 4], start_time="18:00", end_time="20:00", session_min=30)

    piano = blocks_titled(week, "Piano")
    assert sorted(local(b)[0][:3] for b in piano) == ["Fri", "Thu", "Wed"]
    assert all(minutes(b) == 30 for b in piano)
    assert {(b["placed_min"], b["estimate_min"]) for b in piano} == {(90, 90)}
    [item] = [i for i in store.list_items(store.connect(db)) if i.title == "Piano"]
    assert item.preset_params["weekdays"] == [0, 1, 2, 3, 4]
    assert (item.preset_params["every_day"], item.preset_params["session_min"]) == (True, 30)


def test_an_every_day_session_off_the_grid_is_stored_as_typed_and_planned_rounded_up(
    db: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    get(client)
    monkeypatch.setattr(api, "now", lambda: pacific(18, 12, month=11))

    week = add(client, title="Piano", preset="every_day", weekdays=[2, 3, 4], start_time="18:00", end_time="20:00", session_min=20)

    piano = blocks_titled(week, "Piano")
    assert len(piano) == 3 and all(minutes(b) == 30 for b in piano)
    assert {(b["placed_min"], b["estimate_min"]) for b in piano} == {(90, 90)}
    [item] = [i for i in store.list_items(store.connect(db)) if i.title == "Piano"]
    assert item.preset_params["session_min"] == 20


def test_an_estimate_off_the_grid_is_stored_as_typed_and_planned_rounded_up(db: Path, client: TestClient) -> None:
    week = add(client, title="Stretch", preset="day", day="2026-11-18", estimate_min=20)

    [block] = blocks_titled(week, "Stretch")
    assert (minutes(block), block["estimate_min"]) == (30, 30)
    [item] = [i for i in store.list_items(store.connect(db)) if i.title == "Stretch"]
    assert item.estimate_min == 20


def test_an_every_day_item_with_no_day_left_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Wednesday 7:45pm: Mon and Tue have passed and Wednesday's 6 to 8pm has 15 minutes left.
    monkeypatch.setattr(api, "now", lambda: pacific(18, 19, month=11) + timedelta(minutes=45))

    detail = refused(client, title="Piano", preset="every_day", weekdays=[0, 1, 2], start_time="18:00", end_time="20:00", session_min=30)

    assert detail == api.NO_DAY_LEFT


# Editing items


def item_id(db: Path, title: str) -> UUID:
    [item] = [i for i in store.list_items(store.connect(db)) if i.title == title]
    return item.id


def fetch(client: TestClient, id_: UUID) -> dict:
    response = client.get(f"/api/items/{id_}")
    assert response.status_code == 200, response.text
    return response.json()


def put(client: TestClient, id_: UUID, form: dict, week: str = WEEK, status: int = 200) -> dict:
    body = {k: v for k, v in form.items() if k not in ("id", "source", "editable")}
    response = client.put(f"/api/items/{id_}", params={"week": week}, json=body)
    assert response.status_code == status, response.text
    return response.json()


def item_blocks(db: Path, id_: UUID) -> list[tuple[UUID, datetime, datetime]]:
    return sorted((b.id, b.start, b.end) for b in store.list_blocks(store.connect(db)) if b.item_id == id_)


@pytest.mark.parametrize(
    "fields",
    [
        {"title": "Dentist", "preset": "exact", "day": "2026-11-19", "start_time": "23:00", "end_time": "01:00"},
        {"title": "Errand", "preset": "day", "day": "2026-11-18", "estimate_min": 20},
        {"title": "Call", "preset": "day_range", "day": "2026-11-17", "start_time": "17:00", "end_time": "19:00", "estimate_min": 30},
        {"title": "Read", "preset": "days", "weekdays": [1, 3], "estimate_min": 90, "max_chunk_min": 45, "one_block_per_day": True},
        {"title": "Piano", "preset": "every_day", "weekdays": [0, 2], "start_time": "18:00", "end_time": "20:00", "session_min": 20},
        {"title": "Essay", "preset": "before_deadline", "deadline_date": "2026-11-20", "deadline_time": "17:00", "estimate_min": 60},
    ],
    ids=["exact", "day", "day_range", "days", "every_day", "before_deadline"],
)
def test_saving_an_item_unchanged_changes_nothing(db: Path, client: TestClient, fields: dict) -> None:
    add(client, **fields)
    id_ = item_id(db, fields["title"])
    form, before = fetch(client, id_), item_blocks(db, id_)

    as_sent = {k: f"{v}:00" if k.endswith("_time") else v for k, v in fields.items()}  # times come back with seconds
    assert {k: form[k] for k in fields} == as_sent
    assert (form["editable"], form["source"]) == (True, None)
    put(client, id_, form)

    assert item_blocks(db, id_) == before
    assert fetch(client, id_) == form


def test_a_bigger_estimate_re_plans(db: Path, client: TestClient) -> None:
    id_ = item_id(db, "Chemistry lab")
    get(client)
    form = fetch(client, id_)

    week = put(client, id_, form | {"estimate_min": 180, "max_chunk_min": 60})

    lab = blocks_titled(week, "Chemistry lab")
    assert sum(minutes(b) for b in lab) == 180 and all(minutes(b) == 60 for b in lab)
    assert all(local(b)[0].startswith("Wed") for b in lab)


def test_moving_a_day_item_moves_its_block_and_re_plans_the_old_week(db: Path, client: TestClient) -> None:
    id_ = item_id(db, "Chemistry lab")
    get(client)

    put(client, id_, fetch(client, id_) | {"day": "2026-11-24", "week_start": "2026-11-23"})

    assert blocks_titled(get(client), "Chemistry lab") == []
    [moved] = blocks_titled(get(client, "2026-11-23"), "Chemistry lab")
    assert local(moved)[0].startswith("Tue")


def test_moving_a_days_item_to_another_week(db: Path, client: TestClient) -> None:
    add(client, title="Read", preset="days", weekdays=[1], estimate_min=60)
    id_ = item_id(db, "Read")

    put(client, id_, fetch(client, id_) | {"week_start": "2026-11-23"})

    assert blocks_titled(get(client), "Read") == []
    assert len(blocks_titled(get(client, "2026-11-23"), "Read")) == 1


def test_a_change_that_does_not_fit_is_refused_and_changes_nothing(db: Path, client: TestClient) -> None:
    id_ = item_id(db, "Chemistry lab")
    get(client)
    form, before = fetch(client, id_), item_blocks(db, id_)

    detail = put(client, id_, form | {"estimate_min": 20 * 60}, status=422)["detail"]

    assert detail == api.DOES_NOT_FIT
    assert (fetch(client, id_), item_blocks(db, id_)) == (form, before)


def test_a_past_item_can_be_renamed_but_not_moved_into_the_past(
    db: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    id_ = item_id(db, "Chemistry lab")
    get(client)
    monkeypatch.setattr(api, "now", lambda: pacific(20, 12, month=11))  # Friday: Wednesday's lab is over
    form = fetch(client, id_)

    put(client, id_, form | {"title": "Chem lab"})
    assert fetch(client, id_)["title"] == "Chem lab"

    detail = put(client, id_, form | {"day": "2026-11-19"}, status=422)["detail"]
    assert detail == "That time has already passed."


def test_a_started_fixed_event_can_be_renamed_but_not_moved(
    db: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    add(client, title="Dentist", preset="exact", day="2026-11-19", start_time="13:00", end_time="14:00")
    id_ = item_id(db, "Dentist")
    monkeypatch.setattr(api, "now", lambda: pacific(19, 13, month=11) + timedelta(minutes=10))
    form = fetch(client, id_)

    assert put(client, id_, form | {"end_time": "15:00"}, status=422)["detail"] == api.ALREADY_STARTED
    put(client, id_, form | {"title": "Dentist (cleaning)"})
    assert fetch(client, id_)["title"] == "Dentist (cleaning)"


def test_custom_items_and_missing_items_cannot_be_edited(db: Path, client: TestClient) -> None:
    id_ = item_id(db, "Email advisor")
    form = fetch(client, id_)
    assert (form["preset"], form["editable"]) == ("custom", False)
    week = get(client)
    assert [i["editable"] for i in week["unscheduled"] if i["title"] == "Email advisor"] == [False]
    assert {b["editable"] for b in week["blocks"]} == {True}

    body = {"title": "Email", "preset": "day", "day": "2026-11-18", "estimate_min": 15, "week_start": WEEK}
    assert put(client, id_, body, status=422)["detail"] == api.CUSTOM_NOT_EDITABLE
    assert put(client, uuid4(), body, status=404)["detail"] == api.ITEM_GONE
    assert client.get(f"/api/items/{uuid4()}").status_code == 404


def test_editing_keeps_the_fields_the_dialog_does_not_show(db: Path, client: TestClient) -> None:
    id_ = item_id(db, "Project 3: implement")
    get(client)
    conn = store.connect(db)
    before = store.get_item(conn, id_)
    assert before is not None and before.depends_on and store.item_source(conn, id_) == "week.toml"
    form = fetch(client, id_)
    assert form["source"] == "week.toml"

    put(client, id_, form | {"title": "Project 3: build", "estimate_min": 240})

    after = store.get_item(store.connect(db), id_)
    assert after is not None
    assert (after.title, after.estimate_min, after.depends_on, after.checkable) == (
        "Project 3: build", 240, before.depends_on, before.checkable,
    )
    assert store.item_source(store.connect(db), id_) == "week.toml"


def test_editing_a_lecture_keeps_it_checkable(db: Path, client: TestClient) -> None:
    get(client)
    lectures = [i for i in store.list_items(store.connect(db)) if i.title == "Algorithms lecture"]
    lecture = lectures[0]
    assert lecture.checkable

    put(client, lecture.id, fetch(client, lecture.id) | {"title": "Algorithms"})

    after = store.get_item(store.connect(db), lecture.id)
    assert after is not None and (after.title, after.checkable, after.series_id) == ("Algorithms", True, lecture.series_id)


# Work frames


WEEKDAYS_FRAME = {"name": "Weekdays", "weekdays": [0, 1, 2, 3, 4], "start_time": "09:00", "end_time": "18:00"}


def frames(client: TestClient) -> list[dict]:
    response = client.get("/api/frames")
    assert response.status_code == 200, response.text
    return response.json()


def frame_id(client: TestClient, name: str) -> str:
    return next(f["id"] for f in frames(client) if f["name"] == name)


def test_frames_are_listed_by_first_day_then_start(client: TestClient) -> None:
    assert [(f["name"], f["weekdays"], f["start_time"], f["end_time"]) for f in frames(client)] == [
        ("Weekdays", [0, 1, 2, 3, 4], "09:00:00", "18:00:00"),
        ("Weekend", [5, 6], "10:00:00", "16:00:00"),
    ]


def test_adding_a_frame_stores_it_and_returns_the_week(client: TestClient) -> None:
    get(client)
    evenings = {"name": "Evenings", "weekdays": [0, 2], "start_time": "19:00", "end_time": "22:00"}
    response = client.post(f"/api/frames?week={WEEK}", json=evenings)
    assert response.status_code == 201, response.text
    assert response.json()["week_start"] == WEEK
    assert [f["name"] for f in frames(client)] == ["Weekdays", "Evenings", "Weekend"]
    # The page shades the new frame time: Monday now has two frame spans.
    assert len(response.json()["frames"]) == 9


def test_shrinking_a_frame_re_plans_the_week_into_it(client: TestClient) -> None:
    gym_before = {local(b) for b in blocks_titled(get(client), "Gym")}
    assert all(start.endswith("16:00") for start, _ in gym_before)  # its preferred 4 to 6pm
    id_ = frame_id(client, "Weekdays")
    response = client.put(f"/api/frames/{id_}?week={WEEK}", json=WEEKDAYS_FRAME | {"end_time": "15:00"})
    assert response.status_code == 200, response.text
    gym = blocks_titled(response.json(), "Gym")
    assert len(gym) == 3
    assert all(end <= f"{end[:3]} 15:00" for _, end in map(local, gym))  # inside 9 to 3 now


def test_a_frame_change_that_breaks_the_week_changes_nothing(db: Path, client: TestClient) -> None:
    before = get(client)["blocks"]
    id_ = frame_id(client, "Weekdays")
    response = client.put(f"/api/frames/{id_}?week={WEEK}", json=WEEKDAYS_FRAME | {"end_time": "09:30"})
    assert response.status_code == 422, response.text
    assert response.json()["detail"].startswith("Nothing changed: the week of Nov 16 to 22 wouldn't fit.")
    assert frames(client)[0]["end_time"] == "18:00:00"
    assert get(client)["blocks"] == before
    assert status(db, WEEK) is True


def test_deleting_a_frame_moves_work_out_of_its_days(client: TestClient) -> None:
    get(client)
    response = client.delete(f"/api/frames/{frame_id(client, 'Weekend')}?week={WEEK}")
    assert response.status_code == 200, response.text
    assert [f["name"] for f in frames(client)] == ["Weekdays"]
    weekend = [b for b in response.json()["blocks"] if local(b)[0][:3] in ("Sat", "Sun")]
    assert weekend == []


def test_a_frame_change_clears_the_plans_of_other_weeks(db: Path, client: TestClient) -> None:
    get(client)
    store.save_plan(store.connect(db), [], [], {date(2026, 11, 2): True}, BEFORE_THE_WEEK)
    evenings = {"name": "Evenings", "weekdays": [0], "start_time": "19:00", "end_time": "22:00"}
    assert client.post(f"/api/frames?week={WEEK}", json=evenings).status_code == 201
    assert status(db, "2026-11-02") is None  # re-plans when next viewed
    assert status(db, WEEK) is True


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"name": "  "}, "Give it a name, like Weekdays."),
        ({"weekdays": []}, "Pick at least one day."),
        ({"end_time": "09:00"}, "Start and end can't be the same time."),
    ],
)
def test_a_bad_frame_is_refused_with_the_dialogs_message(client: TestClient, change: dict, message: str) -> None:
    response = client.post(f"/api/frames?week={WEEK}", json=WEEKDAYS_FRAME | change)
    assert (response.status_code, response.json()["detail"]) == (422, message)
    assert len(frames(client)) == 2


def test_changing_a_missing_frame_is_404(client: TestClient) -> None:
    response = client.put(f"/api/frames/{uuid4()}?week={WEEK}", json=WEEKDAYS_FRAME)
    assert (response.status_code, response.json()["detail"]) == (404, "That work frame no longer exists.")
    assert client.delete(f"/api/frames/{uuid4()}?week={WEEK}").status_code == 404


# Rules


def rules(client: TestClient) -> list[dict]:
    response = client.get("/api/rules")
    assert response.status_code == 200, response.text
    return response.json()


def targets(client: TestClient) -> dict[str, dict]:
    response = client.get("/api/rules/targets")
    assert response.status_code == 200, response.text
    return {t["title"]: t for t in response.json()}


def add_rule(client: TestClient, status: int = 201, **fields) -> dict:  # type: ignore[no-untyped-def]
    response = client.post(f"/api/rules?week={WEEK}", json=fields)
    assert response.status_code == status, response.text
    return response.json()


def test_rules_are_listed_in_the_dialogs_terms(client: TestClient) -> None:
    listed = rules(client)
    assert [r["kind"] for r in listed] == ["daily_limit", "time_preference", "time_preference", "rest_between"]
    limit, gym_pref, reading, rest = listed
    assert (limit["max_min"], limit["weekdays"], limit["targets"], limit["source"]) == (120, [5, 6], [], "week.toml")
    assert gym_pref["mode"] == "prefer"
    assert gym_pref["ranges"] == [
        {"weekdays": [0, 1, 2, 3, 4], "start_time": "16:00:00", "end_time": "18:00:00"},
        {"weekdays": [5, 6], "start_time": "12:00:00", "end_time": "14:00:00"},
    ]
    assert [(t["kind"], t["title"]) for t in gym_pref["targets"]] == [("series", "Gym")]
    # A single top-level range in the file comes back as one range.
    assert reading["ranges"] == [{"weekdays": [0, 1, 2, 3, 4], "start_time": "09:00:00", "end_time": "12:00:00"}]
    assert (rest["min_gap_days"], rest["every_item"]) == (1, False)


def test_targets_list_series_first_then_one_off_items(client: TestClient) -> None:
    listed = list(targets(client).values())
    kinds = [t["kind"] for t in listed]
    assert kinds == sorted(kinds, key=lambda k: k != "series")
    by_title = targets(client)
    assert by_title["Gym"]["week_start"] is None
    assert by_title["Chemistry lab"]["week_start"] == WEEK
    assert "Email advisor" not in by_title  # nothing to place it in, so nothing to rule on


def test_an_avoid_rule_moves_work_out_of_its_times(client: TestClient) -> None:
    week_before = get(client)
    before = [local(b) for b in blocks_titled(week_before, "Project 3: design")]
    assert before[0][0].endswith("09:00")
    others = {b["id"]: (b["start"], b["end"]) for b in week_before["blocks"] if not b["title"].startswith("Project 3")}
    design = targets(client)["Project 3: design"]["id"]
    week = add_rule(
        client,
        kind="time_preference",
        mode="avoid",
        ranges=[{"weekdays": [0, 1, 2, 3, 4], "start_time": "09:00", "end_time": "12:00"}],
        item_ids=[design],
    )
    after = [local(b) for b in blocks_titled(week, "Project 3: design")]
    assert all(start[4:] >= "12:00" for start, _ in after)
    # Only the work the rule covers is placed again (and what depends on it); everything else stays put.
    moved = [b["title"] for b in week["blocks"] if b["id"] in others and (b["start"], b["end"]) != others[b["id"]]]
    assert len(moved) <= 2, moved
    added = rules(client)[-2]  # time preferences come before rest days
    assert (added["mode"], added["source"], [t["title"] for t in added["targets"]]) == ("avoid", None, ["Project 3: design"])


def test_a_daily_limit_that_breaks_the_week_changes_nothing(client: TestClient) -> None:
    before = get(client)["blocks"]
    detail = add_rule(client, 422, kind="daily_limit", max_min=60, weekdays=[0, 1, 2, 3, 4, 5, 6])["detail"]
    assert detail.startswith("Nothing changed: the week of Nov 16 to 22 wouldn't fit.")
    assert len(rules(client)) == 4
    assert get(client)["blocks"] == before


def test_a_daily_limit_is_rounded_down_to_the_slot(client: TestClient) -> None:
    add_rule(client, kind="daily_limit", max_min=200, weekdays=[6])  # Sunday has room for it
    assert [r["max_min"] for r in rules(client) if r["kind"] == "daily_limit"] == [120, 195]


def test_a_rule_for_every_item_sends_no_targets(client: TestClient) -> None:
    add_rule(client, kind="rest_between", min_gap_days=2, every_item=True)
    added = rules(client)[-1]
    assert (added["min_gap_days"], added["every_item"], added["targets"]) == (2, True, [])


def test_editing_an_imported_rule_keeps_its_source_and_kind(db: Path, client: TestClient) -> None:
    rest = rules(client)[-1]
    gym = targets(client)["Gym"]["id"]
    response = client.put(f"/api/rules/{rest['id']}?week={WEEK}", json={"kind": "rest_between", "min_gap_days": 2, "series_ids": [gym]})
    assert response.status_code == 200, response.text
    edited = rules(client)[-1]
    assert (edited["id"], edited["min_gap_days"], edited["source"]) == (rest["id"], 2, "week.toml")
    # The file wins on --replace, as for items.
    import_week(EXAMPLE, db, replace=True)
    assert rules(client)[-1]["min_gap_days"] == 1

    changed_kind = client.put(f"/api/rules/{rules(client)[-1]['id']}?week={WEEK}", json={"kind": "daily_limit", "max_min": 60, "weekdays": [0]})
    assert (changed_kind.status_code, changed_kind.json()["detail"]) == (422, "A rule's kind can't change. Delete it and add another.")


def test_deleting_a_rule_re_plans(client: TestClient) -> None:
    get(client)
    limit = rules(client)[0]
    response = client.delete(f"/api/rules/{limit['id']}?week={WEEK}")
    assert response.status_code == 200, response.text
    assert [r["kind"] for r in rules(client)] == ["time_preference", "time_preference", "rest_between"]
    assert client.delete(f"/api/rules/{limit['id']}?week={WEEK}").status_code == 404


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"kind": "daily_limit", "max_min": 0, "weekdays": [0]}, "Use a length longer than 0m."),
        ({"kind": "daily_limit", "max_min": 1500, "weekdays": [0]}, "A day only has 24h."),
        ({"kind": "daily_limit", "max_min": 60, "weekdays": []}, "Pick at least one day."),
        ({"kind": "rest_between", "min_gap_days": 7, "every_item": True}, "Use a whole number of days from 1 to 6."),
        ({"kind": "rest_between", "min_gap_days": 1}, "Pick at least one item, or choose Every item."),
        (
            {"kind": "time_preference", "every_item": True, "ranges": [{"weekdays": [0], "start_time": "09:00", "end_time": "09:00"}]},
            "Start and end can't be the same time.",
        ),
        ({"kind": "time_preference", "every_item": True, "ranges": []}, "Add at least one range of times."),
        ({"kind": "rest_between", "min_gap_days": 1, "item_ids": [str(uuid4())]}, "One of the picked items no longer exists. Pick again."),
    ],
)
def test_a_bad_rule_is_refused_with_the_dialogs_message(client: TestClient, fields: dict, message: str) -> None:
    assert add_rule(client, 422, **fields)["detail"] == message
    assert len(rules(client)) == 4


# Series (Milestone 6)

OFFICE_HOURS = {
    "title": "Office hours",
    "preset": "exact",
    "start_time": "08:00",
    "end_time": "09:00",
    "freq": "weekly",
    "repeat_weekdays": [1, 4],  # Tue and Fri
    "start_date": "2026-11-16",
}


def add_series(client: TestClient, status: int = 201, **fields) -> dict:  # type: ignore[no-untyped-def]
    response = client.post("/api/series", json={"week_start": WEEK, **fields})
    assert response.status_code == status, response.text
    return response.json()


def local_starts(week: dict, title: str) -> list[str]:
    zone = ZoneInfo("America/Los_Angeles")
    return [
        datetime.fromisoformat(b["start"]).astimezone(zone).strftime("%a %H:%M")
        for b in sorted(blocks_titled(week, title), key=lambda b: b["start"])
    ]


def series_id(week: dict, title: str) -> str:
    return blocks_titled(week, title)[0]["series_id"]


def test_a_series_added_in_the_app_shows_in_every_week_it_repeats_in(client: TestClient) -> None:
    week = add_series(client, **OFFICE_HOURS)
    assert local_starts(week, "Office hours") == ["Tue 08:00", "Fri 08:00"]
    for later in ("2026-11-23", "2026-12-07", "2027-01-04"):
        assert local_starts(get(client, later), "Office hours") == ["Tue 08:00", "Fri 08:00"]
    [repeat] = [r for r in week["series"] if r["id"] == series_id(week, "Office hours")]
    assert (repeat["freq"], repeat["weekdays"], repeat["per_week"]) == ("weekly", [1, 4], False)


def test_a_series_round_trips_through_the_edit_form(client: TestClient) -> None:
    week = add_series(client, **OFFICE_HOURS, end_date="2026-12-18")
    form = client.get(f"/api/series/{series_id(week, 'Office hours')}").json()
    assert form | {"id": None} == {
        "id": None, "source": None, "title": "Office hours", "preset": "exact", "start_time": "08:00:00",
        "end_time": "09:00:00", "weekdays": None, "deadline_time": None, "estimate_min": None,
        "max_chunk_min": None, "one_block_per_day": False, "session_min": None, "freq": "weekly",
        "interval": 1, "repeat_weekdays": [1, 4], "start_date": "2026-11-16", "end_date": "2026-12-18",
        "checkable": False, "on_miss": "skip",  # the defaults for an exact-time item
    }


def test_an_every_day_series_repeats_by_the_week_from_its_monday(client: TestClient) -> None:
    week = add_series(
        client, title="Piano", preset="every_day", weekdays=[0, 1, 2, 3, 4], session_min=30,
        start_time="18:00", end_time="20:00", start_date="2026-11-18",
    )
    assert len(blocks_titled(week, "Piano")) == 5  # Monday on: the series starts on its week's Monday
    assert len(blocks_titled(get(client, "2026-11-30"), "Piano")) == 5
    form = client.get(f"/api/series/{series_id(week, 'Piano')}").json()
    assert (form["preset"], form["session_min"], form["start_date"], form["repeat_weekdays"]) == ("every_day", 30, WEEK, [])
    assert [r["per_week"] for r in week["series"] if r["id"] == series_id(week, "Piano")] == [True]


def test_a_weekly_deadline_series_is_due_on_each_date(client: TestClient) -> None:
    week = add_series(
        client, title="Reading response", preset="before_deadline", estimate_min=60, deadline_time="17:00",
        repeat_weekdays=[2], start_date="2026-11-16",
    )
    ends: dict[str, str] = {}
    for b in blocks_titled(week, "Reading response"):  # next week's may start early too
        ends[b["item_id"]] = max(ends.get(b["item_id"], b["end"]), b["end"])
    items = {i: client.get(f"/api/items/{i}").json()["deadline_date"] for i in ends}
    due = {"2026-11-18": "2026-11-19T01:00:00Z", "2026-11-25": "2026-11-26T01:00:00Z"}  # Wed 5pm PST
    assert "2026-11-18" in items.values()
    assert all(end <= due[items[i]] for i, end in ends.items())


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"start_date": "2026-11-13"}, "can't start in the past"),
        ({"repeat_weekdays": []}, "Pick at least one day to repeat on"),
        ({"end_date": "2026-11-01"}, "end date is before the start date"),
        ({"end_date": "2026-11-16"}, "No day between"),  # a Monday; it repeats Tue and Fri
        ({"interval": 0}, "1 or more"),
        ({"preset": "days", "weekdays": [0], "estimate_min": 60, "freq": "daily"}, "repeats every week"),
        ({"title": " "}, "title"),
        ({"preset": "day", "estimate_min": None}, "Add an estimate"),
    ],
)
def test_a_bad_series_is_refused_with_a_reason(client: TestClient, change: dict, message: str) -> None:
    detail = add_series(client, 422, **(OFFICE_HOURS | change))["detail"]
    assert message in detail


def test_editing_a_series_rebuilds_future_occurrences_but_not_hand_edited_ones(client: TestClient) -> None:
    week = add_series(client, **OFFICE_HOURS)
    sid = series_id(week, "Office hours")
    # Move Friday's by hand to 5pm.
    friday = sorted(blocks_titled(week, "Office hours"), key=lambda b: b["start"])[1]["item_id"]
    form = client.get(f"/api/items/{friday}").json()
    moved = client.put(f"/api/items/{friday}", params={"week": WEEK}, json=form | {"start_time": "17:00", "end_time": "18:00"})
    assert moved.status_code == 200, moved.text

    response = client.put(f"/api/series/{sid}", params={"week": WEEK}, json={"week_start": WEEK, **OFFICE_HOURS, "start_time": "09:00", "end_time": "10:00"})

    assert response.status_code == 200, response.text
    assert local_starts(response.json(), "Office hours") == ["Tue 09:00", "Fri 17:00"]
    assert local_starts(get(client, "2026-11-23"), "Office hours") == ["Tue 09:00", "Fri 09:00"]


def test_editing_a_series_keeps_occurrences_that_already_happened(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    week = add_series(client, **OFFICE_HOURS)
    sid = series_id(week, "Office hours")
    monkeypatch.setattr(api, "now", lambda: datetime(2026, 11, 18, 20, tzinfo=UTC))  # Wed noon PST

    response = client.put(f"/api/series/{sid}", params={"week": WEEK}, json={"week_start": WEEK, **OFFICE_HOURS, "start_time": "09:00", "end_time": "10:00"})

    assert response.status_code == 200, response.text  # its start passed but didn't change
    assert local_starts(response.json(), "Office hours") == ["Tue 08:00", "Fri 09:00"]


def test_deleting_one_occurrence_skips_its_date(client: TestClient, db: Path) -> None:
    week = add_series(client, **OFFICE_HOURS)
    tuesday = sorted(blocks_titled(week, "Office hours"), key=lambda b: b["start"])[0]
    response = client.delete(f"/api/items/{tuesday['item_id']}", params={"week": WEEK})
    assert response.status_code == 200, response.text
    store.clear_plans(store.connect(db))  # plan again from scratch: it must not come back
    assert local_starts(get(client), "Office hours") == ["Fri 08:00"]
    assert local_starts(get(client, "2026-11-23"), "Office hours") == ["Tue 08:00", "Fri 08:00"]


def test_deleting_the_series_keeps_what_already_happened(client: TestClient, db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    week = add_series(client, **OFFICE_HOURS)
    get(client, "2026-11-23")
    sid = series_id(week, "Office hours")
    monkeypatch.setattr(api, "now", lambda: datetime(2026, 11, 18, 20, tzinfo=UTC))  # Wed noon PST

    response = client.delete(f"/api/series/{sid}", params={"week": WEEK})

    assert response.status_code == 200, response.text
    assert local_starts(response.json(), "Office hours") == ["Tue 08:00"]
    assert local_starts(get(client, "2026-11-23"), "Office hours") == []
    assert client.get(f"/api/series/{sid}").json()["end_date"] == "2026-11-17"


def test_deleting_a_series_that_never_happened_deletes_it_whole(client: TestClient) -> None:
    week = add_series(client, **OFFICE_HOURS)
    sid = series_id(week, "Office hours")
    response = client.delete(f"/api/series/{sid}", params={"week": WEEK})
    assert response.status_code == 200, response.text
    assert blocks_titled(response.json(), "Office hours") == []
    assert client.get(f"/api/series/{sid}").status_code == 404


def test_a_new_series_can_be_named_by_a_rule(client: TestClient) -> None:
    week = add_series(client, **OFFICE_HOURS)
    sid = series_id(week, "Office hours")
    targets = client.get("/api/rules/targets").json()
    assert {"id": sid, "kind": "series", "title": "Office hours", "week_start": None} in targets


# Turning a one-off item into a series


def item_titled(client: TestClient, title: str, week: str = WEEK) -> str:
    return blocks_titled(get(client, week), title)[0]["item_id"]


LAB_WEEKLY = {
    "title": "Chemistry lab", "preset": "day", "estimate_min": 120,
    "freq": "weekly", "repeat_weekdays": [2], "start_date": "2026-11-18",  # Wednesdays, from its own date
}


def repeat(client: TestClient, item_id: str, status: int = 200, **fields) -> dict:  # type: ignore[no-untyped-def]
    response = client.post(f"/api/items/{item_id}/repeat", params={"week": WEEK}, json={"week_start": WEEK, **fields})
    assert response.status_code == status, response.text
    return response.json()


def test_an_item_made_to_repeat_becomes_the_first_occurrence(client: TestClient, db: Path) -> None:
    lab = item_titled(client, "Chemistry lab")
    week = repeat(client, lab, **LAB_WEEKLY)

    [block] = blocks_titled(week, "Chemistry lab")
    assert block["item_id"] == lab and block["series_id"] is not None  # same item, now an occurrence
    assert local_starts(get(client, "2026-11-23"), "Chemistry lab")[0].startswith("Wed")
    conn = store.connect(db)
    assert not store.hand_edited(conn, UUID(lab))  # rebuilt from the template, so series edits reach it
    assert client.get(f"/api/items/{lab}").json()["series_id"] == block["series_id"]


def test_an_item_off_the_repeat_days_is_kept_as_it_is(client: TestClient, db: Path) -> None:
    lab = item_titled(client, "Chemistry lab")  # Wednesday
    week = repeat(client, lab, **(LAB_WEEKLY | {"repeat_weekdays": [3], "start_date": "2026-11-18"}))  # Thursdays

    assert local_starts(week, "Chemistry lab")[1].startswith("Thu")  # Wednesday's lab stays, Thursday's comes too
    assert lab in [b["item_id"] for b in blocks_titled(week, "Chemistry lab")]
    later = local_starts(get(client, "2026-11-23"), "Chemistry lab")
    assert len(later) == 1 and later[0].startswith("Thu")
    assert store.hand_edited(store.connect(db), UUID(lab))


def test_a_past_item_can_be_made_to_repeat_from_its_own_date(client: TestClient, db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lab = item_titled(client, "Chemistry lab")
    monkeypatch.setattr(api, "now", lambda: datetime(2026, 11, 19, 20, tzinfo=UTC))  # Thu noon PST, the lab is over

    week = repeat(client, lab, **LAB_WEEKLY)

    assert [b["item_id"] for b in blocks_titled(week, "Chemistry lab")] == [lab]  # its session stays
    assert store.hand_edited(store.connect(db), UUID(lab))  # it already happened, so it's kept as it was
    assert len(blocks_titled(get(client, "2026-11-23"), "Chemistry lab")) == 1
    # Any other start in the past is refused, as for a new series.
    other = item_titled(client, "Study group")
    detail = repeat(client, other, 422, title="Study group", preset="exact", start_time="15:00", end_time="16:30",
                    freq="weekly", repeat_weekdays=[3], start_date="2026-11-12")["detail"]
    assert "can't start in the past" in detail


def test_an_occurrence_cant_be_made_to_repeat_again(client: TestClient) -> None:
    week = add_series(client, **OFFICE_HOURS)
    occurrence = blocks_titled(week, "Office hours")[0]["item_id"]
    assert repeat(client, occurrence, 422, **OFFICE_HOURS)["detail"] == api.ALREADY_REPEATS
