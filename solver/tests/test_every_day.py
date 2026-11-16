""""Every one of these days" items: one session on each open chosen day, and never more work than that."""

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from mycal import Block, Constraint, FlexPreset, Item, SolverSettings, WorkFrame, store
from mycal.demo import parse_week
from mycal.planner import effective_item, plan_weeks, remaining_min, waiting_on_broken_weeks, week_horizon
from mycal.presets import compile_windows

LA = "America/Los_Angeles"
ZONE = ZoneInfo(LA)
W1, W2 = date(2026, 11, 16), date(2026, 11, 23)  # Mondays
BEFORE_THE_WEEK = datetime(2026, 11, 15, 12, tzinfo=UTC)
WEEKDAYS = [0, 1, 2, 3, 4]


def local(day: int, hour: int, minute: int = 0) -> datetime:
    """A local moment in November 2026, as UTC."""
    return datetime(2026, 11, day, hour, minute, tzinfo=ZONE).astimezone(UTC)


def piano(weekdays: list[int] = WEEKDAYS, session: int = 30, **params: object) -> Item:
    estimate = session * len(weekdays)
    return Item(
        "Piano",
        FlexPreset.DAYS,
        preset_params={"week": W1, "weekdays": weekdays, "every_day": True, "session_min": session, **params},
        estimate_min=estimate,
        max_chunk_min=session,
        one_block_per_day=True,
    )


def database(frame: WorkFrame, item: Item, engine: str = "cp_sat") -> tuple[object, SolverSettings]:
    conn = store.connect(":memory:")
    settings = SolverSettings(LA, engine=engine)  # type: ignore[arg-type]
    store.save_settings(conn, settings)
    store.put_work_frame(conn, frame)
    store.put_item(conn, item)
    return conn, settings


def sessions(conn: object, item: Item) -> list[Block]:
    return sorted((b for b in store.list_blocks(conn) if b.item_id == item.id), key=lambda b: b.start)  # type: ignore[arg-type]


def days_of(blocks: list[Block]) -> Counter[date]:
    return Counter(b.start.astimezone(ZONE).date() for b in blocks)


def minutes(block: Block) -> int:
    return (block.end - block.start) // timedelta(minutes=1)


DAYTIME = WorkFrame("Weekdays", WEEKDAYS, time(9), time(18), LA)


@pytest.mark.parametrize("engine", ["cp_sat", "backtracking"])
def test_one_session_on_each_chosen_day(engine: str) -> None:
    item = piano()
    conn, settings = database(DAYTIME, item, engine)

    assert plan_weeks(conn, settings, W1, W1, BEFORE_THE_WEEK) == {W1: True}  # type: ignore[arg-type]

    placed = sessions(conn, item)
    assert days_of(placed) == Counter({W1 + timedelta(days=d): 1 for d in WEEKDAYS})
    assert all(minutes(b) == 30 for b in placed)


def test_windows_are_cut_at_local_midnight() -> None:
    late = WorkFrame("Late", [4], time(23), time(1), LA)  # Fri 11pm to Sat 1am
    item = piano([4], 60)
    week = week_horizon(W1, LA)

    windows = compile_windows(item, [late], LA, week.start, week.end)

    assert windows and all(w.end <= local(21, 0) for w in windows)  # nothing past Friday


def test_an_overnight_frame_never_moves_a_session_past_midnight() -> None:
    item = piano([4], 60)
    conn, settings = database(WorkFrame("Late", [4], time(23), time(1), LA), item)
    # Pull it toward Saturday 12 to 1am: without the cut it would start there, on an unchosen day.
    after_midnight = {"mode": "prefer", "weekdays": [5], "start_time": time(0), "end_time": time(1)}
    store.put_constraint(conn, Constraint(kind="time_preference", params={"item_ids": [item.id], **after_midnight}))  # type: ignore[arg-type]

    plan_weeks(conn, settings, W1, W1, BEFORE_THE_WEEK)  # type: ignore[arg-type]

    [session] = sessions(conn, item)
    assert (session.start, session.end) == (local(20, 23), local(21, 0))


def test_planned_mid_week_only_the_open_days_get_sessions() -> None:
    item = piano()
    conn, settings = database(DAYTIME, item)
    wednesday_noon = local(18, 12)

    plan_weeks(conn, settings, W1, W1, wednesday_noon)  # type: ignore[arg-type]

    assert days_of(sessions(conn, item)) == Counter({date(2026, 11, d): 1 for d in (18, 19, 20)})
    assert effective_item(item, store.list_blocks(conn), [DAYTIME], settings, wednesday_noon).estimate_min == 90  # type: ignore[arg-type]


def test_re_planning_mid_week_keeps_past_sessions_in_place() -> None:
    item = piano()
    conn, settings = database(DAYTIME, item)
    plan_weeks(conn, settings, W1, W1, BEFORE_THE_WEEK)  # type: ignore[arg-type]
    before = sessions(conn, item)

    plan_weeks(conn, settings, W1, W1, local(18, 12))  # type: ignore[arg-type]

    after = sessions(conn, item)
    past = [b for b in before if b.start < local(18, 12)]
    assert [(b.id, b.start) for b in past] == [(b.id, b.start) for b in after[: len(past)]]
    assert days_of(after) == Counter({W1 + timedelta(days=d): 1 for d in WEEKDAYS})


def test_a_session_that_already_started_stays_and_counts_for_today() -> None:
    item = piano()
    conn, settings = database(WorkFrame("Evenings", WEEKDAYS, time(17), time(19), LA), item)
    plan_weeks(conn, settings, W1, W1, BEFORE_THE_WEEK)  # type: ignore[arg-type]
    [wednesday] = [b for b in sessions(conn, item) if b.start.astimezone(ZONE).day == 18]
    assert (wednesday.start, wednesday.end) == (local(18, 17), local(18, 17, 30))

    plan_weeks(conn, settings, W1, W1, local(18, 17, 10))  # re-plan ten minutes into it  # type: ignore[arg-type]

    after = sessions(conn, item)
    assert [(b.start, b.end) for b in after if b.start.astimezone(ZONE).day == 18] == [(local(18, 17), local(18, 17, 30))]
    assert days_of(after) == Counter({W1 + timedelta(days=d): 1 for d in WEEKDAYS})


def test_a_missed_day_never_carries_into_another_day_or_week() -> None:
    item = piano()
    conn, settings = database(DAYTIME, item)
    plan_weeks(conn, settings, W1, W1, BEFORE_THE_WEEK)  # type: ignore[arg-type]
    # Tuesday's session is gone (as if missed); Monday's stays unchecked.
    tuesday = [b for b in sessions(conn, item) if b.start.astimezone(ZONE).day == 17]
    store.save_plan(conn, [b.id for b in tuesday], [], {}, BEFORE_THE_WEEK)  # type: ignore[arg-type]
    saturday = local(21, 12)
    blocks = store.list_blocks(conn)  # type: ignore[arg-type]

    assert remaining_min(item, blocks) == 30  # the stored estimate is out of date
    assert remaining_min(effective_item(item, blocks, [DAYTIME], settings, saturday), blocks) == 0

    store.save_plan(conn, [], [], {W1: False}, saturday)  # type: ignore[arg-type]
    assert item.id not in waiting_on_broken_weeks(conn, settings, W1, saturday)  # type: ignore[arg-type]

    plan_weeks(conn, settings, W1, W2, saturday)  # type: ignore[arg-type]
    after = sessions(conn, item)
    assert len(after) == 4 and all(b.start < local(21, 0) for b in after)  # still no Tuesday, nothing next week


@pytest.mark.parametrize(
    "params, message",
    [
        ({"every_day": True}, "session_min"),
        ({"every_day": True, "session_min": 0}, "positive"),
        ({"session_min": 30}, "needs every_day"),
        ({"every_day": "yes", "session_min": 30}, "bool"),
    ],
)
def test_bad_every_day_params_are_rejected(params: dict, message: str) -> None:
    item = Item("Piano", FlexPreset.DAYS, preset_params={"week": W1, "weekdays": [0], **params}, estimate_min=30)
    week = week_horizon(W1, LA)
    with pytest.raises(ValueError, match=message):
        compile_windows(item, [DAYTIME], LA, week.start, week.end)


@pytest.mark.parametrize("engine", ["cp_sat", "backtracking"])
def test_a_session_off_the_slot_grid_is_planned_rounded_up(engine: str) -> None:
    item = piano(session=20)
    conn, settings = database(DAYTIME, item, engine)

    assert plan_weeks(conn, settings, W1, W1, BEFORE_THE_WEEK) == {W1: True}  # type: ignore[arg-type]

    placed = sessions(conn, item)
    assert days_of(placed) == Counter({W1 + timedelta(days=d): 1 for d in WEEKDAYS})
    assert all(minutes(b) == 30 for b in placed)
    assert store.list_items(conn)[0].preset_params["session_min"] == 20  # type: ignore[arg-type]


# Week files

WEEK_FILE = {
    "timezone": LA,
    "week_start": W1,
    "work_frames": [{"name": "Weekdays", "weekdays": WEEKDAYS, "start_time": time(9), "end_time": time(18)}],
}


def test_a_week_file_fills_in_the_work_fields() -> None:
    raw = {"title": "Piano", "preset": "days", "weekdays": WEEKDAYS, "every_day": True, "session_min": 30}
    [item] = parse_week(WEEK_FILE | {"items": [raw]}).items

    assert (item.estimate_min, item.max_chunk_min, item.one_block_per_day) == (150, 30, True)


def test_a_week_file_rejects_conflicting_every_day_fields() -> None:
    raw = {"title": "Piano", "preset": "days", "weekdays": WEEKDAYS, "every_day": True, "session_min": 30, "estimate_min": 60}
    with pytest.raises(ValueError, match="leave them out"):
        parse_week(WEEK_FILE | {"items": [raw]})


def test_a_week_file_keeps_a_session_off_the_grid_as_written() -> None:
    raw = {"title": "Piano", "preset": "days", "weekdays": WEEKDAYS, "every_day": True, "session_min": 20}
    [item] = parse_week(WEEK_FILE | {"items": [raw]}).items

    assert (item.preset_params["session_min"], item.estimate_min, item.max_chunk_min) == (20, 100, 20)
