"""The week API, serving stored plans from a temporary database with the made-up sample week."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mycal import FlexPreset, Item, api, store
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
    assert (week["week_start"], week["timezone"], week["feasible"]) == (WEEK, "America/Los_Angeles", True)
    blocks = {b["title"]: b for b in reversed(week["blocks"])}  # the first block of each title wins
    lecture = blocks["Algorithms lecture"]
    assert (lecture["start"], lecture["end"], lecture["fixed"]) == (
        "2026-11-17T19:00:00Z",  # Tue 11am PST
        "2026-11-17T20:30:00Z",
        True,
    )
    assert blocks["Chemistry lab"]["fixed"] is False
    assert week["frames"][0] == {"start": "2026-11-16T17:00:00Z", "end": "2026-11-17T02:00:00Z"}  # Mon 9 to 6
    assert week["unscheduled"] == [{"id": week["unscheduled"][0]["id"], "title": "Email advisor", "estimate_min": 15}]


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
