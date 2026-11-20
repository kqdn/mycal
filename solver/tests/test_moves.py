"""Moving blocks by hand (Milestone 9): a moved session locks, and the planner plans around it."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from mycal import api, store
from mycal.importer import import_week

EXAMPLE = Path(__file__).parent.parent / "examples" / "week.toml"
WEEK = "2026-11-16"
BEFORE_THE_WEEK = datetime(2026, 11, 15, 12, tzinfo=UTC)
LA = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "mycal.db"
    monkeypatch.setenv(store.DB_ENV, str(path))
    monkeypatch.setattr(api, "now", lambda: BEFORE_THE_WEEK)
    import_week(EXAMPLE, path)
    conn = store.connect(path)
    for series in store.list_series(conn):  # keep later weeks empty, as in the API tests
        store.put_series(conn, replace(series, end_date=date(2026, 11, 22)))
    conn.close()
    return path


@pytest.fixture
def client(db: Path) -> Iterator[TestClient]:
    api._drop_proposal()  # the proposal lives in the module, so no test sees another's
    yield TestClient(app=api.app)
    api._drop_proposal()


def at(day: int, hour: int, minute: int = 0) -> str:
    """Nov `day`, 2026 at a local time, as UTC ISO."""
    return datetime(2026, 11, day, hour, minute, tzinfo=LA).astimezone(UTC).isoformat()


def get(client: TestClient) -> dict:
    response = client.get(f"/api/weeks/{WEEK}")
    assert response.status_code == 200, response.text
    return response.json()


def block(week: dict, title: str, day: int | None = None) -> dict:
    """The block of `title`, on Nov `day` if given."""
    return next(
        b for b in week["blocks"]
        if b["title"] == title and (day is None or datetime.fromisoformat(b["start"]).astimezone(LA).day == day)
    )


def move(client: TestClient, block_id: str, start: str, propose: bool = True):
    return client.post(f"/api/blocks/{block_id}/move", params={"week": WEEK}, json={"start": start, "propose": propose})


def same_moment(a: str, b: str) -> bool:
    return datetime.fromisoformat(a) == datetime.fromisoformat(b)


def test_a_moved_session_locks_where_it_was_put_once_accepted(client: TestClient) -> None:
    call = block(get(client), "Call home")
    assert call["locked"] is False

    response = move(client, call["id"], at(18, 19))

    assert response.status_code == 200, response.text
    proposed = next(b for b in response.json()["proposal"]["blocks"] if b["id"] == call["id"])
    assert same_moment(proposed["start"], at(18, 19)) and same_moment(proposed["end"], at(18, 19, 30))
    assert proposed["locked"] is True
    assert response.json()["proposal"]["summary"] == "Move Call home"
    assert block(response.json(), "Call home")["locked"] is False  # not saved yet

    client.post("/api/proposal/accept", params={"week": WEEK})
    stored = block(get(client), "Call home")
    assert (stored["id"], stored["locked"]) == (call["id"], True)
    assert same_moment(stored["start"], at(18, 19))


def test_a_session_the_planner_placed_makes_room(client: TestClient) -> None:
    week = get(client)
    reading = block(week, "Read for seminar", 16)  # 1h 30m
    # Onto the start of design's 2h session, wherever ties put it (ids differ on each import).
    design = block(week, "Project 3: design")

    response = move(client, reading["id"], design["start"])

    assert response.status_code == 200, response.text
    proposed = {b["id"]: b for b in response.json()["proposal"]["blocks"]}
    assert same_moment(proposed[reading["id"]]["start"], design["start"])
    moved_design = proposed.get(design["id"])
    assert moved_design is None or not same_moment(moved_design["start"], design["start"])


@pytest.mark.parametrize(
    "title, day, start, message",
    [
        ("Call home", 19, at(16, 13), "Linear algebra is there already. Pick a free spot."),  # a fixed event
        ("Call home", 19, at(16, 13, 10), api.MOVE_OFF_GRID),
        ("Call home", 19, at(14, 9), api.MOVE_IN_PAST),
        ("Linear algebra", 16, at(16, 9), api.MOVE_ONLY_WORK),
    ],
)
def test_a_move_is_refused(client: TestClient, title: str, day: int, start: str, message: str) -> None:
    target = block(get(client), title, day)
    response = move(client, target["id"], start)
    assert (response.status_code, response.json()["detail"]) == (422, message)
    assert get(client)["proposal"] is None


def test_a_locked_session_is_not_pushed_aside(client: TestClient) -> None:
    week = get(client)
    move(client, block(week, "Call home")["id"], at(18, 19))
    client.post("/api/proposal/accept", params={"week": WEEK})

    piano = block(get(client), "Practice piano", 18)
    response = move(client, piano["id"], at(18, 19, 15))

    assert (response.status_code, response.json()["detail"]) == (422, "Call home is there already. Pick a free spot.")


def test_a_session_that_started_is_not_moved(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    call = block(get(client), "Call home")
    monkeypatch.setattr(api, "now", lambda: datetime.fromisoformat(call["start"]))
    response = move(client, call["id"], at(20, 19))
    assert (response.status_code, response.json()["detail"]) == (422, api.MOVE_NOT_STARTED)


def test_a_session_already_running_is_in_the_way(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    week = get(client)
    piano = block(week, "Practice piano", 18)
    started = datetime.fromisoformat(piano["start"])
    monkeypatch.setattr(api, "now", lambda: started)
    tail = (started + (datetime.fromisoformat(piano["end"]) - started) / 2).isoformat()  # halfway through

    response = move(client, block(week, "Call home")["id"], tail)

    assert (response.status_code, response.json()["detail"]) == (422, "Practice piano is there already. Pick a free spot.")


def test_unlocking_hands_the_session_back(client: TestClient) -> None:
    call = block(get(client), "Call home")
    move(client, call["id"], at(18, 19))
    client.post("/api/proposal/accept", params={"week": WEEK})

    response = client.post(f"/api/blocks/{call['id']}/unlock", params={"week": WEEK}, json={"propose": True})

    assert response.status_code == 200, response.text
    assert response.json()["proposal"]["summary"] == "Unlock Call home"
    client.post("/api/proposal/accept", params={"week": WEEK})
    assert all(not b["locked"] for b in get(client)["blocks"] if b["title"] == "Call home")


def test_only_a_locked_session_can_be_unlocked(client: TestClient) -> None:
    call = block(get(client), "Call home")
    response = client.post(f"/api/blocks/{call['id']}/unlock", params={"week": WEEK}, json={})
    assert response.status_code == 422
