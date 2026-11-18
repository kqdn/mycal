"""Check-ins and on-miss policies through the API (Milestone 7), on a small made-up week."""

from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from mycal import BlockStatus, FlexPreset, Item, OnMiss, SolverSettings, WorkFrame, api, store
from mycal.checkins import CHECK_IN_GRACE

LA = "America/Los_Angeles"
ZONE = ZoneInfo(LA)
WEEK = "2026-11-16"


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=ZONE).astimezone(UTC)


SUNDAY = local(15, 12)


class Clock:
    def __init__(self) -> None:
        self.moment = SUNDAY

    def __call__(self) -> datetime:
        return self.moment


@pytest.fixture
def clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Clock:
    path = tmp_path / "mycal.db"
    monkeypatch.setenv(store.DB_ENV, str(path))
    clock = Clock()
    monkeypatch.setattr(api, "now", clock)
    conn = store.connect(path)
    store.save_settings(conn, SolverSettings(LA))
    store.put_work_frame(conn, WorkFrame("Weekdays", [0, 1, 2, 3, 4], time(9), time(18), LA))
    conn.close()
    return clock


@pytest.fixture
def client(clock: Clock) -> TestClient:
    return TestClient(app=api.app)


def add(item: Item) -> Item:
    conn = store.connect(store.db_path())
    store.put_item(conn, item)
    store.clear_plans(conn)
    conn.close()
    return item


def lecture(on_miss: OnMiss = OnMiss.CATCH_UP) -> Item:
    """Mon 10 to 11am."""
    params = {"start": local(16, 10), "end": local(16, 11)}
    return add(Item("Lecture", FlexPreset.EXACT, preset_params=params, checkable=True, on_miss=on_miss))


def call_home(on_miss: OnMiss = OnMiss.RESCHEDULE, checkable: bool = True) -> Item:
    """1h on Monday between 9am and 10am: one spot, and nowhere to go once it has passed."""
    params = {"day": local(16, 9).astimezone(ZONE).date(), "start_time": time(9), "end_time": time(10)}
    return add(
        Item("Call home", FlexPreset.DAY_RANGE, preset_params=params, estimate_min=60, checkable=checkable, on_miss=on_miss)
    )


def essay(on_miss: OnMiss = OnMiss.RESCHEDULE) -> Item:
    """4h in 1h sessions, due Friday at 5pm."""
    return add(
        Item("Essay", FlexPreset.BEFORE_DEADLINE, estimate_min=240, max_chunk_min=60, deadline=local(20, 17),
             checkable=True, on_miss=on_miss)
    )


def week(client: TestClient) -> dict:
    response = client.get(f"/api/weeks/{WEEK}")
    assert response.status_code == 200, response.text
    return response.json()


def blocks_of(client: TestClient, item: Item) -> list[dict]:
    return sorted((b for b in week(client)["blocks"] if b["item_id"] == str(item.id)), key=lambda b: b["start"])


def pending(client: TestClient) -> list[dict]:
    response = client.get("/api/check-ins")
    assert response.status_code == 200, response.text
    return response.json()


def answer(client: TestClient, block_id: str, answer: str, **fields: object) -> dict:
    return client.post(f"/api/blocks/{block_id}/check-in?week={WEEK}", json={"answer": answer, **fields}).json()


def answered(client: TestClient, block_id: str, answer: str, **fields: object) -> dict:
    response = client.post(f"/api/blocks/{block_id}/check-in?week={WEEK}", json={"answer": answer, **fields})
    assert response.status_code == 200, response.text
    return response.json()


def stored_block(block_id: str) -> object:
    [block] = [b for b in store.list_blocks(store.connect(store.db_path())) if b.id == UUID(block_id)]
    return block


def minutes(block: dict) -> int:
    start, end = datetime.fromisoformat(block["start"]), datetime.fromisoformat(block["end"])
    return (end - start) // timedelta(minutes=1)


# Which blocks ask


def test_only_checkable_blocks_that_have_ended_ask(client: TestClient, clock: Clock) -> None:
    talk = lecture()
    call_home(checkable=False)
    week(client)  # plan as of Sunday

    clock.moment = local(16, 10, 30)  # the lecture is still on, the call is over
    assert pending(client) == []

    clock.moment = local(16, 11)
    [asking] = pending(client)
    assert (asking["item_id"], asking["status"], asking["on_miss"]) == (str(talk.id), "planned", "catch_up")
    assert asking["choices"] == ["catch_up", "skip"]  # an exact item can't be rescheduled


def test_yes_marks_the_block_done(client: TestClient, clock: Clock) -> None:
    lecture()
    week(client)
    clock.moment = local(16, 12)
    [asking] = pending(client)

    shown = answered(client, asking["block_id"], "yes")

    [block] = [b for b in shown["blocks"] if b["id"] == asking["block_id"]]
    assert (block["status"], block["done_min"], block["missed_action"]) == ("done", 60, None)
    assert pending(client) == []


def test_a_block_that_has_not_started_cant_be_answered(client: TestClient) -> None:
    lecture()
    [block] = week(client)["blocks"]

    response = client.post(f"/api/blocks/{block['id']}/check-in?week={WEEK}", json={"answer": "yes"})

    assert response.status_code == 422


# On-miss policies


def test_no_with_reschedule_places_the_work_again(client: TestClient, clock: Clock) -> None:
    work = essay()
    first = blocks_of(client, work)[0]
    clock.moment = datetime.fromisoformat(first["end"])

    answered(client, first["id"], "no")

    later = [b for b in blocks_of(client, work) if b["status"] == "planned" and b["id"] != first["id"]]
    assert sum(minutes(b) for b in later) == 240  # the missed hour is back in the plan
    assert stored_block(first["id"]).missed_action is OnMiss.RESCHEDULE  # type: ignore[attr-defined]


def test_partly_reschedules_only_the_rest(client: TestClient, clock: Clock) -> None:
    work = essay()
    first = blocks_of(client, work)[0]
    clock.moment = datetime.fromisoformat(first["end"])

    shown = answered(client, first["id"], "partly", done_min=30)

    planned = [b for b in shown["blocks"] if b["item_id"] == str(work.id) and b["status"] == "planned"]
    assert sum(minutes(b) for b in planned) == 210


@pytest.mark.parametrize("done", [None, 0, 60, 90])
def test_partly_needs_a_part_of_the_block(client: TestClient, clock: Clock, done: int | None) -> None:
    work = essay()
    first = blocks_of(client, work)[0]
    clock.moment = datetime.fromisoformat(first["end"])

    response = client.post(f"/api/blocks/{first['id']}/check-in?week={WEEK}", json={"answer": "partly", "done_min": done})

    assert response.status_code == 422


def test_no_with_catch_up_adds_a_catch_up_item(client: TestClient, clock: Clock) -> None:
    talk = lecture()
    week(client)
    clock.moment = local(16, 12)
    [asking] = pending(client)

    answered(client, asking["block_id"], "no")

    conn = store.connect(store.db_path())
    [catch_up] = [i for i in store.list_items(conn) if i.catch_up_of == UUID(asking["block_id"])]
    assert (catch_up.title, catch_up.estimate_min, catch_up.flex_preset) == ("Catch up: Lecture", 75, FlexPreset.BEFORE_DEADLINE)
    assert catch_up.deadline == local(23, 12)  # no next lecture or dependent item: a week after the answer
    assert sum(minutes(b) for b in blocks_of(client, catch_up)) == 75
    assert talk.id != catch_up.id


def test_a_catch_up_is_due_before_the_series_next_occurrence(client: TestClient, clock: Clock) -> None:
    from mycal.model import ItemTemplate, Rule, Series

    conn = store.connect(store.db_path())
    template = ItemTemplate(FlexPreset.EXACT, {"start_time": time(10), "end_time": time(11)}, checkable=True,
                            on_miss=OnMiss.CATCH_UP)
    series = Series("Lecture", Rule("weekly", weekdays=[0, 2]), LA, local(16, 0).astimezone(ZONE).date(), template=template)
    store.put_series(conn, series)
    conn.close()
    week(client)
    clock.moment = local(16, 12)
    [asking] = pending(client)

    answered(client, asking["block_id"], "no")

    [catch_up] = [i for i in store.list_items(store.connect(store.db_path())) if i.catch_up_of is not None]
    assert catch_up.deadline == local(18, 10)  # Wednesday's lecture


def test_no_with_skip_drops_the_work(client: TestClient, clock: Clock) -> None:
    work = essay(OnMiss.SKIP)
    first = blocks_of(client, work)[0]
    clock.moment = datetime.fromisoformat(first["end"])

    answered(client, first["id"], "no")

    later = [b for b in blocks_of(client, work) if b["status"] == "planned"]
    assert sum(minutes(b) for b in later) == 180


def test_an_ask_item_needs_a_choice(client: TestClient, clock: Clock) -> None:
    work = essay(OnMiss.ASK)
    first = blocks_of(client, work)[0]
    clock.moment = datetime.fromisoformat(first["end"])

    assert client.post(f"/api/blocks/{first['id']}/check-in?week={WEEK}", json={"answer": "no"}).status_code == 422
    answered(client, first["id"], "no", action="skip")

    assert stored_block(first["id"]).missed_action is OnMiss.SKIP  # type: ignore[attr-defined]


def test_a_reschedule_with_nowhere_to_go_is_refused_and_nothing_changes(client: TestClient, clock: Clock) -> None:
    call = call_home()
    [block] = blocks_of(client, call)
    clock.moment = local(16, 12)

    response = client.post(f"/api/blocks/{block['id']}/check-in?week={WEEK}", json={"answer": "no"})

    assert response.status_code == 422
    assert "Skip" in response.json()["detail"]
    assert stored_block(block["id"]).status is BlockStatus.PLANNED  # type: ignore[attr-defined]
    answered(client, block["id"], "no", action="skip")


def test_changing_a_catch_up_answer_drops_the_catch_up(client: TestClient, clock: Clock) -> None:
    lecture()
    week(client)
    clock.moment = local(16, 12)
    [asking] = pending(client)
    answered(client, asking["block_id"], "no")

    answered(client, asking["block_id"], "yes")

    assert [i for i in store.list_items(store.connect(store.db_path())) if i.catch_up_of is not None] == []


# Unanswered


def test_an_unanswered_check_in_counts_as_no(client: TestClient, clock: Clock) -> None:
    work = essay()
    first = blocks_of(client, work)[0]
    clock.moment = datetime.fromisoformat(first["end"]) + CHECK_IN_GRACE

    assert all(p["block_id"] != first["id"] for p in pending(client))
    block = stored_block(first["id"])
    assert (block.status, block.missed_action) == (BlockStatus.UNANSWERED, OnMiss.RESCHEDULE)  # type: ignore[attr-defined]
    later = [b for b in blocks_of(client, work) if b["status"] == "planned" and b["id"] != first["id"]]
    assert sum(minutes(b) for b in later) == 240


def test_an_unanswered_ask_keeps_waiting_and_can_still_be_answered(client: TestClient, clock: Clock) -> None:
    work = essay(OnMiss.ASK)
    first = blocks_of(client, work)[0]
    clock.moment = datetime.fromisoformat(first["end"]) + CHECK_IN_GRACE

    waiting = [p for p in pending(client) if p["block_id"] == first["id"]]

    assert [p["status"] for p in waiting] == ["unanswered"]
    answered(client, first["id"], "yes")
    assert stored_block(first["id"]).status is BlockStatus.DONE  # type: ignore[attr-defined]


def test_an_unanswered_reschedule_with_nowhere_to_go_waits_for_a_choice(client: TestClient, clock: Clock) -> None:
    call = call_home()
    [block] = blocks_of(client, call)
    clock.moment = datetime.fromisoformat(block["end"]) + CHECK_IN_GRACE

    [waiting] = pending(client)

    assert (waiting["block_id"], waiting["status"]) == (block["id"], "unanswered")
    assert stored_block(block["id"]).missed_action is None  # type: ignore[attr-defined]


# Fewer sessions for "N times a week" items


WORKOUT = {
    "week_start": WEEK, "title": "Workout", "preset": "days", "weekdays": [0, 2, 4],
    "estimate_min": 180, "max_chunk_min": 60, "one_block_per_day": True,
}
TUESDAY_MESSAGE = "Workout gets 2 of 3 sessions this week: only Wed and Fri are left."


def test_adding_with_too_few_days_left_asks_first(client: TestClient, clock: Clock) -> None:
    clock.moment = local(17, 12)

    asked = client.post("/api/items", json=WORKOUT)
    assert (asked.status_code, asked.json()["detail"]) == (409, TUESDAY_MESSAGE)
    assert store.list_items(store.connect(store.db_path())) == []  # nothing saved

    added = client.post("/api/items", json=WORKOUT | {"accept_shortfall": True})
    assert added.status_code == 201, added.text
    assert added.json()["shortfalls"] == []  # accepted, so no banner
    assert sum(minutes(b) for b in added.json()["blocks"]) == 120


def test_a_shortfall_from_viewing_shows_a_banner_until_accepted(client: TestClient, clock: Clock) -> None:
    item = add(
        Item("Workout", FlexPreset.DAYS, preset_params={"week": local(16, 0).astimezone(ZONE).date(), "weekdays": [0, 2, 4]},
             estimate_min=180, max_chunk_min=60, one_block_per_day=True)
    )
    clock.moment = local(17, 12)

    [banner] = week(client)["shortfalls"]
    assert (banner["item_id"], banner["gets"], banner["message"]) == (str(item.id), 2, TUESDAY_MESSAGE)

    accepted = client.post(f"/api/shortfalls/{item.id}/accept?week={WEEK}")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["shortfalls"] == []
    assert week(client)["shortfalls"] == []


def test_a_missed_session_with_no_day_left_asks_first(client: TestClient, clock: Clock) -> None:
    store_conn = store.connect(store.db_path())
    store.put_item(
        store_conn,
        Item("Workout", FlexPreset.DAYS, preset_params={"week": local(16, 0).astimezone(ZONE).date(), "weekdays": [0, 2, 4]},
             estimate_min=180, max_chunk_min=60, one_block_per_day=True, checkable=True),
    )
    store_conn.close()
    monday = week(client)["blocks"][0]
    clock.moment = local(16, 17, 30)  # Monday has no hour left for it, so only Wed and Fri remain

    asked = client.post(f"/api/blocks/{monday['id']}/check-in?week={WEEK}", json={"answer": "no"})
    assert asked.status_code == 409
    assert asked.json()["detail"].startswith("Workout gets 2 of 3 sessions this week")
    assert stored_block(monday["id"]).status is BlockStatus.PLANNED  # type: ignore[attr-defined]

    shown = answered(client, monday["id"], "no", accept_shortfall=True)
    assert shown["shortfalls"] == []
