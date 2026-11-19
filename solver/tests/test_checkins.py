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


def test_deleting_a_catch_up_item_marks_the_missed_block_skipped(client: TestClient, clock: Clock) -> None:
    lecture()
    week(client)
    clock.moment = local(16, 12)
    [asking] = pending(client)
    answered(client, asking["block_id"], "no")
    [catch_up] = [i for i in store.list_items(store.connect(store.db_path())) if i.catch_up_of is not None]

    response = client.delete(f"/api/items/{catch_up.id}?week={WEEK}")

    assert response.status_code == 200, response.text
    [missed] = [b for b in response.json()["blocks"] if b["id"] == asking["block_id"]]
    assert (missed["status"], missed["missed_action"]) == ("missed", "skip")


def preview(client: TestClient, block_id: str, answer: str, **fields: object) -> dict:
    response = client.post(f"/api/blocks/{block_id}/check-in/preview", json={"answer": answer, **fields})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_preview_shows_the_catch_up_item_and_saves_nothing(client: TestClient, clock: Clock) -> None:
    lecture()
    week(client)
    clock.moment = local(16, 12)
    [asking] = pending(client)

    shown = preview(client, asking["block_id"], "no")

    assert (shown["action"], shown["missed_min"], shown["recording"], shown["due_reason"]) == ("catch_up", 60, True, "a week from now")
    form = shown["catch_up"]
    assert (form["title"], form["preset"], form["estimate_min"]) == ("Catch up: Lecture", "before_deadline", 75)
    assert (form["deadline_date"], form["deadline_time"]) == ("2026-11-23", "12:00:00")
    assert [p["block_id"] for p in pending(client)] == [asking["block_id"]]
    assert all(i.catch_up_of is None for i in store.list_items(store.connect(store.db_path())))


def test_a_preview_of_a_reschedule_or_an_ask_without_a_choice(client: TestClient, clock: Clock) -> None:
    work = essay(OnMiss.ASK)
    first = blocks_of(client, work)[0]
    clock.moment = datetime.fromisoformat(first["end"])

    assert preview(client, first["id"], "no")["action"] is None
    shown = preview(client, first["id"], "partly", done_min=20, action="reschedule")
    assert (shown["action"], shown["missed_min"], shown["catch_up"]) == ("reschedule", 40, None)


def test_a_missed_recording_rounds_up_to_whole_slots(client: TestClient, clock: Clock) -> None:
    params = {"start": local(16, 10), "end": local(16, 10, 30)}
    add(Item("Seminar", FlexPreset.EXACT, preset_params=params, checkable=True, on_miss=OnMiss.CATCH_UP))
    week(client)
    clock.moment = local(16, 12)
    [asking] = pending(client)

    assert preview(client, asking["block_id"], "no")["catch_up"]["estimate_min"] == 45  # 37.5m, up to 15m slots


def test_answering_with_a_changed_catch_up_item_uses_it(client: TestClient, clock: Clock) -> None:
    lecture()
    week(client)
    clock.moment = local(16, 12)
    [asking] = pending(client)
    form = preview(client, asking["block_id"], "no")["catch_up"]
    changed = {**form, "week_start": WEEK, "title": "Watch the recording", "estimate_min": 90}
    changed = {k: v for k, v in changed.items() if k not in ("id", "source", "editable", "series_id")}

    answered(client, asking["block_id"], "no", action="catch_up", catch_up=changed)

    conn = store.connect(store.db_path())
    [catch_up] = [i for i in store.list_items(conn) if i.catch_up_of == UUID(asking["block_id"])]
    assert (catch_up.title, catch_up.estimate_min) == ("Watch the recording", 90)
    answered(client, asking["block_id"], "yes")
    assert [i for i in store.list_items(store.connect(store.db_path())) if i.catch_up_of is not None] == []


def test_a_changed_catch_up_is_refused_when_nothing_is_caught_up(client: TestClient, clock: Clock) -> None:
    lecture()
    week(client)
    clock.moment = local(16, 12)
    [asking] = pending(client)
    item = {"week_start": WEEK, "title": "Watch", "preset": "before_deadline", "deadline_date": "2026-11-20",
            "deadline_time": "17:00", "estimate_min": 60}

    response = client.post(f"/api/blocks/{asking['block_id']}/check-in?week={WEEK}",
                           json={"answer": "no", "action": "skip", "catch_up": item})

    assert response.status_code == 422
    assert stored_block(asking["block_id"]).status is BlockStatus.PLANNED  # type: ignore[attr-defined]


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


def test_a_week_viewed_first_after_the_grace_counts_its_old_check_ins_as_no(client: TestClient, clock: Clock) -> None:
    lecture()
    clock.moment = local(16, 11) + CHECK_IN_GRACE  # the week was never viewed while the lecture was on

    talk = [b for b in week(client)["blocks"] if b["title"] == "Lecture"]

    assert [(b["status"], b["missed_action"]) for b in talk] == [("unanswered", "catch_up")]
    assert any(b["title"] == "Catch up: Lecture" for b in week(client)["blocks"])


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


# Archiving


def test_deleting_an_item_with_history_archives_it(client: TestClient, clock: Clock) -> None:
    work = essay()
    first, *ahead = blocks_of(client, work)
    clock.moment = datetime.fromisoformat(first["end"])
    shown = answered(client, first["id"], "yes")
    assert all(b["history"] and b["kept"] == 1 for b in shown["blocks"] if b["item_id"] == str(work.id))

    response = client.delete(f"/api/items/{work.id}?week={WEEK}")

    assert response.status_code == 200, response.text
    left = [b for b in response.json()["blocks"] if b["item_id"] == str(work.id)]
    assert [(b["id"], b["status"], b["deleted"], b["editable"]) for b in left] == [(first["id"], "done", True, False)]
    assert all(u["id"] != str(work.id) for u in response.json()["unscheduled"])
    assert all(p["block_id"] != first["id"] for p in pending(client))
    conn = store.connect(store.db_path())
    assert store.is_archived(conn, work.id) and store.get_item(conn, work.id) is not None
    kept = [b for b in store.list_blocks(conn, include_archived=True) if b.item_id == work.id]
    assert [str(b.id) for b in kept] == [first["id"]]  # the done session stays, the ones ahead are gone
    assert client.delete(f"/api/items/{work.id}?week={WEEK}").status_code == 404


def test_deleting_an_item_without_history_deletes_it(client: TestClient, clock: Clock) -> None:
    work = essay()
    week(client)

    client.delete(f"/api/items/{work.id}?week={WEEK}")

    assert store.get_item(store.connect(store.db_path()), work.id) is None


# Check-in fields in the item dialog


ESSAY = {
    "week_start": WEEK, "title": "Essay", "preset": "before_deadline", "deadline_date": "2026-11-20",
    "deadline_time": "17:00", "estimate_min": 120,
}
MEETING = {"week_start": WEEK, "title": "Meeting", "preset": "exact", "day": "2026-11-17", "start_time": "10:00", "end_time": "11:00"}


def added_form(client: TestClient, request: dict) -> dict:
    response = client.post("/api/items", json=request)
    assert response.status_code == 201, response.text
    [block] = [b for b in response.json()["blocks"] if b["title"] == request["title"]][:1]
    return client.get(f"/api/items/{block['item_id']}").json()


@pytest.mark.parametrize(("request_", "checkable", "on_miss"), [(ESSAY, True, "reschedule"), (MEETING, False, "skip")])
def test_new_items_check_in_unless_they_are_exact(client: TestClient, request_: dict, checkable: bool, on_miss: str) -> None:
    form = added_form(client, request_)
    assert (form["checkable"], form["on_miss"]) == (checkable, on_miss)


def test_an_exact_item_cant_be_rescheduled(client: TestClient) -> None:
    response = client.post("/api/items", json=MEETING | {"checkable": True, "on_miss": "reschedule"})
    assert response.status_code == 422
    assert "Catch up" in response.json()["detail"]


def test_editing_changes_the_check_in_fields_or_keeps_them_when_left_out(client: TestClient) -> None:
    form = added_form(client, MEETING | {"checkable": True, "on_miss": "catch_up"})
    body = {k: v for k, v in form.items() if k not in ("id", "source", "editable", "series_id", "checkable", "on_miss")}

    kept = client.put(f"/api/items/{form['id']}?week={WEEK}", json=body | {"title": "Seminar"})
    assert kept.status_code == 200, kept.text
    assert client.get(f"/api/items/{form['id']}").json()["on_miss"] == "catch_up"

    changed = client.put(f"/api/items/{form['id']}?week={WEEK}", json=body | {"checkable": False, "on_miss": "ask"})
    assert changed.status_code == 200, changed.text
    after = client.get(f"/api/items/{form['id']}").json()
    assert (after["checkable"], after["on_miss"]) == (False, "ask")
