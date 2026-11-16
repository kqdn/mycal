"""The week API, serving stored plans from a temporary database with the made-up sample week."""

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import UUID, uuid4

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
    return path


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
        {"id": week["unscheduled"][0]["id"], "title": "Email advisor", "estimate_min": 15, "reason": None, "sessions": 0, "editable": False}
    ]


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

    assert [b for b in store.list_blocks(store.connect(db)) if b.start < wednesday_noon] == started
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
