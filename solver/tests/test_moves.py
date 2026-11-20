"""Moving blocks by hand (Milestone 9): a moved session locks, and the planner plans around it."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
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


def test_a_running_session_moves_even_to_a_start_in_the_past(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    week = get(client)
    # A session with the half hour before it free (ties place blocks differently on each import).
    call = next(
        b for b in week["blocks"]
        if not b["fixed"] and not any(starts(b) - timedelta(minutes=30) < ends(o) <= starts(b) for o in week["blocks"])
    )
    monkeypatch.setattr(api, "now", lambda: starts(call) + timedelta(minutes=10))
    began = starts(call) - timedelta(minutes=15)  # it really began 15 minutes earlier

    response = move(client, call["id"], began.isoformat())

    assert response.status_code == 200, response.text
    moved = next(b for b in response.json()["proposal"]["blocks"] if b["id"] == call["id"])
    assert starts(moved) == began and moved["locked"] is True


def test_a_session_that_is_over_or_checked_in_stays(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    week = get(client)
    plain = next(b for b in week["blocks"] if not b["fixed"] and not b["checkable"])
    monkeypatch.setattr(api, "now", lambda: ends(plain) + timedelta(minutes=5))
    response = move(client, plain["id"], (ends(plain) + timedelta(hours=1)).isoformat())
    assert (response.status_code, response.json()["detail"]) == (422, api.MOVE_NOT_OPEN)  # ended, never answered

    essay = {"week_start": WEEK, "title": "Essay", "preset": "day", "day": "2026-11-18", "estimate_min": 60, "checkable": True}
    assert client.post("/api/items", json=essay).status_code == 201
    checkable = next(b for b in get(client)["blocks"] if b["title"] == "Essay")
    monkeypatch.setattr(api, "now", lambda: ends(checkable) + timedelta(minutes=5))
    answered = client.post(f"/api/blocks/{checkable['id']}/check-in", params={"week": WEEK}, json={"answer": "yes"})
    assert answered.status_code == 200, answered.text
    response = move(client, checkable["id"], (ends(checkable) + timedelta(hours=1)).isoformat())
    assert (response.status_code, response.json()["detail"]) == (422, api.MOVE_NOT_OPEN)


def test_a_session_already_running_is_in_the_way(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    week = get(client)
    piano = block(week, "Practice piano", 18)
    started = datetime.fromisoformat(piano["start"])
    monkeypatch.setattr(api, "now", lambda: started)
    tail = (started + (datetime.fromisoformat(piano["end"]) - started) / 2).isoformat()  # halfway through

    response = move(client, block(week, "Call home")["id"], tail)

    assert (response.status_code, response.json()["detail"]) == (422, "Practice piano is there already. Pick a free spot.")


# +15 min


def extend(client: TestClient, block_id: str):
    return client.post(f"/api/blocks/{block_id}/extend", params={"week": WEEK}, json={"propose": True})


def starts(b: dict) -> datetime:
    return datetime.fromisoformat(b["start"])


def ends(b: dict) -> datetime:
    return datetime.fromisoformat(b["end"])


def free_after(week: dict, b: dict) -> bool:
    """Nothing starts in the hour after `b` ends (ties place blocks differently on each import)."""
    return not any(ends(b) <= starts(o) < ends(b) + timedelta(hours=1) for o in week["blocks"])


def running(monkeypatch: pytest.MonkeyPatch, b: dict) -> None:
    """Make it 5 minutes into `b`."""
    monkeypatch.setattr(api, "now", lambda: starts(b) + timedelta(minutes=5))


def test_more_time_saves_right_away_when_nothing_moves(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    week = get(client)
    b = next(b for b in week["blocks"] if not b["fixed"] and free_after(week, b))
    estimate = client.get(f"/api/items/{b['item_id']}").json()["estimate_min"]
    running(monkeypatch, b)

    response = extend(client, b["id"])

    assert response.status_code == 200, response.text
    assert response.json()["proposal"] is None
    longer = next(o for o in response.json()["blocks"] if o["id"] == b["id"])
    assert (ends(longer) - ends(b), longer["locked"]) == (timedelta(minutes=15), True)
    assert client.get(f"/api/items/{b['item_id']}").json()["estimate_min"] == estimate + 15


def test_more_time_shows_a_new_plan_when_a_session_moves(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    week = get(client)
    flexible = [b for b in week["blocks"] if not b["fixed"]]
    b, after = next((b, o) for b in flexible for o in flexible if starts(o) == ends(b))  # back to back
    running(monkeypatch, b)

    response = extend(client, b["id"])

    assert response.status_code == 200, response.text
    proposal = response.json()["proposal"]
    assert proposal["summary"] == f"Add 15m to {b['title']}"
    moved = next(o for o in proposal["blocks"] if o["id"] == after["id"])
    assert starts(moved) != starts(after)
    assert next(o for o in response.json()["blocks"] if o["id"] == b["id"])["end"] == b["end"]  # not saved yet


def test_more_time_may_run_into_a_fixed_event(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    week = get(client)
    b = next(b for b in week["blocks"] if not b["fixed"] and free_after(week, b))
    local_end = ends(b).astimezone(LA)
    event = {"week_start": WEEK, "title": "Dentist", "preset": "exact", "day": local_end.date().isoformat(),
             "start_time": local_end.strftime("%H:%M"), "end_time": (local_end + timedelta(minutes=30)).strftime("%H:%M")}
    assert client.post("/api/items", json=event).status_code == 201
    running(monkeypatch, b)

    response = extend(client, b["id"])

    assert response.status_code == 200, response.text
    dentist = next(o for o in response.json()["blocks"] if o["title"] == "Dentist")
    assert [b["id"], dentist["id"]] in response.json()["overlaps"]


def test_a_session_without_check_ins_gets_more_time_only_while_it_runs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = next(b for b in get(client)["blocks"] if not b["fixed"] and not b["checkable"])
    monkeypatch.setattr(api, "now", lambda: ends(b) + timedelta(minutes=5))
    response = extend(client, b["id"])
    assert (response.status_code, response.json()["detail"]) == (422, api.EXTEND_NOT_OPEN)


def test_a_session_that_has_not_started_gets_more_time_too(client: TestClient) -> None:
    week = get(client)
    b = next(b for b in week["blocks"] if not b["fixed"] and free_after(week, b))  # the week hasn't begun

    response = extend(client, b["id"])

    assert response.status_code == 200, response.text
    longer = next(o for o in response.json()["blocks"] if o["id"] == b["id"])
    assert (ends(longer) - ends(b), longer["locked"]) == (timedelta(minutes=15), True)


def test_more_time_with_a_bigger_slot_adds_one_slot(client: TestClient, db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = store.connect(db)
    settings = store.load_settings(conn)
    assert settings is not None
    store.save_settings(conn, replace(settings, slot_min=30))
    store.clear_plans(conn)
    conn.close()
    week = get(client)
    b = next(b for b in week["blocks"] if not b["fixed"] and free_after(week, b))
    running(monkeypatch, b)

    response = extend(client, b["id"])

    longer = next(o for o in response.json()["blocks"] if o["id"] == b["id"])
    assert ends(longer) - ends(b) == timedelta(minutes=30)


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


# This and following events: splitting a series where a repeating event was dragged

OFFICE = {"title": "Office hours", "preset": "exact", "start_time": "08:00", "end_time": "09:00", "freq": "weekly",
          "interval": 1, "repeat_weekdays": [1, 4], "start_date": WEEK, "end_date": "2026-12-04"}  # Tue and Fri


def office_starts(client: TestClient, week: str) -> list[str]:
    blocks = client.get(f"/api/weeks/{week}").json()["blocks"]
    return [starts(b).astimezone(LA).strftime("%a %d %H:%M") for b in blocks if b["title"] == "Office hours"]


def split(client: TestClient, series: str, from_date: str, **changes: object):
    form = client.get(f"/api/series/{series}").json() | {"week_start": WEEK, **changes}
    body = {**form, "from_date": from_date, "propose": True}
    response = client.post(f"/api/series/{series}/split", params={"week": WEEK}, json=body)
    assert response.status_code == 200, response.text
    assert client.post("/api/proposal/accept", params={"week": WEEK}).status_code == 200
    return response


def add_office(client: TestClient) -> str:
    response = client.post("/api/series", json={"week_start": WEEK, **OFFICE})
    assert response.status_code == 201, response.text
    return next(b["series_id"] for b in response.json()["blocks"] if b["title"] == "Office hours")


def test_this_and_following_keeps_the_dates_before_it(client: TestClient) -> None:
    series = add_office(client)

    response = split(client, series, "2026-11-20", start_time="10:00", end_time="11:00")  # from Fri Nov 20

    assert response.json()["proposal"]["summary"] == "Change Office hours from Fri Nov 20"
    assert office_starts(client, WEEK) == ["Tue 17 08:00", "Fri 20 10:00"]
    assert office_starts(client, "2026-11-23") == ["Tue 24 10:00", "Fri 27 10:00"]


def test_this_and_following_from_the_first_date_changes_the_whole_series(client: TestClient) -> None:
    series = add_office(client)

    split(client, series, WEEK, start_time="10:00", end_time="11:00")  # its start date, so nothing comes before

    assert office_starts(client, WEEK) == ["Tue 17 10:00", "Fri 20 10:00"]
    assert client.get(f"/api/series/{series}").json()["start_time"] == "10:00:00"  # the same series, kept


def test_this_and_following_to_another_weekday(client: TestClient) -> None:
    series = add_office(client)

    split(client, series, "2026-11-17", repeat_weekdays=[2, 4])  # Tue Nov 17 dragged to Wed

    assert office_starts(client, WEEK) == ["Wed 18 08:00", "Fri 20 08:00"]


def test_a_hand_edited_date_after_the_split_keeps_its_own_time(client: TestClient, db: Path) -> None:
    series = add_office(client)
    client.get("/api/weeks/2026-11-23")  # creates the occurrences of that week
    items = store.list_items(store.connect(db))
    item = next(i for i in items if i.title == "Office hours" and i.occurrence_date == date(2026, 11, 27))
    form = client.get(f"/api/items/{item.id}").json() | {"start_time": "15:00", "end_time": "16:00"}  # Fri Nov 27 only
    assert client.put(f"/api/items/{item.id}", params={"week": WEEK}, json=form).status_code == 200

    split(client, series, "2026-11-20", start_time="10:00", end_time="11:00")

    assert office_starts(client, "2026-11-23") == ["Tue 24 10:00", "Fri 27 15:00"]


def test_more_time_moves_a_running_fixed_event_s_end(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    week = get(client)
    event = next(b for b in week["blocks"] if b["fixed"] and free_after(week, b))
    running(monkeypatch, event)

    response = extend(client, event["id"])

    assert response.status_code == 200, response.text
    assert response.json()["proposal"] is None  # nothing else moved, so it saved
    same = [b for b in response.json()["blocks"] if b["item_id"] == event["item_id"]]
    assert [(starts(b), ends(b)) for b in same] == [(starts(event), ends(event) + timedelta(minutes=15))]


def test_a_series_change_moves_today_s_started_occurrence_when_unanswered(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    series = add_office(client)  # Tue and Fri, 8 to 9am
    monkeypatch.setattr(api, "now", lambda: datetime(2026, 11, 17, 8, 30, tzinfo=LA))  # Tue 8:30: today's is running
    form = client.get(f"/api/series/{series}").json() | {"week_start": WEEK, "start_time": "15:00", "end_time": "16:00"}

    response = client.put(f"/api/series/{series}", params={"week": WEEK}, json=form | {"propose": True})
    assert response.status_code == 200, response.text
    client.post("/api/proposal/accept", params={"week": WEEK})

    assert office_starts(client, WEEK) == ["Tue 17 15:00", "Fri 20 15:00"]  # today's moved too, not only later ones


def test_this_and_following_moves_today_s_started_occurrence_too(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    series = add_office(client)
    monkeypatch.setattr(api, "now", lambda: datetime(2026, 11, 17, 9, 30, tzinfo=LA))  # Tue 9:30: today's is over, unanswered

    split(client, series, "2026-11-17", start_time="15:00", end_time="16:00")

    assert office_starts(client, WEEK) == ["Tue 17 15:00", "Fri 20 15:00"]


def test_a_series_change_leaves_a_started_occurrence_whose_new_time_has_passed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    series = add_office(client)
    monkeypatch.setattr(api, "now", lambda: datetime(2026, 11, 17, 8, 30, tzinfo=LA))

    split(client, series, "2026-11-17", start_time="06:00", end_time="07:00")  # earlier today: nothing to move to

    assert office_starts(client, WEEK) == ["Tue 17 08:00", "Fri 20 06:00"]
